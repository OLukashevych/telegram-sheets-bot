import os
import json
import base64
from datetime import datetime

from fastapi import FastAPI, Request
import gspread
from google.oauth2.service_account import Credentials
import requests

app = FastAPI()

# =====================
# CONFIG
# =====================

def tg_url():
    return f"https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}"

# =====================
# DATA
# =====================

BUY_ITEMS = [
    "Пісок буд.", "Пісок мит", "Щ 3/8", "Щ 5/20",
    "Щ 20/40", "Щ 40/70", "Відсів", "Т-крихта"
]

SERVICES = {
    "Навантажувач": "год",
    "Доставка": "км"
}

EXPENSES = [
    "Паливо", "Зарплата", "Ремонт"
]

# =====================
# STATE
# =====================

user_states = {}

# =====================
# TELEGRAM
# =====================

def send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}

    requests.post(f"{tg_url()}/sendMessage", json=payload)


def menu(chat_id):
    send(chat_id, "📊 Меню:", [
        [
            {"text": "🟢 Купую", "callback_data": "BUY"},
            {"text": "🔵 Продаю", "callback_data": "SELL"}
        ],
        [
            {"text": "🔴 Витрати", "callback_data": "EXP"}
        ]
    ])

# =====================
# GOOGLE SHEETS
# =====================

def get_sheet():
    creds = json.loads(
        base64.b64decode(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]).decode()
    )

    client = gspread.authorize(
        Credentials.from_service_account_info(
            creds,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    )

    return client.open_by_key(os.environ["SHEET_KEY"])

# =====================
# WEBHOOK
# =====================

@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()

    # =====================
    # CALLBACK
    # =====================
    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        state = user_states.get(chat_id, {})

        # ===== MENU =====

        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}
            send(chat_id, "🟢 Купую товар:", [[{"text": x, "callback_data": x}] for x in BUY_ITEMS])
            return {"ok": True}

        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}

            keyboard = [[{"text": x, "callback_data": x}] for x in BUY_ITEMS]
            keyboard += [[{"text": x, "callback_data": x}] for x in SERVICES]

            send(chat_id, "🔵 Продаю:", keyboard)
            return {"ok": True}

        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            send(chat_id, "🔴 Витрати:", [[{"text": x, "callback_data": x}] for x in EXPENSES])
            return {"ok": True}

        # ===== ITEM SELECT =====

        if state.get("step") == "item":
            state["item"] = action

            if state["mode"] == "exp":
                state["step"] = "amount"
                send(chat_id, "Введи суму:")
            else:
                state["step"] = "qty"

                if action in SERVICES:
                    state["unit"] = SERVICES[action]
                    send(chat_id, f"Введи кількість {state['unit']}:")
                else:
                    state["unit"] = "т"
                    send(chat_id, "Введи кількість тонн:")

            user_states[chat_id] = state
            return {"ok": True}

        return {"ok": True}

    # =====================
    # MESSAGE
    # =====================

    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id:
        return {"ok": True}

    # 👉 старт / будь-яке повідомлення без state
    state = user_states.get(chat_id)

    if text == "/start":
        menu(chat_id)
        return {"ok": True}

    if not state:
        menu(chat_id)
        return {"ok": True}

    # ===== QTY =====

    if state.get("step") == "qty":
        state["qty"] = float(text)
        state["step"] = "price"

        if state["unit"] == "т":
            send(chat_id, "Введи ціну за тонну:")
        elif state["unit"] == "год":
            send(chat_id, "Введи ціну за годину:")
        else:
            send(chat_id, "Введи ціну за км:")

        user_states[chat_id] = state
        return {"ok": True}

    # ===== PRICE =====

    if state.get("step") == "price":
        price = float(text)
        qty = state["qty"]
        total = qty * price

        now = datetime.now()
        date = now.strftime("%d.%m.%Y")

        sheet = get_sheet()
        ws = sheet.worksheet("купую" if state["mode"] == "buy" else "продаю")

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            state["item"],
            qty,
            state["unit"],
            price,
            total
        ])

        # красивий текст
        if state["mode"] == "buy":
            text_msg = f"""🟢 Купівля записана:
{date}
{state['item']} — {qty} т × {price} грн
Сума: {total} грн"""

        else:
            unit = state["unit"]
            text_msg = f"""🔵 Продаж записаний:
{date}
{state['item']} — {qty} {unit} × {price} грн
Виручка: {total} грн"""

        send(chat_id, text_msg)

        user_states.pop(chat_id)
        menu(chat_id)

        return {"ok": True}

    # ===== EXPENSE =====

    if state.get("step") == "amount":
        amount = float(text)

        now = datetime.now()
        date = now.strftime("%d.%m.%Y")

        sheet = get_sheet()
        ws = sheet.worksheet("витрати")

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            state["item"],
            amount
        ])

        send(chat_id, f"""🔴 Витрата записана:
{date}
{state['item']} — {amount} грн""")

        user_states.pop(chat_id)
        menu(chat_id)

        return {"ok": True}

    return {"ok": True}
