"""HTTPS for GitHub API/download with a reliable CA bundle and optional TLS overrides.

- Prefers ``SSL_CERT_FILE`` or ``REQUESTS_CA_BUNDLE`` when set to a PEM file (corporate CA).
- Otherwise uses ``certifi``'s CA bundle when installed (fixes many macOS/Python ``urllib`` setups).
- Last resort: ``POKEMACRO_INSECURE_SSL=1`` disables verification (insecure; debugging only).
"""
from __future__ import annotations

import os
import ssl
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen


def ssl_context(*, emit: Callable[[str], None] | None = None) -> ssl.SSLContext:
    ca_env = (
        os.environ.get("SSL_CERT_FILE", "").strip()
        or os.environ.get("REQUESTS_CA_BUNDLE", "").strip()
    )
    cafile: str | None = None
    if ca_env and os.path.isfile(ca_env):
        cafile = ca_env
    else:
        try:
            import certifi

            cafile = certifi.where()
        except Exception:
            cafile = None

    if cafile:
        try:
            ctx = ssl.create_default_context(cafile=cafile)
        except OSError as e:
            if emit:
                emit(f"[ssl] Could not load CA file {cafile!r} ({e}); using system defaults.")
            ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()

    if os.environ.get("POKEMACRO_INSECURE_SSL", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        if emit:
            emit(
                "[ssl] POKEMACRO_INSECURE_SSL is set: TLS verification is disabled "
                "(only for debugging / broken corporate proxies)."
            )
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def urlopen_tls(
    req: Request,
    *,
    timeout: float | None,
    emit: Callable[[str], None] | None = None,
):
    return urlopen(req, timeout=timeout, context=ssl_context(emit=emit))


def emit_tls_hint(emit: Callable[[str], None], err: Any) -> None:
    """Call after URLError for certificate-related failures."""
    reason = getattr(err, "reason", err)
    text = str(reason).lower()
    if any(x in text for x in ("certificate", "ssl", "tls", "handshake")):
        emit(
            "[ssl] Try: pip install -U certifi — or set SSL_CERT_FILE to a PEM bundle "
            "(corporate proxy) — last resort POKEMACRO_INSECURE_SSL=1 (insecure)."
        )
