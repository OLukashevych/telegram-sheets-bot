import os
import json
import base64
from datetime import datetime

from fastapi import FastAPI, Request
import gspread
from google.oauth2.service_account import Credentials

app = FastAPI()

def get_gsheet():
    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds_dict = json.loads(creds_json)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(os.environ["SHEET_KEY"])
    return sheet


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        message = data.get("message", {})
        text = message.get("text", "")

        if text:
            sheet = get_gsheet()

            # ⚠️ назва як у тебе в таблиці
            ws = sheet.worksheet("купую")

            now = datetime.now()

            row = [
                now.strftime("%Y-%m-%d"),  # ДатаВнесення
                now.strftime("%m"),        # Місяць
                now.strftime("%Y"),        # Рік
                text,                      # Номенклатура
                "", "", ""                 # інші поля поки пусті
            ]

            ws.append_row(row)

        return {"ok": True}

    except Exception as e:
        print("ERROR:", e)
        return {"ok": False}

 
