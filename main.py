import os
import json
import base64
from datetime import datetime

from fastapi import FastAPI, Request
import gspread
from google.oauth2.service_account import Credentials
import requests

app = FastAPI()

# =========================
# 🔹 TELEGRAM
# =========================

def get_api():
    token = os.environ.get("BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}"

def send_message(chat_id, text):
    requests.post(f"{get_api()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def send_inline(chat_id, text, keyboard):
    requests.post(f"{get_api()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": keyboard
        }
    })

# =========================
# 🔹 GOOGLE SHEETS
# =========================

def get_gsheet():
    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_dict = json.loads(creds_json)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    return client.open_by_key(os.environ["SHEET_KEY"])

# =========================
# 🔹 DATA
# =========================

BUY_ITEMS = [
    "Пісок буд.", "Пісок мит", "Щ 3/8",
    "Щ 5/20", "Щ 20/40", "Щ 40/70",
    "Відсів", "Т-крихта"
]

SELL_ITEMS = BUY_ITEMS + ["Навантажувач", "Доставка"]

EXPENSE_ITEMS = ["Паливо", "Зарплата", "Ремонт", "Інше"]

user_states = {}

# =========================
# 🔹 ROOT
# =========================

@app.get("/")
def root():
    return {"ok": True}

# =========================
# 🔹 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("INCOMING:", data)

    # ======================
    # CALLBACK BUTTONS
    # ======================

    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        state = user_states.get(chat_id, {})

        # MAIN MENU
        if action == "MENU":
            send_inline(chat_id, "Обери дію:", [
                [{"text": "Купую", "callback_data": "BUY"}],
                [{"text": "Продаю", "callback_data": "SELL"}],
                [{"text": "Витрати", "callback_data": "EXP"}],
            ])
            return {"ok": True}

        # BUY
        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}
            keyboard = [[{"text": i, "callback_data": i}] for i in BUY_ITEMS]
            send_inline(chat_id, "Обери товар:", keyboard)
            return {"ok": True}

        # SELL
        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}
            keyboard = [[{"text": i, "callback_data": i}] for i in SELL_ITEMS]
            send_inline(chat_id, "Обери:", keyboard)
            return {"ok": True}

        # EXPENSE
        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            keyboard = [[{"text": i, "callback_data": i}] for i in EXPENSE_ITEMS]
            send_inline(chat_id, "Обери витрату:", keyboard)
            return {"ok": True}

        # ITEM SELECT
        if state.get("step") == "item":
            state["item"] = action

            if state["mode"] == "exp":
                state["step"] = "amount"
                send_message(chat_id, "Введи суму:")
            else:
                state["step"] = "qty"
                send_message(chat_id, "Введи кількість:")

            user_states[chat_id] = state
            return {"ok": True}

    # ======================
    # TEXT INPUT
    # ======================

    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id:
        return {"ok": True}

    # START
    if text == "/start":
        send_inline(chat_id, "Обери дію:", [
            [{"text": "Купую", "callback_data": "BUY"}],
            [{"text": "Продаю", "callback_data": "SELL"}],
            [{"text": "Витрати", "callback_data": "EXP"}],
        ])
        return {"ok": True}

    state = user_states.get(chat_id)

    if not state:
        send_message(chat_id, "Натисни /start")
        return {"ok": True}

    # ======================
    # BUY / SELL FLOW
    # ======================

    if state.get("step") == "qty":
        state["qty"] = float(text)
        state["step"] = "price"
        user_states[chat_id] = state

        send_message(chat_id, "Введи ціну:")
        return {"ok": True}

    if state.get("step") == "price":
        price = float(text)
        qty = state["qty"]

        sheet = get_gsheet()
        now = datetime.now()

        if state["mode"] == "buy":
            ws = sheet.worksheet("купую")
            ws.append_row([
                now.strftime("%Y-%m-%d"),
                now.strftime("%m"),
                now.strftime("%Y"),
                state["item"],
                qty,
                price,
                qty * price
            ])

        elif state["mode"] == "sell":
            ws = sheet.worksheet("продаю")
            ws.append_row([
                now.strftime("%Y-%m-%d"),
                now.strftime("%m"),
                now.strftime("%Y"),
                state["item"],
                qty,
                "",
                price,
                qty * price
            ])

        send_message(chat_id, "✅ Записано")
        user_states.pop(chat_id)

        return {"ok": True}

    # ======================
    # EXPENSE FLOW
    # ======================

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
