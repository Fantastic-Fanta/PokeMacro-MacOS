from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Non-git installs: set POKEMACRO_GITHUB_REPO=owner/repo or add a single line owner/repo
# in update_repo.txt at the project root. Expects published GitHub Releases (tag e.g. v0.1.5).
# Optional: GITHUB_TOKEN or POKEMACRO_GITHUB_TOKEN for private repos.

_PRESERVE_IF_EXISTS = frozenset({"configs.yaml", ".env"})

GitPullOutcome = Literal["ok", "fail", "unavailable"]


def _should_skip_all() -> bool:
    v = (os.environ.get("POKEMACRO_SKIP_AUTO_UPDATE") or "").strip().lower()
    return v in ("1", "true", "yes")


def _should_skip_git() -> bool:
    v = (os.environ.get("POKEMACRO_SKIP_GIT_UPDATE") or "").strip().lower()
    return v in ("1", "true", "yes")


def _should_skip_http() -> bool:
    v = (os.environ.get("POKEMACRO_SKIP_HTTP_UPDATE") or "").strip().lower()
    return v in ("1", "true", "yes")


def _resolve_github_repo() -> str | None:
    raw = (os.environ.get("POKEMACRO_GITHUB_REPO") or "").strip()
    if raw and "/" in raw and raw.count("/") == 1 and ".." not in raw:
        return raw
    path = PROJECT_ROOT / "update_repo.txt"
    if path.is_file():
        line = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if line:
            candidate = line[0].strip()
            if candidate and "/" in candidate and candidate.count("/") == 1 and ".." not in candidate:
                return candidate
    return None


def _auth_headers() -> dict[str, str]:
    tok = (os.environ.get("POKEMACRO_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _user_agent() -> str:
    try:
        from . import __version__ as ver

        return f"PokeMacro/{ver}"
    except Exception:
        return "PokeMacro"


def _http_json(url: str, emit: Callable[[str], None]) -> Any | None:
    req = Request(url, headers={**_auth_headers(), "User-Agent": _user_agent()})
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        emit(f"[update] GitHub API HTTP {e.code}: {e.reason}")
    except URLError as e:
        emit(f"[update] GitHub API error: {e.reason}")
    except json.JSONDecodeError as e:
        emit(f"[update] GitHub API: invalid JSON ({e})")
    except OSError as e:
        emit(f"[update] GitHub API: {e}")
    return None


def _version_tuple(s: str) -> tuple[int, ...]:
    s = s.strip().lstrip("vV")
    parts: list[int] = []
    for part in s.split("."):
        m = re.match(r"^(\d+)", part)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def _merge_release_tree(src_root: Path, emit: Callable[[str], None]) -> None:
    for path in src_root.rglob("*"):
        if path.is_dir():
            continue
        try:
            rel = path.relative_to(src_root)
        except ValueError:
            continue
        if ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        if rel.suffix == ".pyc":
            continue
        dest = PROJECT_ROOT / rel
        if rel.name in _PRESERVE_IF_EXISTS and dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    emit("[update] Installed release files. Restart the app to load new code.")


def _http_release_update(repo: str, emit: Callable[[str], None]) -> None:
    try:
        from . import __version__ as local_ver
    except Exception:
        local_ver = "0.0.0"

    api = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_json(api, emit)
    if not data or not isinstance(data, dict):
        return

    tag = str(data.get("tag_name") or "").strip()
    zip_url = data.get("zipball_url")
    if not tag or not zip_url or not isinstance(zip_url, str):
        emit("[update] Latest release missing tag or zipball_url.")
        return

    remote_t = _version_tuple(tag)
    local_t = _version_tuple(str(local_ver))
    if remote_t <= local_t:
        emit(f"[update] Already on latest release ({local_ver}).")
        return

    emit(f"[update] Downloading {tag} …")
    req = Request(zip_url, headers={**_auth_headers(), "User-Agent": _user_agent()})
    try:
        with urlopen(req, timeout=180) as resp:
            body = resp.read()
    except HTTPError as e:
        emit(f"[update] Download failed HTTP {e.code}: {e.reason}")
        return
    except URLError as e:
        emit(f"[update] Download failed: {e.reason}")
        return
    except OSError as e:
        emit(f"[update] Download failed: {e}")
        return

    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(body)
        zpath = tmp.name
    extract_dir: str | None = None
    try:
        with zipfile.ZipFile(zpath) as zf:
            members = zf.namelist()
            if not members:
                emit("[update] Empty release zip.")
                return
            extract_dir = tempfile.mkdtemp(prefix="pokemacro-update-")
            zf.extractall(extract_dir)
            inner_root = Path(extract_dir)
            inner = next(inner_root.iterdir(), None)
            if inner is None or not inner.is_dir():
                emit("[update] Unexpected zip layout.")
                return
            _merge_release_tree(inner, emit)
    except zipfile.BadZipFile:
        emit("[update] Downloaded file is not a valid zip.")
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            os.unlink(zpath)
        except OSError:
            pass


def _git_pull(emit: Callable[[str], None]) -> GitPullOutcome:
    if _should_skip_git():
        return "unavailable"
    root = PROJECT_ROOT
    if not (root / ".git").is_dir():
        return "unavailable"
    try:
        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        text = (r.stdout or "").strip() or (r.stderr or "").strip()
        if not text and r.returncode == 0:
            text = "Already up to date."
        for line in (text.splitlines() if text else [f"(exit {r.returncode})"]):
            emit(f"[update] {line}")
        if r.returncode == 0 and text and "already up to date" not in text.lower():
            emit("[update] Restart the app to load any new code.")
        if r.returncode != 0:
            emit(f"[update] git pull failed (exit {r.returncode})")
            return "fail"
        return "ok"
    except FileNotFoundError:
        emit("[update] `git` not on PATH; trying release download if configured.")
        return "unavailable"
    except subprocess.TimeoutExpired:
        emit("[update] git pull timed out.")
        return "fail"
    except OSError as e:
        emit(f"[update] {e}")
        return "fail"


def start_background_update(
    *,
    log_queue: queue.Queue[str] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    def emit(s: str) -> None:
        if log_queue is not None:
            log_queue.put(s)
        elif log_fn is not None:
            log_fn(s)
        else:
            print(s, flush=True)

    def work() -> None:
        if _should_skip_all():
            return
        outcome = _git_pull(emit)
        if outcome == "ok":
            return
        if outcome == "fail":
            return
        if _should_skip_http():
            return
        repo = _resolve_github_repo()
        if not repo:
            if outcome == "unavailable" and not (PROJECT_ROOT / ".git").is_dir():
                emit(
                    "[update] For updates without git, set POKEMACRO_GITHUB_REPO=owner/repo "
                    "or add owner/repo as the first line of update_repo.txt (GitHub Releases)."
                )
            return
        _http_release_update(repo, emit)

    threading.Thread(target=work, daemon=True, name="auto-update").start()
