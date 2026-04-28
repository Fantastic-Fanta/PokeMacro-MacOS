from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

# Directory that contains ``update/``, ``configs.yaml``, etc.
ROOT = Path(__file__).resolve().parent.parent

from .tls import emit_tls_hint, urlopen_tls

DEFAULT_GITHUB_REPO = "Fantastic-Fanta/PokeMacro-MacOS"
_IGNORE = frozenset({"configs.yaml"})
_PRESERVE = frozenset({".env"})
_COMMIT_CACHE = ROOT / ".poke_update_commit"
_USER_AGENT = "PokeMacro-force-update/1"


def _github_repo_from_url(url: str) -> str | None:
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    if u.startswith("git@github.com:"):
        rest = u.split(":", 1)[1]
        return rest if "/" in rest and rest.count("/") == 1 and ".." not in rest else None
    if "github.com/" in u:
        part = u.split("github.com/", 1)[1].split("/")[0:2]
        if len(part) == 2:
            return f"{part[0]}/{part[1]}" if ".." not in part[0] + part[1] else None
    return None


def _parse_origin_repo() -> str | None:
    cfg = ROOT / ".git" / "config"
    if not cfg.is_file():
        return None
    current: str | None = None
    for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current == 'remote "origin"' and line.startswith("url ="):
            return _github_repo_from_url(line.split("=", 1)[1].strip())
    return None


def resolve_repo() -> str | None:
    p = ROOT / "update_repo.txt"
    if p.is_file():
        lines = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if lines:
            c = lines[0].strip()
            if c and "/" in c and c.count("/") == 1 and ".." not in c:
                return c
    o = _parse_origin_repo()
    if o:
        return o
    if (
        DEFAULT_GITHUB_REPO
        and "/" in DEFAULT_GITHUB_REPO
        and DEFAULT_GITHUB_REPO.count("/") == 1
        and ".." not in DEFAULT_GITHUB_REPO
    ):
        return DEFAULT_GITHUB_REPO.strip()
    return None


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _http_json(url: str, emit: Callable[[str], None]) -> Any | None:
    req = Request(url, headers={**_headers(), "User-Agent": _USER_AGENT})
    try:
        with urlopen_tls(req, timeout=60, emit=emit) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        emit(f"[force-update] GitHub API HTTP {e.code}: {e.reason}")
    except URLError as e:
        emit(f"[force-update] GitHub API error: {e.reason}")
        emit_tls_hint(emit, e)
    except json.JSONDecodeError as e:
        emit(f"[force-update] GitHub API: invalid JSON ({e})")
    except OSError as e:
        emit(f"[force-update] GitHub API: {e}")
    return None


def _merge_tree(src: Path, emit: Callable[[str], None]) -> None:
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        try:
            rel = path.relative_to(src)
        except ValueError:
            continue
        if ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        if rel.suffix == ".pyc":
            continue
        if rel.name in _IGNORE:
            continue
        dest = ROOT / rel
        if rel.name in _PRESERVE and dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    emit("[force-update] Installed files into project root. Restart the app if it was running.")


def _download_zip(zip_url: str, emit: Callable[[str], None]) -> bool:
    req = Request(zip_url, headers={**_headers(), "User-Agent": _USER_AGENT})
    try:
        with urlopen_tls(req, timeout=180, emit=emit) as resp:
            body = resp.read()
    except HTTPError as e:
        emit(f"[force-update] Download failed HTTP {e.code}: {e.reason}")
        return False
    except URLError as e:
        emit(f"[force-update] Download failed: {e.reason}")
        emit_tls_hint(emit, e)
        return False
    except OSError as e:
        emit(f"[force-update] Download failed: {e}")
        return False

    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(body)
        zpath = tmp.name
    extract_dir: str | None = None
    try:
        with zipfile.ZipFile(zpath) as zf:
            if not zf.namelist():
                emit("[force-update] Empty archive.")
                return False
            extract_dir = tempfile.mkdtemp(prefix="pokemacro-force-")
            zf.extractall(extract_dir)
            inner_root = Path(extract_dir)
            inner = next(inner_root.iterdir(), None)
            if inner is None or not inner.is_dir():
                emit("[force-update] Unexpected zip layout.")
                return False
            _merge_tree(inner, emit)
    except zipfile.BadZipFile:
        emit("[force-update] Downloaded file is not a valid zip.")
        return False
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            os.unlink(zpath)
        except OSError:
            pass
    return True


def _sync_default_branch(repo: str, emit: Callable[[str], None]) -> bool:
    info = _http_json(f"https://api.github.com/repos/{repo}", emit)
    if not info or not isinstance(info, dict):
        return False
    branch = str(info.get("default_branch") or "master")
    commit_data = _http_json(
        f"https://api.github.com/repos/{repo}/commits/{branch}",
        emit,
    )
    if not commit_data or not isinstance(commit_data, dict):
        return False
    sha = str(commit_data.get("sha") or "").strip()
    if not sha:
        emit("[force-update] Could not read latest commit on default branch.")
        return False
    zip_url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    emit(f"[force-update] Downloading default branch {branch} @ {sha[:7]} …")
    ok = _download_zip(zip_url, emit)
    if ok:
        try:
            _COMMIT_CACHE.write_text(sha + "\n", encoding="utf-8")
        except OSError as e:
            emit(f"[force-update] Could not save update marker: {e}")
    return ok


def run_brutal_force(emit: Callable[[str], None]) -> bool:
    """Always fetch GitHub: latest release zip if present, else default-branch zip. No version or cache checks."""
    repo = resolve_repo()
    if not repo:
        emit(
            "[force-update] No repo: add ``owner/repo`` as the first line of update_repo.txt "
            f"(optional: origin in .git/config, else built-in default {DEFAULT_GITHUB_REPO!r})."
        )
        return False

    api = f"https://api.github.com/repos/{repo}/releases/latest"
    req = Request(api, headers={**_headers(), "User-Agent": _USER_AGENT})
    try:
        with urlopen_tls(req, timeout=60, emit=emit) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        if e.code == 404:
            emit("[force-update] No GitHub releases; using default-branch snapshot.")
            return _sync_default_branch(repo, emit)
        emit(f"[force-update] GitHub API HTTP {e.code}: {e.reason}")
        return False
    except URLError as e:
        emit(f"[force-update] GitHub API error: {e.reason}")
        emit_tls_hint(emit, e)
        return False
    except json.JSONDecodeError as e:
        emit(f"[force-update] GitHub API: invalid JSON ({e})")
        return False
    except OSError as e:
        emit(f"[force-update] GitHub API: {e}")
        return False

    if not isinstance(data, dict):
        return _sync_default_branch(repo, emit)

    tag = str(data.get("tag_name") or "").strip()
    zip_url = data.get("zipball_url")
    if not tag or not zip_url or not isinstance(zip_url, str):
        emit("[force-update] Latest release missing zipball; using default-branch snapshot.")
        return _sync_default_branch(repo, emit)

    emit(f"[force-update] Downloading release {tag} …")
    return _download_zip(zip_url, emit)
