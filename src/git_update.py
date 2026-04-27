from __future__ import annotations

import os
import queue
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _should_skip() -> bool:
    v = (os.environ.get("POKEMACRO_SKIP_GIT_UPDATE") or "").strip().lower()
    return v in ("1", "true", "yes")


def _git_pull(emit: Callable[[str], None]) -> None:
    if _should_skip():
        return
    root = PROJECT_ROOT
    if not (root / ".git").is_dir():
        return
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
    except FileNotFoundError:
        emit("[update] `git` not on PATH; skipped.")
    except subprocess.TimeoutExpired:
        emit("[update] git pull timed out.")
    except OSError as e:
        emit(f"[update] {e}")


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
        _git_pull(emit)

    threading.Thread(target=work, daemon=True, name="git-auto-update").start()
