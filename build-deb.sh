#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  build-deb.sh — Build .deb package untuk ai-chat-cli
#
#  Cara pakai:
#    chmod +x build-deb.sh
#    ./build-deb.sh              # build normal
#    ./build-deb.sh --docs       # build dengan optional deps (Pillow, pypdf, dll)
#
#  Output:  dist/aichat_<version>_all.deb
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Parse flags ──────────────────────────────────────────────
INCLUDE_DOCS=false
for arg in "$@"; do
  case "$arg" in
    --docs) INCLUDE_DOCS=true ;;
    -h|--help)
      echo "Usage: $0 [--docs]"
      echo "  --docs   Include optional document dependencies (Pillow, pypdf, etc.)"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

# ── Extract metadata dari pyproject.toml ─────────────────────
VERSION=$(python3 -c "
import re, pathlib
text = pathlib.Path('pyproject.toml').read_text()
m = re.search(r'version\s*=\s*\"([^\"]+)\"', text)
print(m.group(1) if m else '0.0.0')
")

PACKAGE="aichat"
ARCH="all"
DEB_NAME="${PACKAGE}_${VERSION}_${ARCH}"
DIST_DIR="$ROOT/dist"
STAGE="$DIST_DIR/$DEB_NAME"

echo "╔══════════════════════════════════════════════════╗"
echo "║  Building: ${PACKAGE} v${VERSION}               "
echo "║  Output:   dist/${DEB_NAME}.deb                 "
echo "╚══════════════════════════════════════════════════╝"
echo

# ── Cleanup stage ────────────────────────────────────────────
rm -rf "$STAGE"
mkdir -p "$STAGE"

# ── 1) DEBIAN control files ─────────────────────────────────
mkdir -p "$STAGE/DEBIAN"

cat > "$STAGE/DEBIAN/control" << EOF
Package: ${PACKAGE}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10)
Suggests: python3-pil, python3-pypdf, tesseract-ocr, python3-docx
Maintainer: DJ Recycle <djrecycle@users.noreply.github.com>
Description: DJ Chat AI — terminal chat untuk Ollama, LocalAI, dan Gemini
 Aplikasi chat AI cantik berbasis terminal dengan dukungan
 multi-provider (Ollama, LocalAI, OpenAI, Gemini), rich markdown
 rendering, syntax highlighting, dan TUI interaktif.
Homepage: https://github.com/djrecycle/ai-chat-cli
EOF

# ── 2) Post-install: set permissions ────────────────────────
cat > "$STAGE/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
# Pastikan wrapper bisa dieksekusi
chmod +x /usr/bin/aichat 2>/dev/null || true
echo ""
echo "  ✅  aichat berhasil diinstall!"
echo "  Jalankan:  aichat --help"
echo ""
POSTINST
chmod 0755 "$STAGE/DEBIAN/postinst"

# ── 3) Post-remove: cleanup ────────────────────────────────
cat > "$STAGE/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
  # Hapus config user jika purge
  rm -rf /opt/aichat 2>/dev/null || true
fi
POSTRM
chmod 0755 "$STAGE/DEBIAN/postrm"

# ── 4) Install app source → /opt/aichat/ ────────────────────
INSTALL_ROOT="$STAGE/opt/aichat"
mkdir -p "$INSTALL_ROOT"

# Copy source package
cp -r "$ROOT/chat_cli" "$INSTALL_ROOT/chat_cli"
cp "$ROOT/pyproject.toml" "$INSTALL_ROOT/"
cp "$ROOT/requirements.txt" "$INSTALL_ROOT/"

# Hapus __pycache__ dari source
find "$INSTALL_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_ROOT" -name "*.pyc" -delete 2>/dev/null || true

# ── 5) Install Python dependencies → /opt/aichat/lib/ ───────
echo "📦 Menginstall dependencies dengan pip..."
LIB_DIR="$INSTALL_ROOT/lib"
mkdir -p "$LIB_DIR"

pip3 install --target="$LIB_DIR" \
  --no-cache-dir \
  --no-compile \
  click'>=8.1.0' \
  rich'>=13.7.0' \
  prompt-toolkit'>=3.0.43' \
  2>&1 | tail -5

if $INCLUDE_DOCS; then
  echo "📦 Menginstall optional document dependencies..."
  pip3 install --target="$LIB_DIR" \
    --no-cache-dir \
    --no-compile \
    'Pillow>=10.0.0' \
    'pypdf>=4.0.0' \
    'pytesseract>=0.3.10' \
    'python-docx>=1.1.0' \
    2>&1 | tail -5
fi

# Cleanup unnecessary files dari lib
find "$LIB_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$LIB_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$LIB_DIR" -name "*.pyc" -delete 2>/dev/null || true

# ── 6) Wrapper script → /usr/bin/aichat ──────────────────────
mkdir -p "$STAGE/usr/bin"

cat > "$STAGE/usr/bin/aichat" << 'WRAPPER'
#!/usr/bin/env bash
# ai-chat-cli wrapper — installed by aichat .deb package
export PYTHONPATH="/opt/aichat/lib:/opt/aichat${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m chat_cli "$@"
WRAPPER
chmod 0755 "$STAGE/usr/bin/aichat"

# ── 7) Man page (optional, basic) ───────────────────────────
mkdir -p "$STAGE/usr/share/man/man1"
cat > "$STAGE/usr/share/man/man1/aichat.1" << MANPAGE
.TH AICHAT 1 "$(date +"%B %Y")" "${VERSION}" "AI Chat CLI"
.SH NAME
aichat \- terminal chat AI untuk Ollama, LocalAI, dan Gemini
.SH SYNOPSIS
.B aichat
[\fIOPTIONS\fR]
.SH DESCRIPTION
DJ Chat AI adalah aplikasi chat AI berbasis terminal dengan dukungan
multi-provider (Ollama, LocalAI, OpenAI, Gemini), rich markdown rendering,
syntax highlighting, dan TUI interaktif.
.SH OPTIONS
.TP
.B \-\-help
Tampilkan bantuan
.TP
.B \-\-version
Tampilkan versi
.SH AUTHOR
DJ Recycle
MANPAGE
gzip -9 "$STAGE/usr/share/man/man1/aichat.1"

# ── 8) Desktop & copyright ──────────────────────────────────
mkdir -p "$STAGE/usr/share/doc/$PACKAGE"
cat > "$STAGE/usr/share/doc/$PACKAGE/copyright" << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: ai-chat-cli
Source: https://github.com/djrecycle/ai-chat-cli

Files: *
Copyright: $(date +%Y) DJ Recycle
License: MIT
EOF

# ── 9) Fix permissions ──────────────────────────────────────
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE/opt" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/aichat"

# ── 10) Build .deb ──────────────────────────────────────────
echo
echo "🔨 Building .deb package..."
dpkg-deb --build --root-owner-group "$STAGE" "$DIST_DIR/${DEB_NAME}.deb"

# ── 11) Info ─────────────────────────────────────────────────
DEB_SIZE=$(du -sh "$DIST_DIR/${DEB_NAME}.deb" | cut -f1)
echo
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅  Build selesai!                              "
echo "║                                                  "
echo "║  📦  dist/${DEB_NAME}.deb  (${DEB_SIZE})        "
echo "║                                                  "
echo "║  Install:                                        "
echo "║    sudo dpkg -i dist/${DEB_NAME}.deb             "
echo "║                                                  "
echo "║  Uninstall:                                      "
echo "║    sudo dpkg -r ${PACKAGE}                       "
echo "╚══════════════════════════════════════════════════╝"
echo

# Cleanup staging directory (keep .deb)
rm -rf "$STAGE"
