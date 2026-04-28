from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from update.force_sync import run_brutal_force


def main() -> int:
    def emit(s: str) -> None:
        print(s, flush=True)

    return 0 if run_brutal_force(emit) else 1


if __name__ == "__main__":
    raise SystemExit(main())
