from __future__ import annotations

import json
import os
import queue
import re
import shutil
from itertools import zip_longest
import tempfile
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .github_http import emit_tls_hint, urlopen_tls

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEV_SKIP_AUTO_UPDATE = PROJECT_ROOT / "dev"

# Default for zip installs; overridden by update_repo.txt (first line: owner/repo)
# or by remote origin in .git/config when present.
UPDATE_GITHUB_REPO: str | None = "Fantastic-Fanta/PokeMacro-MacOS"

# Never install these from a release (local config and secrets stay untouched).
_IGNORE_FROM_RELEASE = frozenset({"configs.yaml"})
_PRESERVE_IF_EXISTS = frozenset({".env"})
_UPDATE_COMMIT_CACHE = PROJECT_ROOT / ".poke_update_commit"
_INIT_VERSION_RE = re.compile(
    r"""^__version__\s*=\s*['\"]([^'\"]+)['\"]""", re.MULTILINE
)


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


def _parse_github_repo_from_git_config() -> str | None:
    cfg = PROJECT_ROOT / ".git" / "config"
    if not cfg.is_file():
        return None
    current: str | None = None
    for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current == 'remote "origin"' and line.startswith("url ="):
            url = line.split("=", 1)[1].strip()
            return _github_repo_from_url(url)
    return None


def _resolve_github_repo() -> str | None:
    path = PROJECT_ROOT / "update_repo.txt"
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if lines:
            candidate = lines[0].strip()
            if candidate and "/" in candidate and candidate.count("/") == 1 and ".." not in candidate:
                return candidate
    parsed = _parse_github_repo_from_git_config()
    if parsed:
        return parsed
    if (
        UPDATE_GITHUB_REPO
        and "/" in UPDATE_GITHUB_REPO
        and UPDATE_GITHUB_REPO.count("/") == 1
        and ".." not in UPDATE_GITHUB_REPO
    ):
        return UPDATE_GITHUB_REPO.strip()
    return None


def _github_api_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _user_agent() -> str:
    try:
        from . import __version__ as ver

        return f"PokeMacro/{ver}"
    except Exception:
        return "PokeMacro"


def _http_json(url: str, emit: Callable[[str], None]) -> Any | None:
    req = Request(url, headers={**_github_api_headers(), "User-Agent": _user_agent()})
    try:
        with urlopen_tls(req, timeout=60, emit=emit) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        emit(f"[update] GitHub API HTTP {e.code}: {e.reason}")
    except URLError as e:
        emit(f"[update] GitHub API error: {e.reason}")
        emit_tls_hint(emit, e)
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


def _version_gt(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """True iff ``a`` is strictly greater than ``b`` (numeric segments, zero-padded)."""
    for x, y in zip_longest(a, b, fillvalue=0):
        if x != y:
            return x > y
    return False


def _version_from_init_py(text: str) -> str | None:
    m = _INIT_VERSION_RE.search(text)
    return m.group(1).strip() if m else None


def _remote_root_version(
    repo: str, git_ref: str, emit: Callable[[str], None]
) -> str | None:
    owner, sep, name = repo.partition("/")
    if not sep or "/" in name or not owner or not name:
        return None
    url = f"https://raw.githubusercontent.com/{owner}/{name}/{git_ref}/src/__init__.py"
    req = Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urlopen_tls(req, timeout=30, emit=emit) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code != 404:
            emit(f"[update] Could not read remote src/__init__.py: HTTP {e.code}")
        return None
    except URLError as e:
        emit(f"[update] Could not read remote src/__init__.py: {e.reason}")
        emit_tls_hint(emit, e)
        return None
    except OSError as e:
        emit(f"[update] Could not read remote src/__init__.py: {e}")
        return None
    ver = _version_from_init_py(body)
    if not ver:
        emit("[update] Remote src/__init__.py has no __version__.")
    return ver


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
        if rel.name in _IGNORE_FROM_RELEASE:
            continue
        dest = PROJECT_ROOT / rel
        if rel.name in _PRESERVE_IF_EXISTS and dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    emit("[update] Installed release files.")


def _download_zipball_and_merge(zip_url: str, emit: Callable[[str], None]) -> bool:
    req = Request(zip_url, headers={**_github_api_headers(), "User-Agent": _user_agent()})
    try:
        with urlopen_tls(req, timeout=180, emit=emit) as resp:
            body = resp.read()
    except HTTPError as e:
        emit(f"[update] Download failed HTTP {e.code}: {e.reason}")
        return False
    except URLError as e:
        emit(f"[update] Download failed: {e.reason}")
        emit_tls_hint(emit, e)
        return False
    except OSError as e:
        emit(f"[update] Download failed: {e}")
        return False

    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(body)
        zpath = tmp.name
    extract_dir: str | None = None
    try:
        with zipfile.ZipFile(zpath) as zf:
            members = zf.namelist()
            if not members:
                emit("[update] Empty archive.")
                return False
            extract_dir = tempfile.mkdtemp(prefix="pokemacro-update-")
            zf.extractall(extract_dir)
            inner_root = Path(extract_dir)
            inner = next(inner_root.iterdir(), None)
            if inner is None or not inner.is_dir():
                emit("[update] Unexpected zip layout.")
                return False
            _merge_release_tree(inner, emit)
    except zipfile.BadZipFile:
        emit("[update] Downloaded file is not a valid zip.")
        return False
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            os.unlink(zpath)
        except OSError:
            pass
    return True


def _http_branch_zipball_update(
    repo: str,
    emit: Callable[[str], None],
    *,
    skip_cache: bool = False,
    force: bool = False,
) -> tuple[bool, bool]:
    """Returns (success, installed_new_merge). Second is False when already cached or skipped."""
    try:
        from . import __version__ as local_ver
    except Exception:
        local_ver = "0.0.0"
    local_t = _version_tuple(str(local_ver))

    info = _http_json(f"https://api.github.com/repos/{repo}", emit)
    if not info or not isinstance(info, dict):
        return False, False
    branch = str(info.get("default_branch") or "master")
    commit_data = _http_json(
        f"https://api.github.com/repos/{repo}/commits/{branch}",
        emit,
    )
    if not commit_data or not isinstance(commit_data, dict):
        return False, False
    sha = str(commit_data.get("sha") or "").strip()
    if not sha:
        emit("[update] Could not read latest commit on default branch.")
        return False, False
    if not skip_cache and _UPDATE_COMMIT_CACHE.is_file():
        cached = _UPDATE_COMMIT_CACHE.read_text(encoding="utf-8", errors="replace").strip()
        if cached == sha:
            emit(f"[update] Already up to date ({branch} @ {sha[:7]}).")
            return True, False
    if not force:
        remote_ver = _remote_root_version(repo, sha, emit)
        if remote_ver is None:
            emit("[update] Skipping default-branch sync (could not compare versions).")
            return True, False
        if not _version_gt(_version_tuple(remote_ver), local_t):
            emit(
                f"[update] Default branch ({branch} @ {sha[:7]}, {remote_ver}) "
                f"is not newer than local {local_ver}; skipping."
            )
            return True, False
    zip_url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    emit(f"[update] Downloading {branch} @ {sha[:7]} …")
    ok = _download_zipball_and_merge(zip_url, emit)
    if ok:
        try:
            _UPDATE_COMMIT_CACHE.write_text(sha + "\n", encoding="utf-8")
        except OSError as e:
            emit(f"[update] Could not save update marker: {e}")
    return (True, True) if ok else (False, False)


def _http_release_update(
    repo: str, emit: Callable[[str], None], *, force: bool = False
) -> tuple[bool, bool]:
    try:
        from . import __version__ as local_ver
    except Exception:
        local_ver = "0.0.0"

    api = f"https://api.github.com/repos/{repo}/releases/latest"
    req = Request(api, headers={**_github_api_headers(), "User-Agent": _user_agent()})
    release_data: dict[str, Any] | None = None
    try:
        with urlopen_tls(req, timeout=60, emit=emit) as resp:
            release_data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        if e.code == 404:
            emit("[update] No GitHub releases; syncing from default branch instead.")
            return _http_branch_zipball_update(
                repo, emit, skip_cache=force, force=force
            )
        emit(f"[update] GitHub API HTTP {e.code}: {e.reason}")
        return False, False
    except URLError as e:
        emit(f"[update] GitHub API error: {e.reason}")
        emit_tls_hint(emit, e)
        return False, False
    except json.JSONDecodeError as e:
        emit(f"[update] GitHub API: invalid JSON ({e})")
        return False, False
    except OSError as e:
        emit(f"[update] GitHub API: {e}")
        return False, False

    if not isinstance(release_data, dict):
        return _http_branch_zipball_update(
            repo, emit, skip_cache=force, force=force
        )

    tag = str(release_data.get("tag_name") or "").strip()
    zip_url = release_data.get("zipball_url")
    if not tag or not zip_url or not isinstance(zip_url, str):
        emit("[update] Latest release incomplete; syncing from default branch instead.")
        return _http_branch_zipball_update(
            repo, emit, skip_cache=force, force=force
        )

    remote_t = _version_tuple(tag)
    local_t = _version_tuple(str(local_ver))
    if not force and not _version_gt(remote_t, local_t):
        emit(f"[update] Not updating: {tag} is not newer than installed {local_ver}.")
        return True, False

    emit(
        f"[update] {'Force downloading' if force else 'Downloading'} {tag} …"
    )
    merged = _download_zipball_and_merge(zip_url, emit)
    return (True, True) if merged else (False, False)


def start_background_update(
    *,
    log_queue: queue.Queue[str] | None = None,
    log_fn: Callable[[str], None] | None = None,
    restart_callback: Callable[[], None] | None = None,
) -> None:
    def emit(s: str) -> None:
        if log_queue is not None:
            log_queue.put(s)
        elif log_fn is not None:
            log_fn(s)
        else:
            print(s, flush=True)

    def work() -> None:
        if _DEV_SKIP_AUTO_UPDATE.exists():
            emit("[update] Skipped: dev file in project root.")
            return
        repo = _resolve_github_repo()
        if not repo:
            emit(
                "[update] No repo for updates: set UPDATE_GITHUB_REPO in git_update.py, "
                "or add owner/repo as the first line of update_repo.txt "
                "(GitHub origin URL from .git/config is used when present)."
            )
            return
        ok, installed = _http_release_update(repo, emit, force=False)
        if not ok:
            return
        if installed:
            if restart_callback:
                emit("[update] Restarting to load the update …")
                restart_callback()
            else:
                emit("[update] Restart the app to load new code.")

    threading.Thread(target=work, daemon=True, name="auto-update").start()
