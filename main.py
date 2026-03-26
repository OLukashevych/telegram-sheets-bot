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

# 🔹 ДОВІДНИКИ

BUY_ITEMS = [
    ["Пісок буд.", "Пісок мит"],
    ["Щ 3/8", "Щ 5/20"],
    ["Щ 20/40", "Щ 40/70"],
    ["Відсів", "Т-крихта"]
]

SELL_ITEMS = [
    ["Пісок буд.", "Пісок мит"],
    ["Щ 3/8", "Щ 5/20"],
    ["Щ 20/40", "Щ 40/70"],
    ["Навантажувач", "Доставка"]
]

EXPENSE_ITEMS = [
    ["Паливо", "Зарплата"],
    ["Ремонт", "Оренда"],
    ["Інше"]
]

user_states = {}

# 🔹 TELEGRAM SEND

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


# 🔹 WEBHOOK

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if not chat_id:
            return {"ok": True}

        state = user_states.get(chat_id)

        # 🔹 START
        if text == "/start":
            send_message(
                chat_id,
                "Обери дію:",
                keyboard=[["Купую", "Продаю", "Витрати"]]
            )
            return {"ok": True}

        # =====================
        # 🔹 КУПУЮ
        # =====================

        if text == "Купую":
            user_states[chat_id] = {"mode": "buy", "step": "item", "data": {}}

            send_message(chat_id, "Обери товар:", keyboard=BUY_ITEMS)
            return {"ok": True}

        if state and state["mode"] == "buy":

            if state["step"] == "item":
                state["data"]["name"] = text
                state["step"] = "qty"
                send_message(chat_id, "Введи обсяг (т):")
                return {"ok": True}

            elif state["step"] == "qty":
                state["data"]["qty"] = float(text)
                state["step"] = "price"
                send_message(chat_id, "Введи ціну за тонну:")
                return {"ok": True}

            elif state["step"] == "price":
                state["data"]["price"] = float(text)

                now = datetime.now()

                sheet = get_gsheet()
                ws = sheet.worksheet("купую")

                qty = state["data"]["qty"]
                price = state["data"]["price"]

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["data"]["name"],
                    qty,
                    price,
                    qty * price
                ])

                send_message(chat_id, "✅ Купівля записана")

                user_states.pop(chat_id)
                return {"ok": True}

        # =====================
        # 🔹 ПРОДАЮ
        # =====================

        if text == "Продаю":
            user_states[chat_id] = {"mode": "sell", "step": "item", "data": {}}

            send_message(chat_id, "Обери товар:", keyboard=SELL_ITEMS)
            return {"ok": True}

        if state and state["mode"] == "sell":

            if state["step"] == "item":
                state["data"]["name"] = text
                state["step"] = "qty"
                send_message(chat_id, "Введи кількість:")
                return {"ok": True}

            elif state["step"] == "qty":
                state["data"]["qty"] = float(text)
                state["step"] = "price"
                send_message(chat_id, "Введи ціну:")
                return {"ok": True}

            elif state["step"] == "price":
                state["data"]["price"] = float(text)

                now = datetime.now()

                sheet = get_gsheet()
                ws = sheet.worksheet("продаю")

                qty = state["data"]["qty"]
                price = state["data"]["price"]

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["data"]["name"],
                    qty,
                    "",
                    price,
                    qty * price
                ])

                send_message(chat_id, "✅ Продаж записаний")

                user_states.pop(chat_id)
                return {"ok": True}

        # =====================
        # 🔹 ВИТРАТИ
        # =====================

        if text == "Витрати":
            user_states[chat_id] = {"mode": "expense", "step": "item", "data": {}}

            send_message(chat_id, "Обери категорію:", keyboard=EXPENSE_ITEMS)
            return {"ok": True}

        if state and state["mode"] == "expense":

            if state["step"] == "item":
                state["data"]["name"] = text
                state["step"] = "amount"
                send_message(chat_id, "Введи суму:")
                return {"ok": True}

            elif state["step"] == "amount":
                amount = float(text)

                now = datetime.now()

                sheet = get_gsheet()
                ws = sheet.worksheet("витрати")

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["data"]["name"],
                    amount
                ])

                send_message(chat_id, "✅ Витрата записана")

                user_states.pop(chat_id)
                return {"ok": True}

        # fallback
        send_message(chat_id, "Натисни /start")
        return {"ok": True}

    except Exception as e:
        print("ERROR:", e)
        return {"ok": False}
