import json
from pathlib import Path
from typing import List, Optional, Tuple

import certifi
import requests
import urllib3


def send_discord_webhook(
    webhook_url: str,
    message: str,
    username: Optional[str] = None,
    file_path: Optional[str] = None,
) -> bool:
    if not webhook_url or not webhook_url.strip():
        return False
    verify_options = [certifi.where(), True]
    for verify_option in verify_options:
        try:
            if file_path and Path(file_path).exists():
                with open(file_path, "rb") as f:
                    files = {"file": (Path(file_path).name, f, "image/png")}
                    data = {"content": message, "username": username or "Poopimon Notifier"}
                    response = requests.post(
                        webhook_url,
                        files=files,
                        data=data,
                        timeout=30,
                        verify=verify_option,
                    )
            else:
                response = requests.post(
                    webhook_url,
                    json={"content": message, "username": username or "Poopimon Notifier"},
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                    verify=verify_option,
                )
            if response.status_code in (200, 204):
                return True
            print(f"Discord webhook error: {response.status_code} - {response.text}")
            return False
        except requests.exceptions.SSLError as ssl_error:
            if verify_option == certifi.where():
                continue
            print(f"SSL verification failed, attempting without verification: {ssl_error}")
            try:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                if file_path and Path(file_path).exists():
                    with open(file_path, "rb") as f:
                        files = {"file": (Path(file_path).name, f, "image/png")}
                        data = {"content": message, "username": username or "Poopimon Notifier"}
                        response = requests.post(
                            webhook_url,
                            files=files,
                            data=data,
                            timeout=30,
                            verify=False,
                        )
                else:
                    response = requests.post(
                        webhook_url,
                        json={"content": message, "username": username or "Poopimon Notifier"},
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                        verify=False,
                    )
                if response.status_code in (200, 204):
                    return True
                print(f"Discord webhook error: {response.status_code} - {response.text}")
                return False
            except requests.exceptions.RequestException as e:
                print(f"Failed to send Discord webhook: {e}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Failed to send Discord webhook: {e}")
            return False
    return False


def send_discord_webhook_multifile(
    webhook_url: str,
    message: str,
    file_paths: List[Tuple[str, str]],
    username: Optional[str] = None,
) -> bool:
    if not webhook_url or not webhook_url.strip():
        return False
    name = username or "Poopimon Debuggah"
    payload = {"content": message, "username": name}

    def _content_type(path: str) -> str:
        p = Path(path)
        suffix = (p.suffix or "").lower()
        if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return "image/png" if suffix == ".png" else f"image/{suffix[1:]}"
        if suffix in (".yaml", ".yml"):
            return "text/yaml"
        return "application/octet-stream"

    verify_options = [certifi.where(), True]
    for verify_option in verify_options:
        try:
            files_list: list = []
            opened: list = []
            for i, (filename, file_path) in enumerate(file_paths):
                if Path(file_path).exists():
                    f = open(file_path, "rb")
                    opened.append(f)
                    ct = _content_type(file_path)
                    files_list.append((f"files[{i}]", (filename, f, ct)))
            if not files_list:
                response = requests.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                    verify=verify_option,
                )
            else:
                data = {"payload_json": json.dumps(payload)}
                try:
                    response = requests.post(
                        webhook_url,
                        files=files_list,
                        data=data,
                        timeout=60,
                        verify=verify_option,
                    )
                finally:
                    for f in opened:
                        f.close()
            if response.status_code in (200, 204):
                return True
            return False
        except requests.exceptions.SSLError as ssl_error:
            if verify_option == certifi.where():
                continue
            print(f"SSL verification failed, attempting without verification: {ssl_error}")
            try:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                files_list = []
                opened = []
                for i, (filename, file_path) in enumerate(file_paths):
                    if Path(file_path).exists():
                        f = open(file_path, "rb")
                        opened.append(f)
                        ct = _content_type(file_path)
                        files_list.append((f"files[{i}]", (filename, f, ct)))
                if not files_list:
                    response = requests.post(
                        webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                        verify=False,
                    )
                else:
                    data = {"payload_json": json.dumps(payload)}
                    try:
                        response = requests.post(
                            webhook_url,
                            files=files_list,
                            data=data,
                            timeout=60,
                            verify=False,
                        )
                    finally:
                        for f in opened:
                            f.close()
                if response is not None and response.status_code in (200, 204):
                    return True
                return False
            except requests.exceptions.RequestException as e:
                print(f"Failed to send Discord webhook: {e}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Failed to send Discord webhook: {e}")
            return False
    return False
