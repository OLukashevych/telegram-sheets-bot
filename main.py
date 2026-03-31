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
    "Щ 20/40", "Щ 40/70", "Щ 0/40",
    "Відсів", "Т-крихта",
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

user_states = {}

# =====================
# HELPERS
# =====================

def num(x):
    try:
        return float(str(x).replace(",", "."))
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
# TELEGRAM
# =====================

def send(chat_id, text, k=None):
    payload = {"chat_id": chat_id, "text": text}
    if k:
        payload["reply_markup"] = {"inline_keyboard": k}
    requests.post(f"{tg()}/sendMessage", json=payload)

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

        if not state:
            menu(chat_id)
            return {"ok": True}

        # ===== ВВІД СУМИ =====
        if state["step"] == "amount":
            amount = num(text)
            if amount is None:
                send(chat_id, "Введи суму числом")
                return {"ok": True}

            now = datetime.now()
            u = str(user_id)
            sh = sheet()

            # доставка
            if state["mode"] == "sell" and state["item"] == "Доставка":
                sh.worksheet("продаю").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    "Доставка",
                    "",
                    "",
                    amount,
                    amount,
                    u
                ])

                send(chat_id,
                     f"🚚 Доставка\n"
                     f"Сума: {amount} грн\n"
                     f"📅 {now.strftime('%d.%m.%Y')}"
                )

                user_states.pop(chat_id)
                menu(chat_id)
                return {"ok": True}

            # витрати
            sh.worksheet("витрати").append_row([
                now.strftime("%Y-%m-%d"),
                now.strftime("%m"),
                now.strftime("%Y"),
                state["item"],
                round(amount, 2),
                u,
                ""
            ])

            send(chat_id,
                 f"✅ {state['item']}\n"
                 f"Сума: {round(amount, 2)}\n"
                 f"📅 {now.strftime('%d.%m.%Y')}"
            )

            user_states.pop(chat_id)
            menu(chat_id)
            return {"ok": True}

        # ===== КІЛЬКІСТЬ =====
        if state["step"] == "qty":
            q = num(text)
            if q is None:
                send(chat_id, "Введи кількість числом")
                return {"ok": True}

            state["qty"] = round(q, 2)
            state["step"] = "price"
            send(chat_id, "Ціна:")
            return {"ok": True}

        # ===== ЦІНА =====
        if state["step"] == "price":
            p = num(text)
            if p is None:
                send(chat_id, "Введи ціну числом")
                return {"ok": True}

            qty = state["qty"]
            total = round(qty * p, 2)

            now = datetime.now()
            u = str(user_id)
            sh = sheet()

            if state["mode"] == "buy":
                sh.worksheet("купую").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    qty,
                    round(p, 2),
                    total,
                    u
                ])
            else:
                unit = "т"
                if state["item"] == "Навантажувач":
                    unit = "год"

                sh.worksheet("продаю").append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%m"),
                    now.strftime("%Y"),
                    state["item"],
                    qty,
                    unit,
                    round(p, 2),
                    total,
                    u
                ])

            # ✅ ФІНАЛЬНЕ ПОВІДОМЛЕННЯ БЕЗ ЧАСУ
            send(chat_id,
                 f"✅ Записано:\n"
                 f"Номенклатура: {state['item']}\n"
                 f"Кількість: {qty}\n"
                 f"Ціна: {round(p, 2)}\n"
                 f"Сума: {total}\n"
                 f"📅 {now.strftime('%d.%m.%Y')}"
            )

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
            send(chat_id, "🟡 Податки:", kb(TAXES, n=2))
            return {"ok": True}

        state = user_states.get(chat_id)

        if state and state["step"] == "item":
            state["item"] = action

            if action == "Доставка":
                state["step"] = "amount"
                send(chat_id, "Сума доставки:")
                return {"ok": True}

            if state["mode"] in ["exp", "tax"]:
                state["step"] = "amount"
                send(chat_id, "Сума:")
                return {"ok": True}

            state["step"] = "qty"
            send(chat_id, "Кількість:")
            return {"ok": True}

    return {"ok": True}
