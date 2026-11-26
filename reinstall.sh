#!/usr/bin/env bash
# Update aichat yang terpasang di laptop: build .deb dari kode sekarang, lalu install ulang.
#
#   ./reinstall.sh            # sama seperti ./build-deb.sh, lalu sudo apt install
#   ./reinstall.sh --docs     # ikut opsi build-deb.sh
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./build-deb.sh "$@"

DEB="$(ls -t dist/aichat_*_all.deb | head -n 1)"
# --reinstall: versi di pyproject sering belum dinaikkan, tanpa ini apt melewati paketnya.
echo "── sudo apt install --reinstall -y ./$DEB"
sudo apt install --reinstall -y "./$DEB"
echo
echo "aichat terpasang: versi $(dpkg-query -W -f='${Version}' aichat)"
