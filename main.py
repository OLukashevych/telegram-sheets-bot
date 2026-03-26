import os
import json
import base64
from datetime import datetime

from fastapi import FastAPI, Request
import gspread
from google.oauth2.service_account import Credentials
import requests

app = FastAPI()

# ❗ беремо токен тільки тут і тільки один раз
def get_telegram_api():
    token = os.environ.get("BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}"

# 🔹 кнопки
def send_inline(chat_id, text, keyboard):
    url = f"{get_telegram_api()}/sendMessage"

    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": keyboard
        }
    })

def send_message(chat_id, text):
    url = f"{get_telegram_api()}/sendMessage"

    requests.post(url, json={
        "chat_id": chat_id,
        "text": text
    })

# 🔹 GOOGLE SHEETS
def get_gsheet():
    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_dict = json.loads(creds_json)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    return client.open_by_key(os.environ["SHEET_KEY"])

# 🔹 ROOT
@app.get("/")
def root():
    return {"status": "ok"}

# 🔹 STATE
user_states = {}
----------------------------
@app.get("/debug")
def debug():
    return {
        "bot_token": os.environ.get("BOT_TOKEN")
    }
-------------------------------
# 🔹 WEBHOOK
@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()
    print("INCOMING:", data)

    # CALLBACK
    if "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        action = callback["data"]

        print("CALLBACK:", action)

        if action == "BUY":
            send_message(chat_id, "BUY OK")
        elif action == "SELL":
            send_message(chat_id, "SELL OK")
        elif action == "EXPENSE":
            send_message(chat_id, "EXPENSE OK")

        return {"ok": True}

    # MESSAGE
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    print("TEXT:", text)

    if text == "/start":
        send_inline(chat_id, "Обери дію:", [
            [{"text": "Купую", "callback_data": "BUY"}],
            [{"text": "Продаю", "callback_data": "SELL"}],
            [{"text": "Витрати", "callback_data": "EXPENSE"}],
        ])

    return {"ok": True}
