"""Cash ledger, position sizing, risk stops, and settlement accounting.

The ledger records cash, not mark-to-market equity. An entry subtracts its
premium and fee immediately; a win adds the settlement payout back. That makes
the saved balance match the Kalshi cash balance even while a position is open.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

FEE_RATE = 0.07
FEE_ROUND = 0.01


def kalshi_fee(count: int, price: float) -> float:
    """Kalshi taker fee, rounded up to the next whole cent."""
    if count <= 0 or price <= 0.0 or price >= 1.0:
        return 0.0
    raw = FEE_RATE * count * price * (1.0 - price)
    return math.ceil(round(raw / FEE_ROUND, 9)) * FEE_ROUND


def new(balance: float) -> dict:
    return {
        "balance": float(balance),
        "day": "",
        "day_start_balance": float(balance),
        "pnl_today": 0.0,
        "pnl_total": 0.0,
        "wins": 0,
        "losses": 0,
        "streak": 0,
        "trades": 0,
        "halted": False,
        "halt_reason": "",
        "cooldown_until": 0.0,
        "asset_cooldown": {},
        "open_trades": [],
    }


def load(path: str | Path, starting_balance: float) -> dict:
    """Load the ledger, or start one when the file does not exist yet."""
    ledger = new(starting_balance)
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return ledger
    if not isinstance(data, dict):
        return ledger

    for key in ("balance", "day_start_balance", "pnl_today", "pnl_total",
                "cooldown_until"):
        if isinstance(data.get(key), (int, float)) and not isinstance(data.get(key), bool):
            ledger[key] = float(data[key])
    for key in ("wins", "losses", "streak", "trades"):
        if isinstance(data.get(key), int) and not isinstance(data.get(key), bool):
            ledger[key] = data[key]
    if isinstance(data.get("day"), str):
        ledger["day"] = data["day"]
    ledger["halted"] = bool(data.get("halted"))
    ledger["halt_reason"] = str(data.get("halt_reason") or "")
    if isinstance(data.get("asset_cooldown"), dict):
        ledger["asset_cooldown"] = {
            str(k): float(v) for k, v in data["asset_cooldown"].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    if isinstance(data.get("open_trades"), list):
        ledger["open_trades"] = [
            t for t in data["open_trades"]
            if isinstance(t, dict) and t.get("ticker") and t.get("side") in ("yes", "no")
        ]
    return ledger


def save(path: str | Path, ledger: dict) -> None:
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True))
        tmp.replace(p)
    except OSError:
        pass


def roll_day(ledger: dict, now: float) -> None:
    today = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc).strftime("%Y-%m-%d")
    if ledger["day"] == today:
        return
    ledger["day"] = today
    ledger["day_start_balance"] = ledger["balance"]
    ledger["pnl_today"] = 0.0
    if ledger["halt_reason"].startswith("daily"):
        ledger["halted"] = False
        ledger["halt_reason"] = ""


def can_enter(ledger: dict, cfg: dict, now: float,
              open_positions: int, asset: str) -> tuple[bool, str]:
    """Risk gates that do not depend on the price."""
    roll_day(ledger, now)
    if ledger["halted"]:
        return False, f"halted: {ledger['halt_reason']}"
    if now < ledger["cooldown_until"]:
        return False, f"cooldown {int(ledger['cooldown_until'] - now)}s"
    until = ledger["asset_cooldown"].get(asset, 0.0)
    if now < until:
        return False, f"{asset} cooldown {int(until - now)}s"
    if open_positions >= cfg["max_concurrent"]:
        return False, f"max concurrent positions ({open_positions})"
    return True, ""


def size_position(ledger: dict, cfg: dict, price: float,
                  book_size: float | None) -> int:
    """Largest whole-contract order that fits the per-trade cash cap."""
    if price <= 0:
        return 0
    budget = min(
        ledger["balance"] * cfg["risk_per_trade_pct"],
        cfg["risk_per_trade_abs"],
        ledger["balance"],
    )
    if budget <= 0:
        return 0

    contracts = 0
    while contracts < cfg["max_contracts"]:
        nxt = contracts + 1
        cost = nxt * price + kalshi_fee(nxt, price)
        if cost > budget:
            break
        contracts = nxt

    if book_size is not None and book_size > 0:
        contracts = min(contracts, int(book_size))
    if contracts * price + kalshi_fee(contracts, price) > ledger["balance"]:
        return 0
    return contracts


def record_entry(ledger: dict, trade: dict) -> None:
    """Take the cash out for an entry and remember it for restart recovery."""
    ledger["balance"] -= trade["cost"]
    ledger["open_trades"].append(trade)


def record_result(ledger: dict, cfg: dict, trade: dict, won: bool,
                  now: float) -> float:
    """Apply a settlement. Returns the realised P&L."""
    payout = float(trade["contracts"]) if won else 0.0
    pnl = payout - trade["cost"]
    ledger["balance"] += payout
    ledger["pnl_today"] += pnl
    ledger["pnl_total"] += pnl
    ledger["trades"] += 1

    if won:
        ledger["wins"] += 1
        ledger["streak"] = 0
        ledger["asset_cooldown"].pop(trade["asset"], None)
    else:
        ledger["losses"] += 1
        ledger["streak"] += 1
        ledger["asset_cooldown"][trade["asset"]] = now + cfg["asset_cooldown_seconds"]
        if ledger["streak"] >= cfg["max_consecutive_losses"]:
            ledger["cooldown_until"] = now + cfg["cooldown_after_streak_seconds"]
            ledger["streak"] = 0
        else:
            ledger["cooldown_until"] = max(
                ledger["cooldown_until"], now + cfg["cooldown_after_loss_seconds"]
            )

    ledger["open_trades"] = [
        t for t in ledger["open_trades"] if t.get("ticker") != trade["ticker"]
    ]
    _daily_stops(ledger, cfg)
    return pnl


def _daily_stops(ledger: dict, cfg: dict) -> None:
    start = ledger["day_start_balance"]
    if start <= 0:
        return
    loss_limit = -start * cfg["daily_loss_pct"]
    profit_limit = start * cfg["daily_profit_pct"]
    if ledger["pnl_today"] <= loss_limit:
        ledger["halted"] = True
        ledger["halt_reason"] = f"daily loss {ledger['pnl_today']:+.2f}"
    elif ledger["pnl_today"] >= profit_limit:
        ledger["halted"] = True
        ledger["halt_reason"] = f"daily profit {ledger['pnl_today']:+.2f}"


def win_rate(ledger: dict) -> float:
    n = ledger["wins"] + ledger["losses"]
    return ledger["wins"] / n if n else 0.0


def report(ledger: dict, cfg: dict) -> str:
    return "\n".join([
        f"  cash            ${ledger['balance']:,.2f}",
        f"  per trade       {cfg['risk_per_trade_pct']:.0%} of cash, "
        f"max ${cfg['risk_per_trade_abs']:,.2f}",
        f"  concurrent      {cfg['max_concurrent']} positions",
        f"  daily stop      -{cfg['daily_loss_pct']:.0%} / "
        f"+{cfg['daily_profit_pct']:.0%} of the day's opening cash",
        f"  losses          {cfg['max_consecutive_losses']} in a row -> "
        f"{cfg['cooldown_after_streak_seconds']}s stand-down",
        f"  asset cooldown  {cfg['asset_cooldown_seconds']}s after a loss",
        f"  today           {ledger['pnl_today']:+.2f} | total "
        f"{ledger['pnl_total']:+.2f} | {ledger['wins']}W-{ledger['losses']}L "
        f"({win_rate(ledger):.0%})",
        f"  open trades     {len(ledger['open_trades'])}",
    ])
