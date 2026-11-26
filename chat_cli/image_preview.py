"""Helpers for opening generated images outside the terminal."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


GENERATED_IMAGE_PATTERN = re.compile(r"\[Gambar berhasil dibuat:\s*([^\]]+)\]")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def extract_generated_image_paths(text: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for match in GENERATED_IMAGE_PATTERN.finditer(text):
        path = Path(match.group(1).strip()).expanduser()
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def open_image(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser()
    if not resolved.exists():
        return False, f"File gambar tidak ditemukan: {resolved}"
    if resolved.suffix.lower() not in IMAGE_EXTENSIONS:
        return False, f"File bukan format gambar yang didukung: {resolved}"

    try:
        if sys.platform.startswith("linux"):
            opener = shutil.which("xdg-open")
            if opener is None:
                return False, "Tidak menemukan xdg-open untuk membuka gambar."
            subprocess.Popen(
                [opener, str(resolved)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(resolved)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        elif os.name == "nt":
            os.startfile(resolved)  # type: ignore[attr-defined]
        else:
            return False, "Platform ini belum didukung untuk popup gambar otomatis."
    except OSError as exc:
        return False, f"Gagal membuka gambar: {exc}"

    return True, f"Membuka gambar: {resolved}"
