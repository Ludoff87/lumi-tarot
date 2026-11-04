
"""Lumi Tarot API — secure GigaChat connection."""

import hmac
import json
import os
import socket
import ssl
import time
import uuid

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request


app = Flask(__name__)

_TOKEN = None
_TOKEN_EXPIRES_AT = 0

CERT_FILE = Path(__file__).resolve().parent / "lumi_gigachat_ca_bundle.pem"


def _ssl_context():
    """Keep standard trusted CAs and add the project CA bundle."""
    context = ssl.create_default_context()

    if not CERT_FILE.is_file():
        raise RuntimeError("GigaChat CA bundle file is missing")

    try:
        context.load_verify_locations(cafile=str(CERT_FILE))
    except (ssl.SSLError, OSError):
        raise RuntimeError("GigaChat CA bundle could not be loaded") from None

    return context


def _network_error_category(exc):
    reason = exc.reason if isinstance(exc, URLError) else exc

    if isinstance(reason, ssl.SSLCertVerificationError):
        return "SSL_CERTIFICATE_VERIFY_FAILED"

    if isinstance(reason, ssl.SSLError):
        return "SSL_HANDSHAKE_ERROR"

    if isinstance(reason, socket.gaierror):
        return "DNS_RESOLUTION_FAILED"

    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "CONNECTION_TIMEOUT"

    if isinstance(reason, ConnectionRefusedError):
        return "CONNECTION_REFUSED"

    if isinstance(reason, ConnectionResetError):
        return "CONNECTION_RESET"

    if isinstance(reason, OSError):
        if reason.errno == 101:
            return "NETWORK_UNREACHABLE"
        if reason.errno == 113:
            return "HOST_UNREACHABLE"

    return "NETWORK_ERROR"


def _json_request(url, payload, headers, timeout=15):
    body = json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")

    req = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(
            req,
            timeout=timeout,
            context=_ssl_context(),
        ) as response:
            return json.load(response)

    except HTTPError as exc:
        raise RuntimeError(
            f"GigaChat API HTTP {exc.code}"
        ) from None

    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            "GigaChat API connection failed: "
            + _network_error_category(exc)
        ) from None


def _get_access_token():
    global _TOKEN, _TOKEN_EXPIRES_AT

    if _TOKEN and time.time() < _TOKEN_EXPIRES_AT - 90:
        return _TOKEN

    auth_key = os.environ.get(
        "GIGACHAT_AUTH_KEY", ""
    ).strip()

    scope = os.environ.get(
        "GIGACHAT_SCOPE", "GIGACHAT_API_PERS"
    ).strip()

    if not auth_key:
        raise RuntimeError(
            "GIGACHAT_AUTH_KEY is not configured"
        )

    req = Request(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=urlencode(
            {"scope": scope}
        ).encode("ascii"),
        headers={
            "Authorization": (
                "Basic " + auth_key.removeprefix("Basic ")
            ),
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(
            req,
            timeout=15,
            context=_ssl_context(),
        ) as response:
            result = json.load(response)

    except HTTPError as exc:
        raise RuntimeError(
            f"GigaChat OAuth HTTP {exc.code}"
        ) from None

    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            "GigaChat OAuth connection failed: "
            + _network_error_category(exc)
        ) from None

    _TOKEN = result.get("access_token")

    if not _TOKEN:
        raise RuntimeError(
            "GigaChat OAuth did not return an access token"
        )

    expires_at = result.get("expires_at")

    _TOKEN_EXPIRES_AT = (
        float(expires_at) / 1000
        if expires_at
        else time.time() + 1500
    )

    return _TOKEN


@app.get("/")
def home():
    return jsonify(
        service="Lumi Tarot API",
        status="running",
        version="0.5",
    )


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/gigachat/status")
def gigachat_status():
    return jsonify(
        configured=bool(
            os.environ.get("GIGACHAT_AUTH_KEY")
        ),
        scope_configured=bool(
            os.environ.get("GIGACHAT_SCOPE")
        ),
        public_ai_enabled=False,
    )


@app.post("/internal/test-gigachat")
def private_test():
    expected = os.environ.get(
        "LUMI_ADMIN_TEST_TOKEN", ""
    )

    supplied = request.headers.get(
        "X-Lumi-Admin-Token", ""
    )

    if not expected:
        return jsonify(
            error="Private testing is not enabled"
        ), 503

    if not supplied or not hmac.compare_digest(
        expected, supplied
    ):
        return jsonify(
            error="Unauthorized"
        ), 401

    try:
        token = _get_access_token()

        result = _json_request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            {
                "model": os.environ.get(
                    "GIGACHAT_MODEL", "GigaChat"
                ),
                "messages": [
                    {
                        "role": "system",
                        "content": "Отвечай кратко по-русски.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Напиши одно короткое приветствие "
                            "для Lumi Tarot."
                        ),
                    },
                ],
                "max_tokens": 80,
                "temperature": 0.4,
            },
            {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=20,
        )

        answer = result["choices"][0]["message"]["content"]

        return jsonify(
            ok=True,
            answer=answer,
        )

    except (
        RuntimeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        message = str(exc)

        app.logger.warning(
            "Private GigaChat test failed: %s",
            message,
        )

        return jsonify(
            ok=False,
            error=message,
        ), 502


# Public AI access remains disabled until Telegram
# authentication, quotas and abuse protection are ready.

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )
