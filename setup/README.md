# One-off data setup

Everything the site serves comes from local files in the data directory
(`$DAYSOUT_DATA`, default `$DAYSOUT/data`, or `./data` in development).
These two scripts populate it; both need internet access **once** — after
that the site runs fully offline.

## 1. Postcodes (~25 MB download, ~60 MB in the database)

```bash
python3 import_postcodes.py --db /var/lib/daysout/daysout.db
```

Downloads Ordnance Survey Code-Point Open (free, Open Government Licence),
converts OSGB36 eastings/northings to WGS84 and fills the `postcodes`
table (~1.7M rows). Re-run quarterly at most — postcodes barely change.
If the automatic download fails, fetch `codepo_gb.zip` manually from the
OS Data Hub (osdatahub.os.uk → OpenData → Code-Point Open) and pass
`--zip codepo_gb.zip`.

Verify the coordinate maths without downloading anything:

```bash
python3 import_postcodes.py --self-test
```

## 2. Map tiles (~2–3 GB for Great Britain)

```bash
./get-tiles.sh --data-dir /var/lib/daysout
```

Extracts Great Britain from the free Protomaps daily planet build into
`uk.pmtiles` (single file, served by the Go server with range requests)
and downloads the basemap fonts/sprites into `basemap/`. For a smaller
download, clip to your area:

```bash
./get-tiles.sh --data-dir /var/lib/daysout --bbox=-3.5,50.5,-1.0,52.5
```

Attribution: the basemap is © OpenStreetMap contributors (shown on the
map, as ODbL requires); postcode data contains OS data © Crown copyright
and Royal Mail data © Royal Mail.
