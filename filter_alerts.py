import os
import pandas as pd
import requests
from pathlib import Path

# === Файлы ===
CSV_FILE = Path("alerts.csv")
XLSX_FILE = Path("alerts_filtered.xlsx")

# === Параметры фильтра ===
EXTREME_PCT = float(os.getenv("EXTREME_PCT", 200))
MIN_VOL_X = float(os.getenv("MIN_VOL_X", 2))
MIN_GAP_PCT = float(os.getenv("MIN_GAP_PCT", 6))
MIN_CHANGE_PCT = float(os.getenv("MIN_CHANGE_PCT", 6))
TOP_N = int(os.getenv("TOP_N", 20))

# === Telegram ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def safe_float(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return 0.0


def load_csv():
    df = pd.read_csv(CSV_FILE)
    for c in ["gap_pct", "change_pct", "vol_x", "volume", "avg20"]:
        df[c] = df[c].apply(safe_float)
    return df


def filter_data(df):
    extreme = (df["gap_pct"].abs() >= EXTREME_PCT) | (df["change_pct"].abs() >= EXTREME_PCT)
    normal = (df["vol_x"] >= MIN_VOL_X) & (
        (df["gap_pct"].abs() >= MIN_GAP_PCT) | (df["change_pct"].abs() >= MIN_CHANGE_PCT)
    )
    df = df[extreme | normal]
    df = df.sort_values(by="change_pct", ascending=False).head(TOP_N)
    return df


def save_excel(df):
    df = df.copy()

    # Переименовать заголовки
    df.columns = [
        "Время UTC",
        "Тикер",
        "Вчера",
        "Открытие",
        "Закрытие",
        "Объём",
        "Ср.объём 20дн",
        "ГЭП %",
        "Изм. %",
        "Отн.объём",
    ]

    try:
        with pd.ExcelWriter(XLSX_FILE, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Alerts")

            wb = writer.book
            ws = writer.sheets["Alerts"]

            # Форматы
            fmt_header = wb.add_format(
                {"bold": True, "bg_color": "#DCE6F1", "border": 1, "align": "center"}
            )
            fmt_cell = wb.add_format({"border": 1, "align": "center"})
            fmt_green = wb.add_format({"border": 1, "align": "center", "font_color": "#006100"})
            fmt_red = wb.add_format({"border": 1, "align": "center", "font_color": "#9C0006"})

            # Заголовок
            ws.set_row(0, None, fmt_header)

            # Автоширина
            for i, col in enumerate(df.columns):
                width = max(12, len(col) + 2)
                ws.set_column(i, i, width)

            # Условное форматирование
            rows = len(df)
            ws.conditional_format(f"H2:H{rows+1}", {"type": "cell", "criteria": ">", "value": 0, "format": fmt_green})
            ws.conditional_format(f"H2:H{rows+1}", {"type": "cell", "criteria": "<", "value": 0, "format": fmt_red})
            ws.conditional_format(f"I2:I{rows+1}", {"type": "cell", "criteria": ">", "value": 0, "format": fmt_green})
            ws.conditional_format(f"I2:I{rows+1}", {"type": "cell", "criteria": "<", "value": 0, "format": fmt_red})

            # Границы
            ws.conditional_format(f"A2:J{rows+1}", {"type": "no_blanks", "format": fmt_cell})

        print(f"[INFO] Saved Excel → {XLSX_FILE}")

    except PermissionError:
        print("[ERROR] Excel-файл открыт. Закрой его и перезапусти.")
        raise SystemExit(1)


def send_to_telegram(file_path):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
    try:
        with open(file_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                data={"chat_id": CHAT_ID},
                files={"document": f},
                timeout=30,
            )
        print("[INFO] Файл отправлен в Telegram.")
    except Exception as e:
        print(f"[ERROR] Ошибка при отправке в Telegram: {e}")


if __name__ == "__main__":
    if not CSV_FILE.exists():
        print("[ERROR] Файл alerts.csv не найден.")
        raise SystemExit(1)

    df = load_csv()
    filtered = filter_data(df)
    save_excel(filtered)
    send_to_telegram(XLSX_FILE)
