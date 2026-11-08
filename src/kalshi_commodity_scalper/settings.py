"""Load the one JSON file that controls the bot.

The strategy has no Python classes or plugins. It is a small set of numbers in
`config.json`, validated here before the bot can place an order.
"""

from __future__ import annotations

import json
from pathlib import Path

from .markets import SERIES

WINDOW_SEC = 900

DEFAULTS: dict[str, object] = {
    "assets": list(SERIES),
    "direction": "up",
    "entry_after_seconds": 300,
    "trend_seconds": 30,
    "min_move_cents": 3.0,
    "poll_seconds": 2.0,
    "max_spread_cents": 6.0,
    "min_price_cents": 30.0,
    "max_price_cents": 70.0,
    "stop_entering_seconds_left": 60,
    "max_contracts": 10,
    "risk_per_trade_pct": 0.10,
    "risk_per_trade_abs": 2.00,
    "max_concurrent": 2,
    "daily_loss_pct": 0.20,
    "daily_profit_pct": 0.50,
    "max_consecutive_losses": 3,
    "cooldown_after_loss_seconds": 180,
    "cooldown_after_streak_seconds": 1800,
    "asset_cooldown_seconds": 300,
    "starting_balance": 100.0,
}

_NUMBERS: dict[str, tuple[float, float]] = {
    "entry_after_seconds": (0, WINDOW_SEC - 60),
    "trend_seconds": (5, 300),
    "min_move_cents": (0.1, 50.0),
    "poll_seconds": (0.25, 30.0),
    "max_spread_cents": (0.5, 99.0),
    "min_price_cents": (1.0, 99.0),
    "max_price_cents": (1.0, 99.0),
    "stop_entering_seconds_left": (0, 600),
    "max_contracts": (1, 10_000),
    "risk_per_trade_pct": (0.01, 1.0),
    "risk_per_trade_abs": (0.01, 100_000.0),
    "max_concurrent": (1, 50),
    "daily_loss_pct": (0.01, 1.0),
    "daily_profit_pct": (0.01, 10.0),
    "max_consecutive_losses": (1, 100),
    "cooldown_after_loss_seconds": (0, 86_400),
    "cooldown_after_streak_seconds": (0, 86_400),
    "asset_cooldown_seconds": (0, 86_400),
    "starting_balance": (0.01, 1_000_000_000.0),
}

_INTEGERS = {
    "entry_after_seconds", "trend_seconds", "stop_entering_seconds_left",
    "max_contracts", "max_concurrent", "max_consecutive_losses",
    "cooldown_after_loss_seconds", "cooldown_after_streak_seconds",
    "asset_cooldown_seconds",
}


def load(path: str | Path) -> dict:
    """Read and validate `config.json`; return a complete settings dictionary."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        raise ValueError(f"settings file not found: {p}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p}: JSON error on line {exc.lineno}: {exc.msg}") from None
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: the top level must be one JSON object")

    unknown = sorted(set(raw) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"{p}: unknown setting(s): {', '.join(unknown)}")

    cfg = {**DEFAULTS, **raw}
    direction = cfg.get("direction")
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")

    assets = cfg.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a non-empty list")
    clean_assets: list[str] = []
    for asset in assets:
        if not isinstance(asset, str) or asset not in SERIES:
            raise ValueError(f"unknown asset {asset!r}; known: {', '.join(SERIES)}")
        if asset not in clean_assets:
            clean_assets.append(asset)
    cfg["assets"] = clean_assets

    for key, (low, high) in _NUMBERS.items():
        value = cfg.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if not low <= float(value) <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        cfg[key] = int(value) if key in _INTEGERS else float(value)

    if cfg["min_price_cents"] >= cfg["max_price_cents"]:
        raise ValueError("min_price_cents must be smaller than max_price_cents")

    if (cfg["entry_after_seconds"] + cfg["trend_seconds"]
            >= WINDOW_SEC - cfg["stop_entering_seconds_left"]):
        raise ValueError(
            "entry_after_seconds + trend_seconds must leave time before "
            "stop_entering_seconds_left"
        )

    return cfg


def brief(cfg: dict) -> str:
    """A compact description for logs and --report."""
    return (
        f"direction={cfg['direction']} | after {cfg['entry_after_seconds']}s | "
        f"move {cfg['trend_seconds']}s/{cfg['min_move_cents']:.1f}c | "
        f"price {cfg['min_price_cents']:.0f}-{cfg['max_price_cents']:.0f}c | "
        f"spread <= {cfg['max_spread_cents']:.1f}c"
    )
