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
    "Паливо",
    "Обслуговування",
    "З/П водій 1",
    "З/П водій 2",
    "З/П водій",
    "бухгалтер",
    "Ремонт"
]

TAXES = [
    "Податок водій 1",
    "Податок водій 2",
    "Податок ФОП",
    "Податок за землю",
    "Податок за Н/Ж прим."
]

# =====================
# STATE
# =====================

user_states = {}

# =====================
# HELPERS
# =====================

def parse_number(text):
    try:
        return float(text.replace(",", "."))
    except:
        return None

def build_keyboard(items, cols=2):
    keyboard = []
    row = []

    for i, item in enumerate(items, 1):
        row.append({"text": item, "callback_data": item})

        if i % cols == 0:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return keyboard

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
            {"text": "🔴 Витрати", "callback_data": "EXP"},
            {"text": "🟡 Податки", "callback_data": "TAX"}
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
            send(chat_id, "🟢 Купую товар:", build_keyboard(BUY_ITEMS, 2))
            return {"ok": True}

        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}

            keyboard = build_keyboard(BUY_ITEMS, 2)
            keyboard += build_keyboard(list(SERVICES.keys()), 2)

            send(chat_id, "🔵 Продаю:", keyboard)
            return {"ok": True}

        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            send(chat_id, "🔴 Витрати:", build_keyboard(EXPENSES, 2))
            return {"ok": True}

        if action == "TAX":
            user_states[chat_id] = {"mode": "tax", "step": "item"}
            send(chat_id, "🟡 Податки:", build_keyboard(TAXES, 2))
            return {"ok": True}

        # ===== ITEM SELECT =====

        if state.get("step") == "item":
            state["item"] = action

            if state["mode"] in ["exp", "tax"]:
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

    state = user_states.get(chat_id)

    if text == "/start":
        menu(chat_id)
        return {"ok": True}

    if not state:
        menu(chat_id)
        return {"ok": True}

    # ===== QTY =====

    if state.get("step") == "qty":
        qty = parse_number(text)

        if qty is None:
            send(chat_id, "Введи число (10 або 10,5)")
            return {"ok": True}

        state["qty"] = round(qty, 2)
        state["step"] = "price"

        if state["unit"] == "т":
            send(chat_id, "Ціна за тонну:")
        elif state["unit"] == "год":
            send(chat_id, "Ціна за годину:")
        else:
            send(chat_id, "Ціна за км:")

        user_states[chat_id] = state
        return {"ok": True}

    # ===== PRICE =====

    if state.get("step") == "price":
        price = parse_number(text)

        if price is None:
            send(chat_id, "Введи коректну ціну")
            return {"ok": True}

        price = round(price, 2)
        qty = state["qty"]
        total = round(qty * price, 2)

        now = datetime.now()
        date = now.strftime("%d.%m.%Y")

        sheet = get_sheet()
        ws = sheet.worksheet("продаю" if state["mode"] == "sell" else "купую")

        if state["mode"] == "buy":
            ws.append_row([
                now.strftime("%Y-%m-%d"),
                now.strftime("%m"),
                now.strftime("%Y"),
                state["item"],
                qty,
                price,
                total
            ])

            text_msg = f"""🟢 Купівля:
{date}
{state['item']} — {qty} т × {price}
Сума: {total} грн"""

        else:
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

            text_msg = f"""🔵 Продаж:
{date}
{state['item']} — {qty} {state['unit']} × {price}
Виручка: {total} грн"""

        send(chat_id, text_msg)

        user_states.pop(chat_id)
        menu(chat_id)

        return {"ok": True}

    # ===== EXPENSE / TAX =====

    if state.get("step") == "amount":
        amount = parse_number(text)

        if amount is None:
            send(chat_id, "Введи суму числом")
            return {"ok": True}

        amount = round(amount, 2)

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

        icon = "🔴" if state["mode"] == "exp" else "🟡"

        send(chat_id, f"""{icon} Записано:
{date}
{state['item']} — {amount} грн""")

        user_states.pop(chat_id)
        menu(chat_id)

        return {"ok": True}

    return {"ok": True}
