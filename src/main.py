import subprocess
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pyautogui

from src.hunter_config import DEFAULT_HUNTER_CONFIG
from src.macro_config import DEFAULT_MACRO_CONFIG, HUNTING_MODE, MODE
from src.macro_runner import MacroRunner
from src.roam_runner import HunterRunner
from src.static_runner import StaticRunner
from src.url_opener import open_roblox_place as join_game


def focus_roblox() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "Roblox" to activate'],
        capture_output=True,
    )


def main() -> None:
    try:
        pyautogui.FAILSAFE = True
        if HUNTING_MODE == "roam":
            focus_roblox()
            HunterRunner(DEFAULT_HUNTER_CONFIG).run()
        elif HUNTING_MODE == "static":
            focus_roblox()
            StaticRunner().run()
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
