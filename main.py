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
    "Щ 20/40", "Щ 40/70", "Відсів", "Т-крихта",
    "Земля", "Торф", "Дрова"
]

SERVICES = {
    "Навантажувач": "год",
    "Доставка": None  # 👈 без одиниці
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
users = {}

# =====================
# HELPERS
# =====================

def parse_number(text):
    try:
        return float(text.replace(",", "."))
    except:
        return None


def build_keyboard(items, cols=3):
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


def load_users():
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("users")

        rows = ws.get_all_values()

        for r in rows[1:]:
            users[int(r[0])] = r[1]
    except:
        pass


def save_user(user_id, phone):
    sheet = get_sheet()
    ws = sheet.worksheet("users")

    ws.append_row([user_id, phone])
    users[user_id] = phone


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


def request_phone(chat_id):
    requests.post(f"{tg_url()}/sendMessage", json={
        "chat_id": chat_id,
        "text": "📱 Поділись номером",
        "reply_markup": {
            "keyboard": [[{
                "text": "📱 Надіслати номер",
                "request_contact": True
            }]],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
    })


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
# INIT
# =====================

load_users()

# =====================
# WEBHOOK
# =====================

@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()

    # =====================
    # MESSAGE
    # =====================

    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]

        if user_id not in users and "contact" not in message:
            request_phone(chat_id)
            return {"ok": True}

        if "contact" in message:
            phone = message["contact"]["phone_number"]
            save_user(user_id, phone)

            send(chat_id, "✅ Збережено")
            menu(chat_id)
            return {"ok": True}

        state = user_states.get(chat_id)
        text = message.get("text", "")

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
                send(chat_id, "Введи число")
                return {"ok": True}

            state["qty"] = round(qty, 2)
            state["step"] = "price"

            send(chat_id, "Ціна:")
            user_states[chat_id] = state
            return {"ok": True}

        # ===== PRICE =====

        if state.get("step") == "price":
            price = parse_number(text)

            if price is None:
                send(chat_id, "Введи число")
                return {"ok": True}

            qty = state["qty"]
            total = round(qty * price, 2)

            now = datetime.now()
            user_identifier = users.get(user_id, str(user_id))

            sheet = get_sheet()

            if state["mode"] == "buy":
                ws = sheet.worksheet("купую")

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    qty,
                    price,
                    total,
                    user_identifier
                ])

            else:
                ws = sheet.worksheet("продаю")

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    qty,
                    state.get("unit", "т"),
                    price,
                    total,
                    user_identifier
                ])

            send(chat_id, f"✅ {state['item']} {qty} × {price} = {total}")

            user_states.pop(chat_id)
            menu(chat_id)
            return {"ok": True}

        # ===== AMOUNT =====

        if state.get("step") == "amount":
            amount = parse_number(text)

            if amount is None:
                send(chat_id, "Введи число")
                return {"ok": True}

            user_identifier = users.get(user_id, str(user_id))
            sheet = get_sheet()

            now = datetime.now()

            # 🚚 доставка
            if state["mode"] == "sell" and state["item"] == "Доставка":
                ws = sheet.worksheet("продаю")

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    "",  # qty
                    "",  # unit
                    amount,
                    amount,
                    user_identifier
                ])

                send(chat_id, f"🚚 Доставка: {amount} грн")

            else:
                ws = sheet.worksheet("витрати")

                ws.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    amount,
                    user_identifier
                ])

                send(chat_id, f"✅ {state['item']} {amount}")

            user_states.pop(chat_id)
            menu(chat_id)
            return {"ok": True}

    # =====================
    # CALLBACK
    # =====================

    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}
            send(chat_id, "🟢 Купую:", build_keyboard(BUY_ITEMS, 3))
            return {"ok": True}

        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}

            keyboard = build_keyboard(BUY_ITEMS, 3)
            keyboard += build_keyboard(list(SERVICES.keys()), 3)

            send(chat_id, "🔵 Продаю:", keyboard)
            return {"ok": True}

        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            send(chat_id, "🔴 Витрати:", build_keyboard(EXPENSES, 3))
            return {"ok": True}

        if action == "TAX":
            user_states[chat_id] = {"mode": "tax", "step": "item"}
            send(chat_id, "🟡 Податки:", build_keyboard(TAXES, 3))
            return {"ok": True}

        state = user_states.get(chat_id)

        if state and state.get("step") == "item":
            state["item"] = action

            if action == "Доставка":
                state["step"] = "amount"
                send(chat_id, "Сума доставки:")

            elif state["mode"] in ["exp", "tax"]:
                state["step"] = "amount"
                send(chat_id, "Сума:")

            else:
                state["step"] = "qty"
                send(chat_id, "Кількість:")

            user_states[chat_id] = state
            return {"ok": True}

    return {"ok": True}
