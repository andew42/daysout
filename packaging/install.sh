#!/usr/bin/env bash
# Daysout installer for an LXD container (or any systemd Linux).
#
# Downloads the latest CI build, installs it to /opt/daysout and sets up the
# server service plus the daily scraper timer. Safe to re-run to upgrade; the
# data directory (/var/lib/daysout) is untouched by upgrades.
#
#   curl -fsSL https://github.com/andew42/daysout/releases/latest/download/install.sh | sudo bash
#
# After the FIRST install, populate the data directory (one-off, ~25 MB + a
# few GB of map tiles):
#
#   cd /opt/daysout/setup
#   python3 import_postcodes.py --db /var/lib/daysout/daysout.db
#   ./get-tiles.sh --data-dir /var/lib/daysout
#
# and optionally run the scraper immediately instead of waiting for the
# 05:30 timer:  systemctl start daysout-scrape

set -euo pipefail

main() {
    REPO="andew42/daysout"
    TARBALL_URL="https://github.com/${REPO}/releases/latest/download/daysout.tar.gz"
    INSTALL_DIR="/opt/daysout"
    DATA_DIR="/var/lib/daysout"

    if [ "$(id -u)" -ne 0 ]; then
        echo "This installer needs root. Re-run with: curl -fsSL ${TARBALL_URL%daysout.tar.gz}install.sh | sudo bash" >&2
        exit 1
    fi

    WORK="$(mktemp -d)"
    trap 'rm -rf "${WORK}"' EXIT

    echo "Downloading ${TARBALL_URL} ..."
    curl -fsSL --retry 4 --retry-delay 2 -o "${WORK}/daysout.tar.gz" "${TARBALL_URL}"

    echo "Installing scraper dependencies (python3 requests + beautifulsoup4)..."
    if command -v apt-get >/dev/null; then
        apt-get install -y -qq python3 python3-requests python3-bs4
    else
        echo "apt-get not found — install python3, requests and beautifulsoup4 yourself" >&2
    fi

    echo "Installing to ${INSTALL_DIR} ..."
    mkdir -p "${INSTALL_DIR}" "${DATA_DIR}"
    rm -f "${INSTALL_DIR}/daysout"
    tar -xzf "${WORK}/daysout.tar.gz" -C "${INSTALL_DIR}"

    # The bundle carries a binary per architecture; keep the right one
    case "$(uname -m)" in
        x86_64) cp "${INSTALL_DIR}/daysout-amd64" "${INSTALL_DIR}/daysout" ;;
        aarch64) cp "${INSTALL_DIR}/daysout-arm64" "${INSTALL_DIR}/daysout" ;;
        *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
    esac
    chmod +x "${INSTALL_DIR}/daysout"

    echo "Installing systemd units..."
    cp "${INSTALL_DIR}"/daysout.service \
       "${INSTALL_DIR}"/daysout-scrape.service \
       "${INSTALL_DIR}"/daysout-scrape.timer /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now daysout
    systemctl enable --now daysout-scrape.timer
    systemctl restart daysout

    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo
    echo "Daysout installed and running."
    echo "  Web UI:  http://${IP:-<container-address>}:8080"
    echo "  Status:  systemctl status daysout"
    echo "  Logs:    journalctl -u daysout -f"
    if [ ! -f "${DATA_DIR}/daysout.db" ] || [ ! -f "${DATA_DIR}/uk.pmtiles" ]; then
        echo
        echo "First install: populate the data directory (see header of this"
        echo "script, or ${INSTALL_DIR}/setup/README.md) for postcode lookup"
        echo "and the offline map."
    fi
}

main "$@"
