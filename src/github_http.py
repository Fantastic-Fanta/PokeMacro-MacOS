"""HTTPS for GitHub API/download with a reliable CA bundle and optional TLS overrides.

- ``POKEMACRO_INSECURE_SSL=1`` disables verification (insecure; debugging only).
- Prefers ``SSL_CERT_FILE`` or ``REQUESTS_CA_BUNDLE`` when set to a PEM file (corporate CA).
- Otherwise uses `truststore` (OS certificate store; fixes many macOS / python.org setups).
- Then ``certifi``'s CA bundle.
- Last: ``ssl.create_default_context()`` (system OpenSSL paths).
"""
from __future__ import annotations

import os
import ssl
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen


def _insecure_tls_enabled() -> bool:
    return os.environ.get("POKEMACRO_INSECURE_SSL", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ssl_context(*, emit: Callable[[str], None] | None = None) -> ssl.SSLContext:
    if _insecure_tls_enabled():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if emit:
            emit(
                "[ssl] POKEMACRO_INSECURE_SSL is set: TLS verification is disabled "
                "(only for debugging / broken corporate proxies)."
            )
        return ctx

    ca_env = (
        os.environ.get("SSL_CERT_FILE", "").strip()
        or os.environ.get("REQUESTS_CA_BUNDLE", "").strip()
    )
    if ca_env and os.path.isfile(ca_env):
        try:
            return ssl.create_default_context(cafile=ca_env)
        except OSError as e:
            if emit:
                emit(
                    f"[ssl] Could not load CA file {ca_env!r} ({e}); "
                    "falling back to truststore/certifi."
                )

    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass

    try:
        import certifi

        cpath = certifi.where()
        if cpath and os.path.isfile(cpath):
            try:
                return ssl.create_default_context(cafile=cpath)
            except OSError as e:
                if emit:
                    emit(
                        f"[ssl] Could not load certifi bundle {cpath!r} ({e}); "
                        "using system defaults."
                    )
    except Exception:
        pass

    return ssl.create_default_context()


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
            "[ssl] Try: pip install -U truststore certifi — set SSL_CERT_FILE to a PEM that "
            "includes your proxy/company CA — on macOS (python.org builds), open "
            "Applications/Python 3.x/Install Certificates.command — last resort "
            "POKEMACRO_INSECURE_SSL=1 (insecure)."
        )
