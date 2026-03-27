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
# 🔹 CONFIG
# =====================

def tg_url():
    return f"https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}"

# =====================
# 🔹 DATA
# =====================

BUY_ITEMS = [
    "Пісок буд.", "Пісок мит", "Щ 3/8", "Щ 5/20",
    "Щ 20/40", "Щ 40/70", "Відсів", "Т-крихта"
]

SELL_SERVICES = {
    "Навантажувач": "год",
    "Доставка": "км"
}

EXPENSE_ITEMS = [
    "Паливо", "Зарплата", "Ремонт"
]

# =====================
# 🔹 STATE
# =====================

user_states = {}

# =====================
# 🔹 TELEGRAM
# =====================

def send_message(chat_id, text):
    requests.post(f"{tg_url()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def send_inline(chat_id, text, keyboard):
    requests.post(f"{tg_url()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": keyboard}
    })

def show_menu(chat_id):
    send_inline(chat_id, "📊 Меню:", [
        [
            {"text": "🟢 Купую", "callback_data": "BUY"},
            {"text": "🔵 Продаю", "callback_data": "SELL"}
        ],
        [
            {"text": "🔴 Витрати", "callback_data": "EXP"}
        ]
    ])

# =====================
# 🔹 GOOGLE SHEETS
# =====================

def get_gsheet():
    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_dict = json.loads(creds_json)

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    client = gspread.authorize(creds)
    return client.open_by_key(os.environ["SHEET_KEY"])

# =====================
# 🔹 ROOT
# =====================

@app.get("/")
def root():
    return {"status": "ok"}

# =====================
# 🔹 WEBHOOK
# =====================

@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()

    # =====================
    # 🔹 CALLBACK
    # =====================
    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        state = user_states.get(chat_id, {})

        # BUY
        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}

            keyboard = [[{"text": x, "callback_data": x}] for x in BUY_ITEMS]
            send_inline(chat_id, "Обери товар:", keyboard)
            return {"ok": True}

        # SELL
        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}

            keyboard = [[{"text": x, "callback_data": x}] for x in BUY_ITEMS]
            keyboard += [[{"text": x, "callback_data": x}] for x in SELL_SERVICES.keys()]

            send_inline(chat_id, "Обери:", keyboard)
            return {"ok": True}

        # EXPENSE
        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}

            keyboard = [[{"text": x, "callback_data": x}] for x in EXPENSE_ITEMS]
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

                if action in SELL_SERVICES:
                    unit = SELL_SERVICES[action]
                    state["unit"] = unit

                    if unit == "год":
                        send_message(chat_id, "Введи кількість годин:")
                    else:
                        send_message(chat_id, "Введи кількість км:")
                else:
                    state["unit"] = "т"
                    send_message(chat_id, "Введи кількість тонн:")

            user_states[chat_id] = state
            return {"ok": True}

        return {"ok": True}

    # =====================
    # 🔹 MESSAGE
    # =====================

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

    state = user_states.get(chat_id)

    # 👉 завжди показуємо меню якщо нема стану
    if not state:
        show_menu(chat_id)
        return {"ok": True}

    # QTY
    if state.get("step") == "qty":
        state["qty"] = float(text)
        state["step"] = "price"

        if state["unit"] == "т":
            send_message(chat_id, "Введи ціну за тонну:")
        elif state["unit"] == "год":
            send_message(chat_id, "Введи ціну за годину:")
        else:
            send_message(chat_id, "Введи ціну за км:")

        user_states[chat_id] = state
        return {"ok": True}

    # PRICE
    if state.get("step") == "price":
        price = float(text)
        qty = state["qty"]
        total = qty * price

        now = datetime.now()
        sheet = get_gsheet()

        if state["mode"] == "buy":
            ws = sheet.worksheet("купую")
        else:
            ws = sheet.worksheet("продаю")

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

        # 🔥 красивий текст
        unit_text = {
            "т": "тонн",
            "год": "годин",
            "км": "км"
        }[state["unit"]]

        send_message(chat_id,
            f"✅ Записано:\n"
            f"{now.strftime('%d.%m.%Y')} {state['item']} {qty} {unit_text} по {price} грн.\n"
            f"Сума: {total}"
        )

        user_states.pop(chat_id)
        return {"ok": True}

    # EXPENSE
    if state.get("step") == "amount":
        amount = float(text)

        now = datetime.now()
        sheet = get_gsheet()
        ws = sheet.worksheet("витрати")

        ws.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%m"),
            now.strftime("%Y"),
            state["item"],
            amount
        ])

        send_message(chat_id,
            f"🔴 Витрата записана:\n"
            f"{state['item']} — {amount} грн"
        )

        user_states.pop(chat_id)
        return {"ok": True}

    return {"ok": True}
