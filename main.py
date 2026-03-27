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

def api():
    token = os.environ.get("BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}"

def send_message(chat_id, text):
    requests.post(f"{api()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def send_inline(chat_id, text, keyboard):
    requests.post(f"{api()}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": keyboard}
    })

# =========================
# 🔹 GOOGLE SHEETS
# =========================

def get_gsheet():
    creds = json.loads(base64.b64decode(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]))
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_info(creds, scopes=scope)
    client = gspread.authorize(credentials)
    return client.open_by_key(os.environ["SHEET_KEY"])

# =========================
# 🔹 DATA
# =========================

BUY_ITEMS = [
    "Пісок буд.", "Пісок мит", "Щ 3/8",
    "Щ 5/20", "Щ 20/40", "Щ 40/70",
    "Відсів", "Т-крихта"
]

SELL_ITEMS = [
    {"name": i, "unit": "тонн"} for i in BUY_ITEMS
] + [
    {"name": "Навантажувач", "unit": "годин"},
    {"name": "Доставка", "unit": "км"}
]

EXPENSE_ITEMS = ["Паливо", "Зарплата", "Ремонт", "Інше"]

user_states = {}

# =========================
# 🔹 ROOT
# =========================

@app.get("/")
def root():
    return {"ok": True}

# =========================
# 🔹 MENU
# =========================

def show_menu(chat_id):
    send_inline(chat_id, "👇 Обери дію:", [
        [{"text": "Купую", "callback_data": "BUY"}],
        [{"text": "Продаю", "callback_data": "SELL"}],
        [{"text": "Витрати", "callback_data": "EXP"}],
    ])

# =========================
# 🔹 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()
    print("INCOMING:", data)

    # ======================
    # CALLBACK
    # ======================

    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        action = cb["data"]

        state = user_states.get(chat_id, {})

        if action == "BUY":
            user_states[chat_id] = {"mode": "buy", "step": "item"}
            keyboard = [[{"text": i, "callback_data": i}] for i in BUY_ITEMS]
            send_inline(chat_id, "Обери товар:", keyboard)
            return {"ok": True}

        if action == "SELL":
            user_states[chat_id] = {"mode": "sell", "step": "item"}
            keyboard = [[{"text": i["name"], "callback_data": i["name"]}] for i in SELL_ITEMS]
            send_inline(chat_id, "Обери:", keyboard)
            return {"ok": True}

        if action == "EXP":
            user_states[chat_id] = {"mode": "exp", "step": "item"}
            keyboard = [[{"text": i, "callback_data": i}] for i in EXPENSE_ITEMS]
            send_inline(chat_id, "Обери витрату:", keyboard)
            return {"ok": True}

        # ITEM SELECT
        if state.get("step") == "item":

            if state["mode"] == "exp":
                state["item"] = action
                state["step"] = "amount"
                user_states[chat_id] = state
                send_message(chat_id, "Введи суму:")
                return {"ok": True}

            if state["mode"] == "sell":
                item = next(x for x in SELL_ITEMS if x["name"] == action)
                state["item"] = item["name"]
                state["unit"] = item["unit"]
            else:
                state["item"] = action
                state["unit"] = "тонн"

            state["step"] = "qty"
            user_states[chat_id] = state

            send_message(chat_id, f"Введи кількість {state['unit']}:")
            return {"ok": True}

    # ======================
    # TEXT
    # ======================

    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id:
        return {"ok": True}

    if text in ["/menu", "/start"]:
    show_menu(chat_id)
    return {"ok": True}

    state = user_states.get(chat_id)

    if not state:
        show_menu(chat_id)
        return {"ok": True}

    # ======================
    # QTY
    # ======================

    if state.get("step") == "qty":
        state["qty"] = float(text.replace(",", "."))
        state["step"] = "price"
        user_states[chat_id] = state

        unit = state["unit"]

        if unit == "тонн":
            send_message(chat_id, "Введи ціну за тонну (грн):")
        elif unit == "годин":
            send_message(chat_id, "Введи ціну за годину (грн):")
        else:
            send_message(chat_id, "Введи ціну за км (грн):")

        return {"ok": True}

    # ======================
    # PRICE
    # ======================

    if state.get("step") == "price":
        price = float(text.replace(",", "."))
        qty = state["qty"]
        unit = state["unit"]

        now = datetime.now()
        sheet = get_gsheet()

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

            text_msg = (
                f"✅ Записано:\n"
                f"{now.strftime('%d.%m.%Y')} купила {state['item']} "
                f"{qty} {unit} по {price} грн за {unit}. "
                f"Сума {qty * price}"
            )

        else:
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

            text_msg = (
                f"✅ Записано:\n"
                f"{now.strftime('%d.%m.%Y')} продала {state['item']} "
                f"{qty} {unit} по {price} грн за {unit}. "
                f"Виручка {qty * price}"
            )

        send_message(chat_id, text_msg)
        user_states.pop(chat_id)
        show_menu(chat_id)
        return {"ok": True}

    # ======================
    # EXPENSE
    # ======================

    if state.get("step") == "amount":
        amount = float(text.replace(",", "."))
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

        send_message(chat_id, f"✅ {state['item']} — {amount} грн")
        user_states.pop(chat_id)
        show_menu(chat_id)
        return {"ok": True}

    return {"ok": True}
