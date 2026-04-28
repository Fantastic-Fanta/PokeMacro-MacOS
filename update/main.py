"""Force sync from GitHub (ignores local version and commit cache).

Run from the project root::

    python3 -m update.main

This module is not used by the app UI or macro; it is only for manual runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.git_update import force_http_update


def main() -> int:
    def emit(s: str) -> None:
        print(s, flush=True)

    return 0 if force_http_update(emit) else 1


if __name__ == "__main__":
    raise SystemExit(main())
