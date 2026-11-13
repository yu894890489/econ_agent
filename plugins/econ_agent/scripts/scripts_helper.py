"""共用小函数"""
import sys
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
import requests
from datetime import date
from core.db import upsert_price


def sync_gold_btc(conn):
    """gold-api 快照 XAU/BTC"""
    d = date.today().isoformat()
    for sym, code in (("XAU.USD", "XAU"), ("BTC.USD", "BTC")):
        try:
            r = requests.get(f"https://api.gold-api.com/price/{code}", timeout=15)
            px = r.json()["price"]
            upsert_price(conn, {"date": d, "symbol": sym, "open": px, "high": px, "low": px,
                                "close": px, "volume": 0, "amount": 0, "source": "gold-api"})
        except Exception:
            pass
