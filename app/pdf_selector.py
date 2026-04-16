from __future__ import annotations

import shutil
import sys
import termios
import tty
from pathlib import Path
from typing import Sequence


ANSI_CLEAR = "\033[2J\033[H"
KEY_UP = "\x1b[A"
KEY_DOWN = "\x1b[B"


def _read_key() -> str:
    first = sys.stdin.read(1)
    if first != "\x1b":
        return first
    second = sys.stdin.read(1)
    if second != "[":
        return first + second
    third = sys.stdin.read(1)
    return first + second + third


def _terminal_width() -> int:
    return max(shutil.get_terminal_size(fallback=(80, 24)).columns, 40)


def _truncate(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return f"{text[: max(0, width - 1)]}…"


def _render_menu(
    pdf_paths: Sequence[Path],
    cursor: int,
    selected: set[int],
    message: str | None,
) -> None:
    width = _terminal_width()
    item_prefix_width = len("> [ ] ")
    item_width = max(8, width - item_prefix_width)
    lines = [
        ANSI_CLEAR,
        _truncate("Select PDFs to load", width),
        _truncate("Use ↑/↓ move, Space toggle, Enter on [done], a all, c clear.", width),
        "",
        _truncate(f"Selected: {len(selected)}", width),
        "",
    ]

    items = ["[done]"] + [path.name for path in pdf_paths]
    for index, label in enumerate(items):
        pointer = ">" if index == cursor else " "
        if index == 0:
            marker = " "
        else:
            marker = "x" if (index - 1) in selected else " "
        lines.append(f"{pointer} [{marker}] {_truncate(label, item_width)}")

    if message:
        lines.extend(["", _truncate(message, width)])

    sys.stdout.write("\033[?25l")
    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()


def select_pdfs_interactively(pdf_paths: Sequence[Path]) -> list[Path]:
    if not pdf_paths:
        return []
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return list(pdf_paths)

    selected: set[int] = set()
    cursor = 1
    message: str | None = None
    original_settings = termios.tcgetattr(sys.stdin.fileno())

    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            _render_menu(pdf_paths, cursor, selected, message)
            message = None
            key = _read_key()

            if key == KEY_UP:
                cursor = (cursor - 1) % (len(pdf_paths) + 1)
                continue
            if key == KEY_DOWN:
                cursor = (cursor + 1) % (len(pdf_paths) + 1)
                continue
            if key.lower() == "a":
                selected = set(range(len(pdf_paths)))
                continue
            if key.lower() == "c":
                selected.clear()
                continue
            if key == " ":
                if cursor > 0:
                    index = cursor - 1
                    if index in selected:
                        selected.remove(index)
                    else:
                        selected.add(index)
                continue
            if key in {"\r", "\n"}:
                if cursor == 0:
                    if not selected:
                        message = "Select at least one PDF before choosing done."
                        continue
                    sys.stdout.write(ANSI_CLEAR)
                    sys.stdout.flush()
                    return [pdf_paths[index] for index in sorted(selected)]
                index = cursor - 1
                if index in selected:
                    selected.remove(index)
                else:
                    selected.add(index)
                continue
            if key in {"q", "\x03"}:
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_settings)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
