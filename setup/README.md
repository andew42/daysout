# One-off data setup

Everything the site serves comes from local files in the data directory
(`$DAYSOUT_DATA`, default `$DAYSOUT/data`, or `./data` in development).
These three scripts populate it; all need internet access **once** — after
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

## 2. Place names (~2 MB of queries, ~22,000 rows)

```bash
python3 import_places.py --db /var/lib/daysout/daysout.db
```

Fills the `places` table so an event that names a town and no postcode can
still be put on the map — a listing that writes "Ludlow Food Festival,
Shropshire" and never an address. The data is Wikidata (CC0), the same
source the scraper already uses for destinations, queried one settlement
type at a time.

A postcode remains the precise route and always wins; this is the coarse
fallback, accurate to a town centroid, which is the right order for
drive-time rings measured in tens of kilometres.

**Only unambiguous names are stored.** There are twenty Middletons in the
UK, and an event at the wrong one is worse than one the map never shows,
so a name shared by two genuinely different places is dropped rather than
guessed at (~1,900 of them).

Re-run it whenever the rules change — the deploy does this for you:

```bash
python3 import_places.py --db /var/lib/daysout/daysout.db --if-stale
```

That imports only when the table was built by different rules from the
ones in the script now, so it is safe to run on every deploy. The rules
change more often than the data does, and a table built by the old ones
looks perfectly healthy from outside: the version that had no Bath in it
gave no sign beyond events quietly failing to be placed.

Check the rules without touching the network:

```bash
python3 import_places.py --self-test
```

## 3. Map tiles (~2–3 GB for Great Britain)

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
