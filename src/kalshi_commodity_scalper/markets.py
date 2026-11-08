"""Kalshi's public commodity market and order-book endpoints.

Only the contracts' own books are read; no external data feed is used.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

PUBLIC_REST = "https://api.elections.kalshi.com/trade-api/v2"

# asset key -> (display label, Kalshi series ticker)
SERIES: dict[str, tuple[str, str]] = {
    "gold":      ("Gold",      "KXGOLD15M"),
    "silver":    ("Silver",    "KXSILVER15M"),
    "wti":       ("WTI",       "KXWTI15M"),
    "brent":     ("Brent",     "KXBRENT15M"),
    "copper":    ("Copper",    "KXCOPPER15M"),
    "natgas":    ("NatGas",    "KXNATGAS15M"),
    "platinum":  ("Platinum",  "KXPLATINUM15M"),
    "palladium": ("Palladium", "KXPALLADIUM15M"),
}


def _get(path: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    url = f"{PUBLIC_REST}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "User-Agent": "kalshi-commodity-scalper/0.2",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _parse_ts(value: str) -> float:
    try:
        return dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _number(obj: dict, key: str, default: float = 0.0) -> float:
    """Read a possibly fractional or dollar-suffixed numeric field."""
    for name in (f"{key}_fp", key, f"{key}_dollars"):
        value = obj.get(name)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _price(obj: dict, key: str) -> float:
    """Read a YES price as dollars, preferring Kalshi's explicit dollars field.

    Older payloads publish cents as an integer; the dollars fields publish
    decimals. Normalising here keeps the strategy in 0..1 everywhere.
    """
    dollars = obj.get(f"{key}_dollars")
    if dollars is not None and dollars != "":
        try:
            return float(dollars)
        except (TypeError, ValueError):
            pass
    value = obj.get(key)
    if value is None or value == "":
        return -1.0
    try:
        price = float(value)
    except (TypeError, ValueError):
        return -1.0
    return price / 100.0 if price > 1.0 else price


def _size(obj: dict, key: str) -> float:
    for name in (f"{key}_fp", key):
        value = obj.get(name)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def live_market(asset: str, now: float) -> dict | None:
    """The open 15-minute contract for one asset, or None."""
    label, series = SERIES[asset]
    try:
        payload = _get("/markets", {
            "series_ticker": series, "status": "open", "limit": 10,
        })
    except Exception:
        return None

    best = None
    for market in payload.get("markets") or []:
        ticker = market.get("ticker") or ""
        strike = _number(market, "floor_strike")
        open_ts = _parse_ts(market.get("open_time", ""))
        close_ts = _parse_ts(market.get("close_time", ""))
        if not ticker or strike <= 0 or open_ts <= 0 or close_ts <= now:
            continue
        if open_ts > now:
            continue
        if close_ts <= open_ts or close_ts - open_ts > 1200:
            continue

        view = {
            "ticker": ticker,
            "asset": asset,
            "label": label,
            "strike": strike,
            "open_ts": open_ts,
            "close_ts": close_ts,
            "yes_bid": _price(market, "yes_bid"),
            "yes_ask": _price(market, "yes_ask"),
            "yes_bid_size": _size(market, "yes_bid_size"),
            "yes_ask_size": _size(market, "yes_ask_size"),
            "volume": _number(market, "volume"),
            "exchange_index": int(_number(market, "exchange_index")),
        }
        if best is None or view["close_ts"] < best["close_ts"]:
            best = view
    return best


def quote(ticker: str) -> dict | None:
    """Current YES bid/ask and sizes, or None if the book is not usable."""
    try:
        payload = _get(f"/markets/{ticker}", timeout=8.0)
    except Exception:
        return None
    market = payload.get("market") or payload
    bid = _price(market, "yes_bid")
    ask = _price(market, "yes_ask")
    if not (0.0 < bid < 1.0 and 0.0 < ask < 1.0 and bid <= ask):
        return None
    return {
        "yes_bid": bid,
        "yes_ask": ask,
        "yes_bid_size": _size(market, "yes_bid_size"),
        "yes_ask_size": _size(market, "yes_ask_size"),
    }


def settled_result(ticker: str) -> str | None:
    """`yes` or `no` after settlement, otherwise None."""
    try:
        payload = _get(f"/markets/{ticker}", timeout=8.0)
    except Exception:
        return None
    market = payload.get("market") or payload
    result = str(market.get("result") or "").lower()
    return result if result in ("yes", "no") else None
