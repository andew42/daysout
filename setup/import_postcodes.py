#!/usr/bin/env python3
"""Import Ordnance Survey Code-Point Open into the daysout database.

Downloads the free GB postcode file (Open Government Licence — contains OS
data (C) Crown copyright, Royal Mail data (C) Royal Mail), converts each
postcode's OSGB36 easting/northing to WGS84 latitude/longitude, and fills
the postcodes table. Stdlib only. Re-run quarterly if you care about new
postcodes; --zip skips the download if you already have the file.

    python3 import_postcodes.py [--db PATH] [--zip codepo_gb.zip]
    python3 import_postcodes.py --self-test
"""

import argparse
import csv
import io
import math
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path

DOWNLOAD_URL = ("https://api.os.uk/downloads/v1/products/CodePointOpen/"
                "downloads?area=GB&format=CSV&redirect")

# --- OSGB36 easting/northing -> WGS84 lat/lon ------------------------------
# Standard algorithm from the OS "A guide to coordinate systems in Great
# Britain": inverse transverse Mercator on the Airy 1830 ellipsoid, then a
# Helmert transformation to WGS84 (accurate to ~5 m, plenty for postcodes).

AIRY_A, AIRY_B = 6377563.396, 6356256.909
GRS80_A, GRS80_B = 6378137.0, 6356752.3141
F0 = 0.9996012717
LAT0, LON0 = math.radians(49), math.radians(-2)
N0, E0 = -100000.0, 400000.0


def _meridional_arc(a, b, lat, lat0):
    n = (a - b) / (a + b)
    n2, n3 = n * n, n * n * n
    dlat, slat = lat - lat0, lat + lat0
    return b * F0 * (
        (1 + n + 1.25 * n2 + 1.25 * n3) * dlat
        - (3 * n + 3 * n2 + 2.625 * n3) * math.sin(dlat) * math.cos(slat)
        + (1.875 * n2 + 1.875 * n3) * math.sin(2 * dlat) * math.cos(2 * slat)
        - (35.0 / 24.0) * n3 * math.sin(3 * dlat) * math.cos(3 * slat))


def en_to_osgb36(easting, northing):
    """Easting/northing -> (lat, lon) radians on the Airy 1830 ellipsoid."""
    a, b = AIRY_A, AIRY_B
    e2 = 1 - (b * b) / (a * a)

    lat = LAT0
    m = 0.0
    while abs(northing - N0 - m) >= 1e-5:
        lat = (northing - N0 - m) / (a * F0) + lat
        m = _meridional_arc(a, b, lat, LAT0)

    sin_lat, cos_lat, tan_lat = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * sin_lat ** 2)
    rho = a * F0 * (1 - e2) * (1 - e2 * sin_lat ** 2) ** -1.5
    eta2 = nu / rho - 1

    vii = tan_lat / (2 * rho * nu)
    viii = tan_lat / (24 * rho * nu ** 3) * (5 + 3 * tan_lat ** 2 + eta2 - 9 * tan_lat ** 2 * eta2)
    ix = tan_lat / (720 * rho * nu ** 5) * (61 + 90 * tan_lat ** 2 + 45 * tan_lat ** 4)
    x = 1 / (cos_lat * nu)
    xi = 1 / (cos_lat * 6 * nu ** 3) * (nu / rho + 2 * tan_lat ** 2)
    xii = 1 / (cos_lat * 120 * nu ** 5) * (5 + 28 * tan_lat ** 2 + 24 * tan_lat ** 4)
    xiia = 1 / (cos_lat * 5040 * nu ** 7) * (61 + 662 * tan_lat ** 2 + 1320 * tan_lat ** 4 + 720 * tan_lat ** 6)

    de = easting - E0
    lat_out = lat - vii * de ** 2 + viii * de ** 4 - ix * de ** 6
    lon_out = LON0 + x * de - xi * de ** 3 + xii * de ** 5 - xiia * de ** 7
    return lat_out, lon_out


def osgb36_to_wgs84(lat, lon):
    """Helmert datum shift, radians in and out."""
    a, b = AIRY_A, AIRY_B
    e2 = 1 - (b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    x1 = nu * math.cos(lat) * math.cos(lon)
    y1 = nu * math.cos(lat) * math.sin(lon)
    z1 = (1 - e2) * nu * math.sin(lat)

    # Inverse of the published WGS84 -> OSGB36 transformation.
    tx, ty, tz = 446.448, -125.157, 542.060
    s = -20.4894e-6
    rx, ry, rz = (math.radians(r / 3600.0) for r in (0.1502, 0.2470, 0.8421))

    x2 = tx + (1 + s) * x1 - rz * y1 + ry * z1
    y2 = ty + rz * x1 + (1 + s) * y1 - rx * z1
    z2 = tz - ry * x1 + rx * y1 + (1 + s) * z1

    a, b = GRS80_A, GRS80_B
    e2 = 1 - (b * b) / (a * a)
    p = math.sqrt(x2 ** 2 + y2 ** 2)
    lat = math.atan2(z2, p * (1 - e2))
    for _ in range(8):
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z2 + e2 * nu * math.sin(lat), p)
    return lat, math.atan2(y2, x2)


def en_to_wgs84(easting, northing):
    lat, lon = en_to_osgb36(easting, northing)
    lat, lon = osgb36_to_wgs84(lat, lon)
    return math.degrees(lat), math.degrees(lon)


def self_test():
    # Worked example from the OS coordinate systems guide (Caister water
    # tower): E 651409.903, N 313177.270 is 52°39'27.2531"N 1°43'4.5177"E
    # on OSGB36.
    lat, lon = en_to_osgb36(651409.903, 313177.270)
    want_lat = math.radians(52 + 39 / 60 + 27.2531 / 3600)
    want_lon = math.radians(1 + 43 / 60 + 4.5177 / 3600)
    assert abs(lat - want_lat) < 1e-9, (lat, want_lat)
    assert abs(lon - want_lon) < 1e-9, (lon, want_lon)

    # The WGS84 shift moves points ~100 m; sanity-check magnitude/direction
    # (in East Anglia WGS84 latitude is slightly larger, longitude smaller).
    wlat, wlon = en_to_wgs84(651409.903, 313177.270)
    assert 0.0001 < wlat - math.degrees(want_lat) < 0.001, wlat
    assert -0.003 < wlon - math.degrees(want_lon) < -0.0005, wlon
    print("self-test OK: worked example converts correctly")


# --- import ----------------------------------------------------------------

def default_db():
    import os
    data = os.environ.get("DAYSOUT_DATA")
    if not data:
        base = os.environ.get("DAYSOUT")
        data = base + "/data" if base else "data"
    return str(Path(data) / "daysout.db")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=default_db())
    parser.add_argument("--zip", default="", help="already-downloaded codepo_gb.zip")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    if args.zip:
        payload = Path(args.zip).read_bytes()
    else:
        print(f"downloading Code-Point Open (~25 MB) from {DOWNLOAD_URL}")
        request = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "daysout-setup/0.1"})
        with urllib.request.urlopen(request) as response:
            payload = response.read()

    db = sqlite3.connect(args.db)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS postcodes "
               "(postcode TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)")

    count = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [n for n in archive.namelist()
                     if n.lower().endswith(".csv") and "/csv/" in n.lower()]
        if not csv_names:
            sys.exit("no Data/CSV/*.csv files in the archive — not a Code-Point Open zip?")
        db.execute("DELETE FROM postcodes")
        for name in csv_names:
            with archive.open(name) as f:
                for row in csv.reader(io.TextIOWrapper(f, "utf-8")):
                    # Columns: postcode, quality, easting, northing, ...
                    try:
                        easting, northing = float(row[2]), float(row[3])
                    except (IndexError, ValueError):
                        continue
                    lat, lon = en_to_wgs84(easting, northing)
                    db.execute("INSERT OR REPLACE INTO postcodes VALUES (?, ?, ?)",
                               (row[0].replace(" ", "").upper(), round(lat, 6), round(lon, 6)))
                    count += 1
            db.commit()
            print(f"{name}: total {count}")

    db.commit()
    db.close()
    print(f"imported {count} postcodes into {args.db}")


if __name__ == "__main__":
    main()
