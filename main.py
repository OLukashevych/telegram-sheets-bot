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
    ("SAND_BUD", "Пісок буд."),
    ("SAND_MIT", "Пісок мит"),
    ("FRACTION_3_8", "Щ 3/8"),
    ("FRACTION_5_20", "Щ 5/20"),
    ("FRACTION_20_40", "Щ 20/40"),
    ("FRACTION_40_70", "Щ 40/70"),
    ("SCREENINGS", "Відсів"),
    ("T_KRYHTA", "Т-крихта"),
]

SELL_SERVICES = [
    ("LOADER", "Навантажувач", "год"),
    ("DELIVERY", "Доставка", "км"),
]

EXPENSE_ITEMS = [
    ("FUEL", "Заправка"),
    ("SALARY", "Зарплата"),
    ("REPAIR", "Ремонт"),
]

# 🔹 STATE
user_states = {}

# 🔹 TELEGRAM

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def send_inline(chat_id, text, keyboard):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": keyboard
        }
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

# 🔹 WEBHOOK

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    # =========================
    # 🔹 CALLBACK BUTTONS
    # =========================
    if "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        action = callback["data"]

        # 🔹 MAIN MENU
        if action == "MENU":
            send_inline(chat_id, "Обери дію:", [
                [{"text": "Купую", "callback_data": "BUY"}],
                [{"text": "Продаю", "callback_data": "SELL"}],
                [{"text": "Витрати", "callback_data": "EXPENSE"}],
            ])
            return {"ok": True}

        # 🔹 BUY
        if action == "BUY":
            keyboard = [[{"text": label, "callback_data": code}] for code, label in BUY_ITEMS]

            user_states[chat_id] = {"mode": "buy"}

            send_inline(chat_id, "Обери товар:", keyboard)
            return {"ok": True}

        # 🔹 SELL
        if action == "SELL":
            keyboard = [[{"text": label, "callback_data": code}] for code, label in BUY_ITEMS]

            keyboard += [
                [{"text": "Навантажувач", "callback_data": "LOADER"}],
                [{"text": "Доставка", "callback_data": "DELIVERY"}],
            ]

            user_states[chat_id] = {"mode": "sell"}

            send_inline(chat_id, "Обери:", keyboard)
            return {"ok": True}

        # 🔹 EXPENSE
        if action == "EXPENSE":
            keyboard = [[{"text": label, "callback_data": code}] for code, label in EXPENSE_ITEMS]

            user_states[chat_id] = {"mode": "expense"}

            send_inline(chat_id, "Обери витрату:", keyboard)
            return {"ok": True}

        # 🔹 ITEM SELECTED
        state = user_states.get(chat_id)

        if not state:
            return {"ok": True}

        # BUY / SELL
        for code, label in BUY_ITEMS:
            if action == code:
                state["item"] = label
                state["step"] = "qty"
                user_states[chat_id] = state

                send_message(chat_id, "Введи кількість:")
                return {"ok": True}

        # SERVICES
        for code, label, unit in SELL_SERVICES:
            if action == code:
                state["item"] = label
                state["unit"] = unit
                state["step"] = "qty"
                user_states[chat_id] = state

                send_message(chat_id, f"Введи кількість ({unit}):")
                return {"ok": True}

        # EXPENSE ITEM
        for code, label in EXPENSE_ITEMS:
            if action == code:
                state["item"] = label
                state["step"] = "amount"
                user_states[chat_id] = state

                send_message(chat_id, "Введи суму:")
                return {"ok": True}

        return {"ok": True}

    # =========================
    # 🔹 TEXT MESSAGE
    # =========================

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

    # START
    if text == "/start":
        send_inline(chat_id, "Обери дію:", [
            [{"text": "Купую", "callback_data": "BUY"}],
            [{"text": "Продаю", "callback_data": "SELL"}],
            [{"text": "Витрати", "callback_data": "EXPENSE"}],
        ])
        return {"ok": True}

    state = user_states.get(chat_id)

    if not state:
        send_message(chat_id, "Натисни /start")
        return {"ok": True}

    # 🔹 BUY / SELL FLOW

    if state.get("step") == "qty":
        state["qty"] = float(text)
        state["step"] = "price"
        user_states[chat_id] = state

        send_message(chat_id, "Введи ціну:")
        return {"ok": True}

    elif state.get("step") == "price":
        price = float(text)
        qty = state["qty"]

        sheet = get_gsheet()

        if state["mode"] == "buy":
            ws = sheet.worksheet("купую")
        else:
            ws = sheet.worksheet("продаю")

        now = datetime.now()

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            state["item"],
            qty,
            price,
            qty * price
        ])

        send_message(chat_id, "✅ Записано")

        user_states.pop(chat_id)

        return {"ok": True}

    # 🔹 EXPENSE

    if state.get("step") == "amount":
        amount = float(text)

        sheet = get_gsheet()
        ws = sheet.worksheet("витрати")

        now = datetime.now()

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            state["item"],
            amount
        ])

        send_message(chat_id, "✅ Витрата записана")

        user_states.pop(chat_id)

        return {"ok": True}

    return {"ok": True}
