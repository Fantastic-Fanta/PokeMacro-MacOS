"""HTTPS for GitHub API/download with a reliable CA bundle and optional TLS overrides.

- ``POKEMACRO_INSECURE_SSL=1`` disables verification (insecure; debugging only).
- Prefers ``SSL_CERT_FILE`` or ``REQUESTS_CA_BUNDLE`` when set to a PEM file (corporate CA).
- Otherwise uses `truststore` (OS certificate store; fixes many macOS / python.org setups).
- Then ``certifi``'s CA bundle.
- Then macOS system bundle at ``/etc/ssl/cert.pem`` (Ventura+).
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

    # macOS system CA bundle (works on Ventura+; absent on Linux — ignored there).
    _MACOS_CERT = "/etc/ssl/cert.pem"
    if os.path.isfile(_MACOS_CERT):
        try:
            return ssl.create_default_context(cafile=_MACOS_CERT)
        except OSError:
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
    """Call after a TLS/SSL failure to print actionable guidance."""
    reason = getattr(err, "reason", err)
    text = str(reason).lower() + str(err).lower()
    if not any(x in text for x in ("certificate", "ssl", "tls", "handshake")):
        return

    import platform
    import sys

    lines = [
        "[ssl] SSL certificate verification failed. Quick fixes:",
        "  1. pip install -U truststore certifi",
    ]

    if platform.system() == "Darwin":
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        cert_cmd = f"/Applications/Python {ver}/Install Certificates.command"
        if os.path.isfile(cert_cmd):
            lines.append(f"  2. Run: open \"{cert_cmd}\"  (installs macOS CA certs for python.org builds)")
        else:
            lines.append(
                f"  2. Open Finder → Applications → Python {ver} → double-click 'Install Certificates.command'"
            )

    lines += [
        "  3. Set SSL_CERT_FILE=/path/to/your-ca-bundle.pem (corporate proxy CA)",
        "  4. Last resort (insecure): set POKEMACRO_INSECURE_SSL=1",
    ]
    emit("\n".join(lines))
