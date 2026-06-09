"""Clipboard helpers used by both terminal and full-screen UI modes."""

from __future__ import annotations

import shutil
import subprocess


def copy_to_system_clipboard(text: str) -> bool:
    """Best-effort copy to the desktop clipboard.

    Returns True when an external clipboard command accepted the text. The TUI
    also stores the text in prompt-toolkit's internal clipboard, so copy still
    works inside the app even when the desktop clipboard tool is unavailable.
    """

    commands = [
        ("wl-copy", []),
        ("xclip", ["-selection", "clipboard"]),
        ("xsel", ["--clipboard", "--input"]),
        ("pbcopy", []),
        ("clip.exe", []),
    ]
    for executable, args in commands:
        path = shutil.which(executable)
        if not path:
            continue
        try:
            subprocess.run(
                [path, *args],
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False
