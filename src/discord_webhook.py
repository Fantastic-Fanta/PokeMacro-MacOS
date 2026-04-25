import json
from pathlib import Path
from typing import List, Optional, Tuple

import certifi
import requests
import urllib3


def _do_post(webhook_url: str, *, message: str, username: str, file_path: Optional[str], verify) -> bool:
    if file_path and Path(file_path).exists():
        with open(file_path, "rb") as f:
            response = requests.post(
                webhook_url,
                files={"file": (Path(file_path).name, f, "image/png")},
                data={"content": message, "username": username},
                timeout=30,
                verify=verify,
            )
    else:
        response = requests.post(
            webhook_url,
            json={"content": message, "username": username},
            timeout=10,
            verify=verify,
        )
    return response.status_code in (200, 204)


def _content_type(path: str) -> str:
    suffix = (Path(path).suffix or "").lower()
    if suffix == ".png":
        return "image/png"
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".gif":
        return "image/gif"
    if suffix in (".yaml", ".yml"):
        return "text/yaml"
    return "application/octet-stream"


def _do_post_multifile(webhook_url: str, *, payload: dict, file_paths: List[Tuple[str, str]], verify) -> bool:
    files_list = []
    opened = []
    for i, (filename, file_path) in enumerate(file_paths):
        if Path(file_path).exists():
            f = open(file_path, "rb")
            opened.append(f)
            files_list.append((f"files[{i}]", (filename, f, _content_type(file_path))))
    try:
        if not files_list:
            response = requests.post(webhook_url, json=payload, timeout=10, verify=verify)
        else:
            response = requests.post(
                webhook_url,
                files=files_list,
                data={"payload_json": json.dumps(payload)},
                timeout=60,
                verify=verify,
            )
        return response.status_code in (200, 204)
    finally:
        for f in opened:
            f.close()


def _with_ssl_fallback(fn) -> bool:
    for verify in (certifi.where(), False):
        try:
            return fn(verify)
        except requests.exceptions.SSLError:
            if verify is False:
                return False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except requests.exceptions.RequestException as e:
            print(f"Failed to send Discord webhook: {e}")
            return False
    return False


def send_discord_webhook(
    webhook_url: str,
    message: str,
    username: Optional[str] = None,
    file_path: Optional[str] = None,
) -> bool:
    if not webhook_url or not webhook_url.strip():
        return False
    name = username or "Poopimon Notifier"
    return _with_ssl_fallback(
        lambda verify: _do_post(webhook_url, message=message, username=name, file_path=file_path, verify=verify)
    )


def send_discord_webhook_multifile(
    webhook_url: str,
    message: str,
    file_paths: List[Tuple[str, str]],
    username: Optional[str] = None,
) -> bool:
    if not webhook_url or not webhook_url.strip():
        return False
    payload = {"content": message, "username": username or "Poopimon Debuggah"}
    return _with_ssl_fallback(
        lambda verify: _do_post_multifile(webhook_url, payload=payload, file_paths=file_paths, verify=verify)
    )
