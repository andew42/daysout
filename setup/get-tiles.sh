#!/bin/bash
# Download the offline map: a PMTiles extract of Great Britain from the free
# Protomaps daily planet build, plus the basemap fonts/sprites the style
# needs. Safe to re-run: a complete, valid archive is kept; a partial one
# from an interrupted download is re-fetched.
#
#   ./get-tiles.sh [--data-dir DIR] [--bbox minLon,minLat,maxLon,maxLat]
#
# The GB extract is roughly 2-3 GB. For a smaller download pass a bbox
# around home, e.g. --bbox=-3.5,50.5,-1.0,52.5
set -euo pipefail

DATA_DIR="${DAYSOUT_DATA:-${DAYSOUT:+$DAYSOUT/data}}"
DATA_DIR="${DATA_DIR:-data}"
BBOX="-8.65,49.85,1.78,60.90"   # Great Britain
PMTILES_VERSION="1.28.0"        # go-pmtiles CLI release

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --data-dir=*) DATA_DIR="${1#*=}"; shift ;;
    --bbox) BBOX="$2"; shift 2 ;;
    --bbox=*) BBOX="${1#*=}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

# The pmtiles CLI does the extract over HTTP range requests (only the tiles
# inside the bbox are downloaded) and validates the finished archive.
if ! command -v pmtiles >/dev/null && [ ! -x ./pmtiles ]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) ASSET="Linux_x86_64" ;;
    aarch64) ASSET="Linux_arm64" ;;
    *) echo "unsupported architecture $ARCH — install pmtiles manually" >&2; exit 1 ;;
  esac
  echo "downloading pmtiles CLI v$PMTILES_VERSION"
  curl -fsSL --retry 4 --retry-delay 2 \
    "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_${ASSET}.tar.gz" \
    | tar -xz pmtiles
fi
PMTILES="$(command -v pmtiles || echo ./pmtiles)"

# A valid existing archive means this is a re-run — keep it. A file that
# fails verification is a partial from an interrupted download — redo it.
if [ -f uk.pmtiles ] && "$PMTILES" verify uk.pmtiles >/dev/null 2>&1; then
  echo "uk.pmtiles already present and valid — skipping tile download"
else
  rm -f uk.pmtiles
  # Yesterday's daily planet build (today's may not exist yet). Extract to a
  # temp name and move into place only on success, so an interrupted run can
  # never leave a partial file that looks complete.
  BUILD="$(date -u -d yesterday +%Y%m%d)"
  echo "extracting bbox $BBOX from build $BUILD (this is the big download)"
  for attempt in 1 2 3; do
    rm -f uk.pmtiles.partial
    if "$PMTILES" extract "https://build.protomaps.com/${BUILD}.pmtiles" \
         uk.pmtiles.partial --bbox="$BBOX"; then
      mv uk.pmtiles.partial uk.pmtiles
      break
    fi
    echo "extract attempt $attempt failed" >&2
    if [ "$attempt" = 3 ]; then
      echo "giving up after 3 attempts" >&2
      exit 1
    fi
    sleep 15
  done
fi

# Fonts and sprites for the basemap style, served locally at /basemap/.
if [ -d basemap/fonts ]; then
  echo "basemap assets already present — skipping"
else
  echo "downloading basemap fonts and sprites"
  rm -rf basemap basemaps-assets-main
  curl -fsSL --retry 4 --retry-delay 2 \
    https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz | tar -xz
  mv basemaps-assets-main basemap
fi

echo "done: $(du -h uk.pmtiles | cut -f1) of tiles in $DATA_DIR/uk.pmtiles"
