"""Lumi Tarot API — private GigaChat connectivity test (no public AI endpoint)."""
import hmac
import json
import os
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request

app = Flask(__name__)
_TOKEN = None
_TOKEN_EXPIRES_AT = 0


def _json_request(url, payload, headers, timeout=15):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not expose upstream response: it can contain sensitive details.
        raise RuntimeError(f"GigaChat upstream HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("GigaChat network connection failed") from exc


def _get_access_token():
    global _TOKEN, _TOKEN_EXPIRES_AT
    if _TOKEN and time.time() < _TOKEN_EXPIRES_AT - 90:
        return _TOKEN
    auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
    scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
    if not auth_key:
        raise RuntimeError("GIGACHAT_AUTH_KEY is not configured")
    # Sber OAuth endpoint expects URL-encoded form data, not JSON.
    from urllib.parse import urlencode
    req = Request(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=urlencode({"scope": scope}).encode("ascii"),
        headers={
            "Authorization": "Basic " + auth_key.removeprefix("Basic "),
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
    raise RuntimeError(f"GigaChat OAuth HTTP {exc.code}") from exc
except (URLError, TimeoutError) as exc:
    raise RuntimeError(
        f"GigaChat OAuth connection failed: {type(exc).__name__}"
    ) from exc
    _TOKEN = result.get("access_token")
    if not _TOKEN:
        raise RuntimeError("GigaChat OAuth did not return an access token")
    # 'expires_at' is a Unix timestamp in milliseconds.
    expires_at = result.get("expires_at")
    _TOKEN_EXPIRES_AT = (float(expires_at) / 1000) if expires_at else time.time() + 1500
    return _TOKEN


@app.get("/")
def home():
    return jsonify(service="Lumi Tarot API", status="running", version="0.2")


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/gigachat/status")
def gigachat_status():
    # Only indicates configuration; does not disclose secrets or call the API.
    return jsonify(configured=bool(os.environ.get("GIGACHAT_AUTH_KEY")),
                   scope_configured=bool(os.environ.get("GIGACHAT_SCOPE")),
                   public_ai_enabled=False)


@app.post("/internal/test-gigachat")
def private_test():
    # Never accept the admin secret via URL parameters or expose it to frontend JS.
    expected = os.environ.get("LUMI_ADMIN_TEST_TOKEN", "")
    supplied = request.headers.get("X-Lumi-Admin-Token", "")
    if not expected:
        return jsonify(error="Private testing is not enabled"), 503
    if not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify(error="Unauthorized"), 401
    try:
        token = _get_access_token()
        result = _json_request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            {"model": os.environ.get("GIGACHAT_MODEL", "GigaChat"),
             "messages": [{"role": "system", "content": "Отвечай кратко по-русски."},
                          {"role": "user", "content": "Напиши одно короткое приветствие для Lumi Tarot."}],
             "max_tokens": 80, "temperature": 0.4},
            {"Authorization": "Bearer " + token, "Content-Type": "application/json",
             "Accept": "application/json"}, timeout=20,
        )
        answer = result["choices"][0]["message"]["content"]
        return jsonify(ok=True, answer=answer)
    except (RuntimeError, KeyError, IndexError, TypeError, ValueError) as exc:
       app.logger.warning(
    "Private GigaChat test failed: %s",
    str(exc)
)
        return jsonify(ok=False, error=str(exc)), 502


# No public AI endpoint: Telegram initData verification, server-side quotas,
# persistent storage, abuse protection, and commercial access are pending.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
