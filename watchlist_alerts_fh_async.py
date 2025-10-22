import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

# === Paths ===
BASE_DIR = Path(__file__).resolve().parent
WATCHLIST = BASE_DIR / "watchlist.csv"
ALERTS = BASE_DIR / "alerts.csv"
KEY_FILE = BASE_DIR / "finnhub.key"

# === Load API Key ===
if not KEY_FILE.exists():
    raise FileNotFoundError("Missing finnhub.key! Create it and paste your API token inside.")
with open(KEY_FILE) as f:
    API_KEY = f.read().strip()

# === Settings ===
MAX_CONCURRENT = 20  # parallel requests
QUOTE_URL = "https://finnhub.io/api/v1/quote"
CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"

def load_watchlist():
    df = pd.read_csv(WATCHLIST, header=None)
    tickers = [t.strip().upper() for t in df[0].tolist() if isinstance(t, str) and t.strip()]
    return sorted(set(tickers))

async def fetch_json(session, url):
    for attempt in range(3):
        try:
            async with session.get(url, timeout=10) as r:
                if r.status == 429:
                    await asyncio.sleep(1.2)  # rate limit backoff
                    continue
                if r.status != 200:
                    return None
                return await r.json()
        except Exception:
            await asyncio.sleep(0.5)
    return None

async def get_ticker_data(session, ticker):
    """Fetch quote + 20-day volume avg for one ticker"""
    quote_url = f"{QUOTE_URL}?symbol={ticker}&token={API_KEY}"
    quote = await fetch_json(session, quote_url)
    if not quote or not quote.get("c"):
        return None

    to_ts = int(datetime.now(timezone.utc).timestamp())
    from_ts = to_ts - 20 * 86400
    candle_url = f"{CANDLE_URL}?symbol={ticker}&resolution=D&from={from_ts}&to={to_ts}&token={API_KEY}"
    candles = await fetch_json(session, candle_url)
    avg20 = 0
    if candles and candles.get("s") == "ok" and candles.get("v"):
        vols = candles["v"]
        avg20 = sum(vols) / len(vols) if vols else 0

    prev_close = quote.get("pc", 0)
    open_p = quote.get("o", 0)
    close = quote.get("c", 0)
    volume = quote.get("v", 0)

    if not prev_close or not close:
        return None

    gap_pct = ((open_p - prev_close) / prev_close) * 100 if prev_close else 0
    change_pct = ((close - prev_close) / prev_close) * 100 if prev_close else 0
    vol_x = (volume / avg20) if avg20 else 0

    # sanity filter: игнорировать фантомы
    if abs(change_pct) > 80 and volume < 1_000_000:
        return None

    return {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "prev_close": round(prev_close, 4),
        "open": round(open_p, 4),
        "close": round(close, 4),
        "volume": int(volume),
        "avg20": int(avg20),
        "gap_pct": round(gap_pct, 2),
        "change_pct": round(change_pct, 2),
        "vol_x": round(vol_x, 2),
    }

async def main():
    tickers = load_watchlist()
    print(f"[INFO] Checking {len(tickers)} tickers via Finnhub (async mode)...")
    results = []

    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [get_ticker_data(session, t) for t in tickers]
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            res = await task
            if res:
                results.append(res)
            if i % 50 == 0:
                print(f"[INFO] Processed {i}/{len(tickers)}...")

    if not results:
        print("[WARN] No valid data.")
        return

    df = pd.DataFrame(results)
    df.to_csv(ALERTS, index=False)
    print(f"Saved {ALERTS} — rows: {len(df)}")

if __name__ == "__main__":
    asyncio.run(main())
