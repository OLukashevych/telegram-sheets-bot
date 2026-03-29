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

def tg():
    return f"https://api.telegram.org/bot{os.environ.get('BOT_TOKEN')}"

# =====================
# DATA
# =====================

BUY_ITEMS = [
    "Пісок буд.", "Пісок мит", "Щ 3/8", "Щ 5/20",
    "Щ 20/40", "Щ 40/70", "Відсів", "Т-крихта",
    "Земля", "Торф", "Дрова"
]

SERVICES = ["Навантажувач", "Доставка"]

EXPENSES = [
    "Паливо", "Обслуговування",
    "З/П водій 1", "З/П водій 2",
    "З/П водій", "бухгалтер", "Ремонт"
]

TAXES = [
    "Податок водій 1", "Податок водій 2",
    "Податок ФОП", "Податок за землю",
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

def num(x):
    try:
        return float(x.replace(",", "."))
    except:
        return None

def kb(items, n=3):
    k, row = [], []
    for i, x in enumerate(items, 1):
        row.append({"text": x, "callback_data": x})
        if i % n == 0:
            k.append(row)
            row = []
    if row:
        k.append(row)
    return k

# =====================
# GOOGLE
# =====================

def sheet():
    creds = json.loads(base64.b64decode(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]).decode())

    client = gspread.authorize(
        Credentials.from_service_account_info(
            creds,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    )

    return client.open_by_key(os.environ["SHEET_KEY"])

def load_users():
    try:
        ws = sheet().worksheet("users")
        for r in ws.get_all_values()[1:]:
            users[int(r[0])] = r[1]
    except:
        pass

def save_user(uid, phone):
    ws = sheet().worksheet("users")
    ws.append_row([uid, phone])
    users[uid] = phone

# =====================
# TELEGRAM
# =====================

def send(chat_id, text, k=None):
    payload = {"chat_id": chat_id, "text": text}
    if k:
        payload["reply_markup"] = {"inline_keyboard": k}
    requests.post(f"{tg()}/sendMessage", json=payload)

def ask_phone(chat_id):
    requests.post(f"{tg()}/sendMessage", json={
        "chat_id": chat_id,
        "text": "📱 Поділись номером",
        "reply_markup": {
            "keyboard": [[{"text": "📱 Надіслати номер", "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
    })

def menu(chat_id):
    send(chat_id, "📊 Меню:", [
        [{"text": "🟢 Купую", "callback_data": "BUY"},
         {"text": "🔵 Продаю", "callback_data": "SELL"}],
        [{"text": "🔴 Витрати", "callback_data": "EXP"},
         {"text": "🟡 Податки", "callback_data": "TAX"}]
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

    # ===== MESSAGE =====
    if "message" in data:
        m = data["message"]
        chat_id = m["chat"]["id"]
        user_id = m["from"]["id"]
        text = m.get("text", "")
        state = user_states.get(chat_id)

        # контакт
        if "contact" in m:
            phone = m["contact"]["phone_number"]
            save_user(user_id, phone)
            send(chat_id, "✅ Збережено")
            menu(chat_id)
            return {"ok": True}

        # старт без /start
        if not state:
            if user_id not in users:
                ask_phone(chat_id)
            else:
                menu(chat_id)
            return {"ok": True}

        # ===== QTY =====
        if state["step"] == "qty":
            q = num(text)
            if q is None:
                send(chat_id, "Введи число")
                return {"ok": True}

            state["qty"] = round(q, 2)
            state["step"] = "price"
            send(chat_id, "Ціна:")
            return {"ok": True}

        # ===== PRICE =====
        if state["step"] == "price":
            p = num(text)
            if p is None:
                send(chat_id, "Введи число")
                return {"ok": True}

            qty = state["qty"]
            total = round(qty * p, 2)

            now = datetime.now()
            u = users.get(user_id, str(user_id))

            sh = sheet()

            if state["mode"] == "buy":
                sh.worksheet("купую").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"], qty, p, total, u
                ])
            else:
                sh.worksheet("продаю").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"], qty, "т", p, total, u
                ])

            send(chat_id, f"✅ {state['item']} {qty} × {p} = {total}")
            user_states.pop(chat_id)
            menu(chat_id)
            return {"ok": True}

        # ===== AMOUNT =====
        if state["step"] == "amount":
            a = num(text)
            if a is None:
                send(chat_id, "Введи число")
                return {"ok": True}

            now = datetime.now()
            u = users.get(user_id, str(user_id))
            sh = sheet()

            if state["mode"] == "sell" and state["item"] == "Доставка":
                sh.worksheet("продаю").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    "Доставка", "", "", a, a, u
                ])
                send(chat_id, f"🚚 Доставка {a} грн")
            else:
                sh.worksheet("витрати").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"], a, u
                ])
                send(chat_id, f"✅ {state['item']} {a}")

            user_states.pop(chat_id)
            menu(chat_id)
            return {"ok": True}

    # ===== CALLBACK =====
    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}
            send(chat_id, "🟢 Купую:", kb(BUY_ITEMS))
            return {"ok": True}

        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}
            send(chat_id, "🔵 Продаю:", kb(BUY_ITEMS + SERVICES))
            return {"ok": True}

        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            send(chat_id, "🔴 Витрати:", kb(EXPENSES))
            return {"ok": True}

        if action == "TAX":
            user_states[chat_id] = {"mode": "tax", "step": "item"}
            send(chat_id, "🟡 Податки:", kb(TAXES))
            return {"ok": True}

        state = user_states.get(chat_id)

        if state and state["step"] == "item":
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

            return {"ok": True}

    return {"ok": True}
