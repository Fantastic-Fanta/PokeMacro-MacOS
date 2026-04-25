import subprocess
import sys


def open_roblox_place(place_id: str = "133300157364376") -> bool:
    try:
        subprocess.run(["open", f"roblox://placeid={place_id}"], check=True)
        return True
    except Exception as e:
        print(f"Error opening Roblox: {e}", file=sys.stderr)
        return False
