import os
from pathlib import Path
import subprocess
import sys
import traceback

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pyautogui

from src.git_update import start_background_update
from src.hunter_config import DEFAULT_HUNTER_CONFIG
from src.macro_config import DEFAULT_MACRO_CONFIG, HUNTING_MODE, MODE
from src.macro_runner import MacroRunner
from src.roam_runner import HunterRunner
from src.url_opener import open_roblox_place as join_game


def _normalized_restart_argv(exe: str, root: Path) -> list[str]:
    """Use ``-m src.main`` when the user started via ``python src/main.py`` so imports stay valid."""
    main_py = (root / "src" / "main.py").resolve()
    args = list(sys.argv[1:])
    i = 0
    while i < len(args):
        if args[i] == "-m" and i + 1 < len(args) and args[i + 1] == "src.main":
            return [exe] + args
        if not args[i].startswith("-"):
            try:
                if Path(args[i]).resolve() == main_py:
                    return [exe] + args[:i] + ["-m", "src.main"] + args[i + 1 :]
            except OSError:
                pass
        i += 1
    return [exe] + args


def focus_roblox() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "Roblox" to activate'],
        capture_output=True,
    )


def _restart_after_update() -> None:
    exe = sys.executable
    os.chdir(_ROOT)
    os.execv(exe, _normalized_restart_argv(exe, _ROOT))


def main() -> None:
    start_background_update(restart_callback=_restart_after_update)
    try:
        pyautogui.FAILSAFE = True
        if HUNTING_MODE == "roam":
            focus_roblox()
            HunterRunner(DEFAULT_HUNTER_CONFIG).run()
        else:
            runner = MacroRunner(DEFAULT_MACRO_CONFIG)
            runner.run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if HUNTING_MODE == "egg" and MODE not in ("fast", "quick rejoin"):
        join_game()
    main()
