"""Lumi Tarot API — GigaChat with Telegram Mini App test authentication."""
import hashlib
import hmac
import json
import os
import socket
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
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
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"GigaChat API HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("GigaChat API connection failed: " + _network_error_category(exc)) from None

def _get_access_token():
    global _TOKEN, _TOKEN_EXPIRES_AT
    if _TOKEN and time.time() < _TOKEN_EXPIRES_AT - 90:
        return _TOKEN
    auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
    scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
    if not auth_key:
        raise RuntimeError("GIGACHAT_AUTH_KEY is not configured")
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
        with urlopen(req, timeout=15, context=_ssl_context()) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"GigaChat OAuth HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("GigaChat OAuth connection failed: " + _network_error_category(exc)) from None
    _TOKEN = result.get("access_token")
    if not _TOKEN:
        raise RuntimeError("GigaChat OAuth did not return an access token")
    expires_at = result.get("expires_at")
    _TOKEN_EXPIRES_AT = float(expires_at) / 1000 if expires_at else time.time() + 1500
    return _TOKEN

@app.get("/")
def home():
    return jsonify(service="Lumi Tarot API", status="running", version="0.6-test")

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/gigachat/status")
def gigachat_status():
    return jsonify(configured=bool(os.environ.get("GIGACHAT_AUTH_KEY")), scope_configured=bool(os.environ.get("GIGACHAT_SCOPE")), public_ai_enabled=False)

@app.post("/internal/test-gigachat")
def private_test():
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
            {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"},
            timeout=20,
        )
        answer = result["choices"][0]["message"]["content"]
        return jsonify(ok=True, answer=answer)
    except (RuntimeError, KeyError, IndexError, TypeError, ValueError) as exc:
        message = str(exc)
        app.logger.warning("Private GigaChat test failed: %s", message)
        return jsonify(ok=False, error=message), 502

import hashlib
# import threading
# from datetime import datetime, timezone
# from flask import make_response

# ADD BELOW THE EXISTING PRIVATE TEST ENDPOINT, BEFORE if __name__ == "__main__":

# IMPORTANT: This temporary in-memory quota is for a single Gunicorn worker only.
# It resets on service restart. Do not treat it as production billing protection.
import hashlib
import threading
from datetime import datetime, timezone

_QUOTA_LOCK = threading.Lock()
_QUOTA = {}
_ALLOWED_ORIGIN = "https://ludoff87.github.io"
_CARD_NAMES = [
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император",
    "Иерофант", "Влюблённые", "Колесница", "Сила", "Отшельник",
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть",
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце",
    "Суд", "Мир",
] + [f"{rank} {suit}" for suit in ("Жезлов", "Кубков", "Мечей", "Пентаклей")
     for rank in ("Туз", "Двойка", "Тройка", "Четвёрка", "Пятёрка",
                  "Шестёрка", "Семёрка", "Восьмёрка", "Девятка",
                  "Десятка", "Паж", "Рыцарь", "Королева", "Король")]
_POSITIONS = {
    "day": ["Послание дня"],
    "three": ["Прошлое", "Настоящее", "Возможное развитие"],
    "love": ["Ты", "Динамика отношений", "Совет"],
}


def _verify_telegram_init_data(init_data):
    """Verify Telegram Mini App initData HMAC and freshness server-side."""
    from urllib.parse import parse_qsl
    if not isinstance(init_data, str) or len(init_data) > 8192:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        if len(values) != len(pairs):
            return None
        their_hash = values.pop("hash", "")
        if len(their_hash) != 64:
            return None
        auth_date = int(values.get("auth_date", "0"))
        if not (0 <= time.time() - auth_date <= 86400):
            return None
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return None
        data_check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, their_hash):
            return None
        user = json.loads(values.get("user", "{}"))
        user_id = user.get("id")
        return user_id if type(user_id) is int and user_id > 0 else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


@app.after_request
def _reading_cors(response):
    if request.path == "/api/reading" and request.headers.get("Origin") == _ALLOWED_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = _ALLOWED_ORIGIN
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/reading", methods=["POST", "OPTIONS"])
def ai_reading():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.headers.get("Origin") != _ALLOWED_ORIGIN:
        return jsonify(ok=False, error="Недопустимый источник запроса"), 403
    if request.content_length is None or request.content_length > 12000:
        return jsonify(ok=False, error="Слишком большой запрос"), 413
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="Неверный формат запроса"), 400
    user_id = _verify_telegram_init_data(data.get("init_data"))
    if user_id is None:
        return jsonify(ok=False, error="Открой Lumi Tarot через Telegram заново"), 401
    mode = data.get("mode")
    cards = data.get("cards")
    question = data.get("question", "")
    if mode not in _POSITIONS or not isinstance(question, str) or len(question) > 250:
        return jsonify(ok=False, error="Некорректный расклад"), 400
    if not isinstance(cards, list) or len(cards) != len(_POSITIONS[mode]):
        return jsonify(ok=False, error="Некорректное число карт"), 400
    validated = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            return jsonify(ok=False, error="Некорректная карта"), 400
        card_id = card.get("id")
        reversed_card = card.get("reversed")
        if type(card_id) is not int or not 0 <= card_id < 78 or type(reversed_card) is not bool:
            return jsonify(ok=False, error="Некорректная карта"), 400
        validated.append(f"{_POSITIONS[mode][index]}: {_CARD_NAMES[card_id]} ({'перевёрнутая' if reversed_card else 'прямая'})")
    if len({card["id"] for card in cards}) != len(cards):
        return jsonify(ok=False, error="Карты не должны повторяться"), 400

    # Short-term test limits: 2 day readings per UTC day and 5 other readings total.
    # Hold a reservation during the API call to avoid concurrent quota bypass.
    day = datetime.now(timezone.utc).date().isoformat()
    with _QUOTA_LOCK:
        state = _QUOTA.setdefault(user_id, {"day": day, "day_used": 0, "welcome_used": 0, "pending": False})
        if state["day"] != day:
            state["day"], state["day_used"] = day, 0
        if state["pending"]:
            return jsonify(ok=False, error="Дождись завершения предыдущего расклада"), 429
        if mode == "day" and state["day_used"] >= 2:
            return jsonify(ok=False, error="Лимит карт дня исчерпан"), 429
        if mode != "day" and state["welcome_used"] >= 20:
            return jsonify(ok=False, error="Лимит приветственных раскладов исчерпан"), 429
        state["pending"] = True

    success = False
    try:
        token = _get_access_token()
        result = _json_request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            {
                "model": os.environ.get("GIGACHAT_MODEL", "GigaChat"),
                "messages": [
                   {"role": "system", "content": (
    
"Ты — опытный, внимательный таролог приложения Lumi Tarot. "
"Создавай персонализированные символические толкования карт Таро на русском языке. "
"Обращайся к пользователю на «ты», дружелюбно и естественно. "
"Главная задача — ответить непосредственно на заданный вопрос, "
"а не просто пересказать универсальные значения карт. "                       
"Не повторяй значения карт в разных разделах. "
"В разделе «Ответ на твой вопрос» назови главную тему или возможное препятствие, "
"которое символизирует сочетание карт, без подробного разбора каждой карты. "
"В разделе «Что говорят карты» объясни каждую карту только один раз, "
"с учётом вопроса, позиции и перевёрнутого положения. "
"В разделе «Общий вывод» сформулируй одну новую объединяющую мысль "
"в 1–2 предложениях, не пересказывая значения карт. "
"В разделе «Совет карт» предложи конкретный практический шаг, "
"подходящий к вопросу пользователя. "
"Не утверждай, что знаешь реальные события прошлого, чувства других людей "
"или личные обстоятельства пользователя. "
"Все предположения формулируй как возможные темы для размышления. "
"Если вопрос задан, начни с заголовка «Ответ на твой вопрос» "
"и дай конкретный, но осторожный ответ в 2–4 предложениях. "
"Затем добавь раздел «Что говорят карты» и объясни каждую карту "
"с учётом её названия, позиции, прямого или перевёрнутого положения "
"и связи с вопросом пользователя. "
"После этого добавь раздел «Общий вывод» — объясни, "
"как карты сочетаются между собой, не повторяя предыдущие объяснения. "
"Заверши разделом «Совет карт» с 1–2 полезными и реалистичными рекомендациями. "
"Если вопрос отсутствует, предложи нейтральное толкование расклада. "
"Не придумывай факты о жизни пользователя, наличие партнёра, "
"прошлые события или чувства других людей. "
"Не обещай точных событий и не утверждай, что знаешь будущее. "
"Используй ясный, тёплый язык без шаблонных фраз и длинных вступлений. "
"Избегай повторений и не пересказывай одну мысль в разных разделах. "
"Ответ должен быть примерно 180–250 слов, с короткими заголовками, без таблиц. "

)},

                    {"role": "user", "content": (
                        f"Тип расклада: {mode}. Вопрос пользователя (учти дословно): «{question.strip() or 'не задан'}».\n" + "\n".join(validated)
                    )},
                ],
                "max_tokens": 650,
                "temperature": 0.7,
            },
            {"Authorization": "Bearer " + token,
             "Content-Type": "application/json", "Accept": "application/json"},
            timeout=35,
        )
        answer = result["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty AI response")
        success = True
        return jsonify(ok=True, answer=answer.strip())
    except (RuntimeError, ValueError, KeyError, IndexError, TypeError):
        app.logger.warning("Public reading request failed")
        return jsonify(ok=False, error="GigaChat временно недоступен. Попробуй позже"), 502
    finally:
        with _QUOTA_LOCK:
            state = _QUOTA[user_id]
            state["pending"] = False
            if success:
                if mode == "day":
                    state["day_used"] += 1
                else:
                    state["welcome_used"] += 1


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
