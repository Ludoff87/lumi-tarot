# Lumi Tarot backend (stage 1)

This is a health-check-only starter. It does not call GigaChat, charge users, or enforce quotas.

Render settings:
- Language: Python 3
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Instance: Free (if available)

Do not commit API keys, bot tokens, or credentials to GitHub. Later stages require Telegram initData server-side validation, persistent storage, request limits, and GigaChat commercial-use review.
