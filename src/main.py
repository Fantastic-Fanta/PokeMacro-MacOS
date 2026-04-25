import subprocess
import sys
import traceback

import pyautogui

from .hunter_config import DEFAULT_HUNTER_CONFIG
from .macro_config import DEFAULT_MACRO_CONFIG, HUNTING_MODE, MODE
from .macro_runner import MacroRunner
from .roam_runner import HunterRunner
from .url_opener import open_roblox_place as join_game


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
        else:
            runner = MacroRunner(DEFAULT_MACRO_CONFIG)
            runner.run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if HUNTING_MODE == "egg" and MODE != "fast":
        join_game()
    main()
