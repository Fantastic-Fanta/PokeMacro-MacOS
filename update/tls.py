from __future__ import annotations

import io
import os
import ssl
import subprocess
import sys
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


def _curl_available() -> bool:
    return sys.platform == "darwin" and bool(
        subprocess.run(["which", "curl"], capture_output=True).returncode == 0
    )


class _CurlResponse:
    """Minimal file-like wrapper around curl output so callers can use .read()."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _urlopen_curl(req: Request, *, timeout: float | None, emit: Callable[[str], None] | None = None):
    """Download via system curl (macOS Keychain SSL — avoids python.org cert issues)."""
    cmd = ["curl", "-fsSL", "--max-time", str(int(timeout or 180))]
    for key, val in req.headers.items():
        cmd += ["-H", f"{key}: {val}"]
    cmd.append(req.full_url)
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise OSError(f"curl failed (exit {result.returncode}): {stderr}")
    return _CurlResponse(result.stdout)


def _is_ssl_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    # URLError wraps the underlying SSLError as .reason
    reason = getattr(exc, "reason", None)
    return isinstance(reason, ssl.SSLError)


def urlopen_tls(
    req: Request,
    *,
    timeout: float | None,
    emit: Callable[[str], None] | None = None,
):
    from urllib.error import URLError

    try:
        return urlopen(req, timeout=timeout, context=ssl_context(emit=emit))
    except (ssl.SSLError, URLError) as exc:
        if _is_ssl_error(exc) and _curl_available():
            if emit:
                emit("[ssl] urllib SSL failed; retrying with system curl (macOS Keychain).")
            return _urlopen_curl(req, timeout=timeout, emit=emit)
        raise


def emit_tls_hint(emit: Callable[[str], None], err: Any) -> None:
    reason = getattr(err, "reason", err)
    text = str(reason).lower()
    if any(x in text for x in ("certificate", "ssl", "tls", "handshake")):
        emit(
            "[ssl] Try: pip install -U truststore certifi — set SSL_CERT_FILE to a PEM that "
            "includes your proxy/company CA — on macOS (python.org builds), open "
            "Applications/Python 3.x/Install Certificates.command — last resort "
            "POKEMACRO_INSECURE_SSL=1 (insecure)."
        )
