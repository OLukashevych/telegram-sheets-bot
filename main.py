import os
import json
import base64
from datetime import datetime

from fastapi import FastAPI, Request
import gspread
from google.oauth2.service_account import Credentials
import requests

app = FastAPI()

BOT_TOKEN = os.environ["BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

user_states = {}


def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        payload["reply_markup"] = {
            "keyboard": keyboard,
            "resize_keyboard": True
        }

    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)


def get_gsheet():
    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_dict = json.loads(creds_json)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    return client.open_by_key(os.environ["SHEET_KEY"])


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

    state = user_states.get(chat_id)

    # 🔹 старт
    if text == "/start":
        send_message(
            chat_id,
            "Обери дію:",
            keyboard=[["Купую", "Продаю", "Витрати"]]
        )
        return {"ok": True}

    # 🔹 вибір режиму
    if text in ["Купую", "Продаю", "Витрати"]:
        user_states[chat_id] = {"mode": text, "step": 1, "data": {}}
        send_message(chat_id, "Введи номенклатуру:")
        return {"ok": True}

    if not state:
        send_message(chat_id, "Натисни /start")
        return {"ok": True}

    mode = state["mode"]
    step = state["step"]

    # 🔹 сценарій Купую
    if mode == "Купую":
        if step == 1:
            state["data"]["name"] = text
            state["step"] = 2
            send_message(chat_id, "Введи обсяг (т):")
            return {"ok": True}

        elif step == 2:
            state["data"]["qty"] = text
            state["step"] = 3
            send_message(chat_id, "Введи ціну за тонну:")
            return {"ok": True}

        elif step == 3:
            state["data"]["price"] = text

            now = datetime.now()

            sheet = get_gsheet()
            ws = sheet.worksheet("купую")

            qty = float(state["data"]["qty"])
            price = float(state["data"]["price"])

            ws.append_row([
                now.strftime("%Y-%m-%d"),
                now.strftime("%m"),
                now.strftime("%Y"),
                state["data"]["name"],
                qty,
                price,
                qty * price
            ])

            send_message(chat_id, "✅ Записано")

            user_states.pop(chat_id)
            return {"ok": True}

    # 🔹 сценарій Витрати (простий)
    if mode == "Витрати":
        sheet = get_gsheet()
        ws = sheet.worksheet("витрати")

        now = datetime.now()

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            text,
            ""
        ])

        send_message(chat_id, "✅ Витрата записана")
        user_states.pop(chat_id)
        return {"ok": True}

    return {"ok": True}
