"""Lumi Tarot backend: safe initial deployment / health check only."""
import os
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify(service="Lumi Tarot API", status="running", version="0.1")

@app.get("/health")
def health():
    return jsonify(ok=True)

# AI interpretation, Telegram authentication, quotas and payments will be added
# only after server-side identity verification and storage are configured.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
