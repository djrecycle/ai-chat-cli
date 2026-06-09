#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PIP_MIRROR="https://mirrors.aliyun.com/pypi/simple/"
PIP_TRUSTED="mirrors.aliyun.com"
APT_PACKAGES=(python3-venv python3-click python3-rich python3-prompt-toolkit)

pick_system_python() {
  local candidate
  for candidate in /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3; do
    [[ -x "$candidate" ]] || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if "Cursor" not in sys.executable and "AppImage" not in sys.executable else 1)' 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

pip_install() {
  .venv/bin/pip install --no-cache-dir \
    -i "$PIP_MIRROR" \
    --trusted-host "$PIP_TRUSTED" \
    "$@"
}

PYTHON="$(pick_system_python)" || {
  echo "Python 3 sistem tidak ditemukan. Install python3 lalu coba lagi." >&2
  exit 1
}

echo "Python: $PYTHON"
"$PYTHON" --version

echo "Menghapus venv lama..."
rm -rf .venv

echo "Membuat venv baru..."
"$PYTHON" -m venv .venv

if ! .venv/bin/python -c 'import sys; assert "AppImage" not in sys.executable' 2>/dev/null; then
  echo "Gagal: venv masih memakai Cursor AppImage, bukan Python sistem." >&2
  echo "Jalankan script ini di terminal biasa (bukan dari dalam Cursor)." >&2
  exit 1
fi

echo "Mengupgrade pip..."
if ! pip_install -U pip; then
  echo "pip upgrade gagal (PyPI/mirror). Lanjut dengan pip bawaan venv..."
fi

echo "Menginstall dependensi..."
if pip_install -r requirements.txt; then
  pip_install -e .
else
  echo
  echo "pip install dari mirror gagal (sering karena jaringan ke PyPI)."
  echo "Mencoba fallback: paket sistem Ubuntu + venv --system-site-packages..."
  echo

  missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
      missing+=("$pkg")
    fi
  done

  if ((${#missing[@]})); then
    echo "Install paket sistem dulu:"
    echo "  sudo apt update && sudo apt install -y ${missing[*]}"
    echo
    if command -v apt-get &>/dev/null; then
      echo "Menjalankan apt install (butuh sudo)..."
      sudo apt-get update -qq
      sudo apt-get install -y "${missing[@]}"
    else
      echo "apt tidak tersedia. Install paket di atas manual lalu jalankan ulang script ini." >&2
      exit 1
    fi
  fi

  rm -rf .venv
  "$PYTHON" -m venv --system-site-packages .venv
  .venv/bin/pip install --no-deps --no-build-isolation -e .
fi

.venv/bin/python -c "import click, rich, prompt_toolkit, chat_cli; print('Dependensi OK')"

echo
echo "Selesai. Aktifkan venv:"
echo "  source .venv/bin/activate"
echo
echo "Jalankan app:"
echo "  ./aichat"
