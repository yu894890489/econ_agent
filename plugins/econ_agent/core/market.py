"""
行情数据模块
数据源优先级：
  1. 东方财富（A股/港股/美股/期货/黄金）
  2. CoinGecko（BTC/ETH，免费 10-30次/分钟）
所有行情统一 upsert 到 prices 表
"""
import time
import json
import logging
import requests
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .db import upsert_price

log = logging.getLogger(__name__)


class NetError(Exception):
    pass


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=20),
       retry=retry_if_exception_type((requests.RequestException, NetError)), reraise=True)
def _get(url, **kw):
    kw.setdefault("timeout", 20)
    hdrs = kw.pop("headers", None)
    if hdrs:
        merged = dict(HEADERS)
        merged.update(hdrs)
        hdrs = merged
    r = requests.get(url, headers=hdrs or HEADERS, **kw)
    if r.status_code != 200 or not r.text.strip():
        raise NetError(f"bad response {r.status_code} len={len(r.text)}")
    return r

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

# 市场前缀映射（东财 secid）
MARKET_PREFIX = {"CN_SH": "1.", "CN_SZ": "0.", "US": "105.", "HK": "116."}


# 指数映射（东财全球指数前缀 100）
INDEX_MAP = {"SPX.US": "100.SPX", "HSI.HK": "100.HSI", "NDX.US": "100.NDX", "DJI.US": "100.DJI"}
# 已知纽交所股票（其余美股默认纳斯达克 105）
NYSE_SET = {"XOM", "TSM", "GLD", "BABA", "NIO", "PFE", "JPM", "JNJ", "WMT", "BAC", "DIS"}


def to_secid(symbol: str) -> str:
    """600519.SH→1.600519 / 000001.SZ→0.000001 / NVDA.US→105.NVDA / XOM.US→106.XOM / 0700.HK→116.00700"""
    if symbol in INDEX_MAP:
        return INDEX_MAP[symbol]
    if symbol.endswith(".SH"):
        return "1." + symbol[:-3]
    if symbol.endswith((".SZ", ".BJ")):
        return "0." + symbol[:-3]
    if symbol.endswith(".US"):
        code = symbol[:-3].upper()
        return ("106." if code in NYSE_SET else "105.") + code
    if symbol.endswith(".HK"):
        return "116." + symbol[:-3].zfill(5)
    # 期货/商品直接用
    return symbol


def normalize_symbol_for_em(symbol: str) -> str:
    """东财对美股要求大写无后缀，港股 5 位数字"""
    if symbol.endswith(".US"):
        return symbol[:-3].upper()
    if symbol.endswith(".HK"):
        return symbol[:-3].zfill(5)
    if symbol.endswith((".SH", ".SZ", ".BJ")):
        return symbol[:-3]
    return symbol


def fetch_kline(symbol: str, beg: str = "20250101", end: str = "20500101", klt: int = 101) -> list[dict]:
    """日 K 线，返回 [{date, open, close, high, low, volume, amount}]"""
    secid = to_secid(symbol)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt, "fqt": 1, "beg": beg, "end": end, "lmt": 1000,
    }
    r = _get(url, params=params)
    data = r.json().get("data")
    if not data or not data.get("klines"):
        log.warning("no kline for %s (%s)", symbol, secid)
        return []
    out = []
    for line in data["klines"]:
        p = line.split(",")
        out.append({
            "date": p[0], "open": float(p[1]), "close": float(p[2]),
            "high": float(p[3]), "low": float(p[4]),
            "volume": float(p[5]), "amount": float(p[6]),
        })
    return out


def fetch_spot(symbols: list[str]) -> dict[str, dict]:
    """实时行情批量，返回 {symbol: {price, pct_chg, name}}"""
    secids = ",".join(to_secid(s) for s in symbols)
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "secids": secids, "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields": "f2,f3,f4,f12,f14,f15,f16,f17,f18", "fltt": 2, "invt": 2,
    }
    r = _get(url, params=params)
    data = r.json().get("data", {}).get("diff", [])
    res = {}
    for d in data:
        secid = d.get("f12", "")
        res[secid] = {
            "price": d.get("f2"), "pct_chg": d.get("f3"),
            "open": d.get("f17"), "prev_close": d.get("f18"),
            "high": d.get("f15"), "low": d.get("f16"),
            "name": d.get("f14"),
        }
    # 映射回原始 symbol
    out = {}
    for s in symbols:
        key = normalize_symbol_for_em(s)
        if key in res:
            out[s] = res[key]
    return out


def fetch_btc() -> dict:
    """CoinGecko 比特币现价"""
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": "bitcoin", "vs_currencies": "usd,cny", "include_24hr_change": "true"}
    r = _get(url, params=params)
    d = r.json()["bitcoin"]
    return {"usd": d["usd"], "cny": d["cny"], "chg_24h": d.get("usd_24h_change", 0)}


def sync_kline_to_db(conn, symbol: str, beg: str = "20250101") -> int:
    rows = fetch_kline(symbol, beg=beg)
    for r in rows:
        upsert_price(conn, {"date": r["date"], "symbol": symbol, **r, "source": "eastmoney"})
    return len(rows)


_SINA_CODE = lambda s: (("sh" if s.endswith(".SH") else "sz") + s[:6]) if s[:6].isdigit() and s.endswith((".SH", ".SZ")) else None


def sina_close(symbol: str) -> float | None:
    """新浪备用接口：东财断连时取最新价/收盘价"""
    code = _SINA_CODE(symbol)
    if not code:
        return None
    try:
        r = _get("https://hq.sinajs.cn/list=" + code,
                 headers={"Referer": "https://finance.sina.com.cn"})
        import re
        m = re.search(r'="([^"]+)"', r.text)
        return float(m.group(1).split(",")[3]) if m else None
    except Exception:
        return None


def sync_with_fallback(conn, symbol: str, beg: str = "20250101") -> int:
    """东财优先，失败/无数据时用新浪补当天收盘价"""
    try:
        n = sync_kline_to_db(conn, symbol, beg)
        if n > 0:
            return n
    except Exception as e:
        log.warning("eastmoney sync %s failed: %s", symbol, e)
    px = sina_close(symbol)
    if px is not None:
        from core.db import today
        upsert_price(conn, {"date": today(), "symbol": symbol, "open": px, "high": px,
                            "low": px, "close": px, "volume": 0, "amount": 0, "source": "sina"})
        return 1
    return 0


# 常用标的速查
BENCHMARK = "000300.SH"  # 沪深300

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 测试
    print(json.dumps(fetch_spot(["600519.SH", "000300.SH", "NVDA.US", "0700.HK"]), ensure_ascii=False, indent=1))
    print(json.dumps(fetch_btc(), indent=1))
