"""Kalshi live trading: request signing, wallet lookup, and IOC buys.

Orders are YES-referenced on the wire, so buying NO is sent as an ask at
`1 - price`. Dry runs never import `cryptography` or call this module.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from .logs import log, tick

TRADE_REST = "https://external-api.kalshi.com/trade-api/v2"


def credentials_present() -> bool:
    return bool(os.getenv("KALSHI_API_KEY_ID") and os.getenv("KALSHI_PRIVATE_KEY_PATH"))


def _headers(method: str, path: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key_id = os.getenv("KALSHI_API_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    if not key_id or not key_path:
        raise ValueError("missing KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH")

    with open(os.path.expanduser(key_path), "rb") as key_file:
        key = load_pem_private_key(key_file.read(), password=None)

    timestamp = str(int(time.time() * 1000))
    message = (timestamp + method + path).encode("utf-8")
    if isinstance(key, Ed25519PrivateKey):
        signature = key.sign(message)
    else:
        signature = key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }


def to_wire(side: str, price: float) -> tuple[str, float]:
    """Buy `side` at `price` -> YES-referenced (wire side, wire price)."""
    return ("bid", price) if side == "yes" else ("ask", 1.0 - price)


def wallet_balance() -> float | None:
    """Cash balance in dollars, or None if the signed request fails."""
    path = "/trade-api/v2/portfolio/balance"
    try:
        headers = _headers("GET", path)
    except Exception as exc:
        log(f"[auth] could not sign the wallet request: {exc}")
        return None

    request = urllib.request.Request(f"{TRADE_REST}/portfolio/balance", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:200]
        log(f"[auth] wallet request rejected: HTTP {exc.code} {detail}")
        return None
    except Exception as exc:
        log(f"[auth] wallet request failed: {exc}")
        return None

    if data.get("balance_dollars") is not None:
        return float(data["balance_dollars"])
    return float(data.get("balance", 0) or 0) / 100.0


def buy(ticker: str, side: str, price: float, count: int,
        exchange_index: int = 0) -> dict | None:
    """IOC limit buy. Returns `{filled, avg_price}` or a `dead` marker."""
    if count <= 0:
        return None
    wire_side, wire_price = to_wire(side, price)
    path = "/trade-api/v2/portfolio/events/orders"
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": wire_side,
        "count": f"{count}.00",
        "price": f"{wire_price:.4f}",
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": False,
        "reduce_only": False,
        "subaccount": 0,
        "exchange_index": exchange_index,
    }

    try:
        headers = _headers("POST", path)
    except Exception as exc:
        log(f"[order] signing failed: {exc}")
        return None
    headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{TRADE_REST}/portfolio/events/orders",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        if exc.code == 404 or "market_not_found" in detail:
            return {"dead": True}
        log(f"[order] {ticker}: HTTP {exc.code} {detail}")
        return None
    except Exception as exc:
        log(f"[order] {ticker}: {exc}")
        return None

    filled = int(float(data.get("fill_count", 0) or 0))
    if filled <= 0:
        tick(f"[order] {ticker}: BUY {side.upper()} {count} @ ${price:.2f} did not fill.")
        return None

    wire_average = data.get("average_fill_price_dollars")
    if wire_average is None:
        wire_average = data.get("average_fill_price")
    if wire_average is None:
        wire_average = wire_price
    wire_average = float(wire_average)
    if wire_average > 1.0:
        wire_average /= 100.0
    side_price = wire_average if side == "yes" else 1.0 - wire_average
    return {"filled": filled, "avg_price": round(side_price, 4)}
