import subprocess
import sys


def open_roblox_place(place_id: str = "133300157364376") -> bool:
    url_string = f"roblox://placeid={place_id}"
    return open_url(url_string)


def open_url(url_string: str) -> bool:
    try:
        subprocess.run(["open", url_string], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error opening URL {url_string}: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Unexpected error opening URL {url_string}: {e}", file=sys.stderr)
        return False
