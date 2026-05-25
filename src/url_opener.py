import subprocess
import sys


def open_roblox_place(place_id: str = "110569687091409") -> bool:
    try:
        subprocess.run(["open", f"roblox://placeid={place_id}"], check=True)
        return True
    except Exception as e:
        print(f"Error opening Roblox: {e}", file=sys.stderr)
        return False
