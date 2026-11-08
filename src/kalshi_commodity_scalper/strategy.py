"""The only strategy: a net move in the contract's own book.

There is no model, class, or plugin here. At or after
`entry_after_seconds` seconds into the 15-minute window, compare the current
YES mid to the mid `trend_seconds` ago. If the configured direction moved by at
least `min_move_cents`, buy that side and hold to settlement.
"""

from __future__ import annotations


def trend_baseline(history: list[tuple[float, float]], now: float,
                   seconds: float) -> tuple[float, float] | None:
    """The newest sample that is at least `seconds` old.

    `history` is ordered oldest -> newest. Using the newest qualifying sample
    keeps the lookback close to the requested window instead of accidentally
    measuring the whole run.
    """
    baseline = None
    for ts, mid in history:
        if now - ts >= seconds:
            baseline = (ts, mid)
        else:
            break
    return baseline


def entry_signal(market: dict, history: list[tuple[float, float]],
                 cfg: dict, now: float) -> dict | None:
    """Return an entry decision, or None if the rule is not satisfied.

    `up` buys YES at the YES ask. `down` buys NO at `1 - YES bid`.
    """
    elapsed = now - market["open_ts"]
    if elapsed < cfg["entry_after_seconds"]:
        return None
    if market["close_ts"] - now < cfg["stop_entering_seconds_left"]:
        return None

    bid, ask = market["yes_bid"], market["yes_ask"]
    if not (0.0 < bid < 1.0 and 0.0 < ask < 1.0 and bid <= ask):
        return None
    spread = ask - bid
    if spread > cfg["max_spread_cents"] / 100.0:
        return None

    baseline = trend_baseline(history, now, cfg["trend_seconds"])
    if baseline is None:
        return None
    base_ts, base_mid = baseline
    mid = (bid + ask) / 2.0
    change = mid - base_mid
    needed = cfg["min_move_cents"] / 100.0

    if cfg["direction"] == "up":
        if change < needed:
            return None
        side, entry = "yes", ask
    else:
        if change > -needed:
            return None
        side, entry = "no", 1.0 - bid

    if not (cfg["min_price_cents"] / 100.0
            <= entry <= cfg["max_price_cents"] / 100.0):
        return None

    return {
        "side": side,
        "entry": round(entry, 4),
        "mid": round(mid, 4),
        "base_mid": round(base_mid, 4),
        "change": round(change, 4),
        "trend_seconds": round(now - base_ts, 1),
        "spread": round(spread, 4),
        "elapsed": round(elapsed, 1),
    }
