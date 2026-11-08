#!/usr/bin/env python3
"""Small Kalshi commodities trend bot.

    uv run kalshi-scalper --report
    uv run kalshi-scalper --dry-run --minutes 60
    uv run kalshi-scalper --live --minutes 60

The loop is one file and one strategy: wait for the configured time, compare
the contract's current YES mid with its mid `trend_seconds` ago, buy the chosen
side if the move is large enough, and hold to settlement.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import broker, ledger, logs, markets, settings
from .strategy import entry_signal, trend_baseline

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.json"
LIVE_STATE = ROOT / "state.json"
DRY_STATE = ROOT / "state.dry.json"
LOG_FILE = ROOT / "bot.log"
DISCOVERY_SEC = 30.0
STATUS_SEC = 10.0


def load_env() -> None:
    """Read `.env`; real environment variables always win."""
    try:
        lines = (ROOT / ".env").read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kalshi commodities book-trend bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="settings JSON file")
    parser.add_argument("--assets",
                        help="comma-separated subset of assets (overrides config)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="simulate and use the dry-run ledger")
    mode.add_argument("--live", action="store_true",
                      help="send real orders; confirms live trading")
    parser.add_argument("--balance", type=float, default=None,
                        help="reset the dry ledger to this cash balance")
    parser.add_argument("--minutes", type=float, default=None,
                        help="stop after this many minutes")
    parser.add_argument("--report", action="store_true",
                        help="show settings and current books, then exit")
    parser.add_argument("--check-auth", action="store_true",
                        help="verify the Kalshi key and wallet, then exit")
    parser.add_argument("--quiet", action="store_true",
                        help="hide 10-second watching lines")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    load_env()
    try:
        cfg = settings.load(args.config)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    if args.assets:
        keys = [key.strip() for key in args.assets.split(",") if key.strip()]
        unknown = [key for key in keys if key not in markets.SERIES]
        if unknown:
            print(f"[error] unknown asset(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        cfg["assets"] = list(dict.fromkeys(keys))

    logs.setup(LOG_FILE, quiet=args.quiet)

    if args.report:
        return report(cfg)
    if args.check_auth:
        return check_auth()
    if args.live and args.balance is not None:
        print("[error] --balance is only for dry runs; live uses the Kalshi wallet",
              file=sys.stderr)
        return 2
    if args.live and not broker.credentials_present():
        print("[error] live mode needs KALSHI_API_KEY_ID and "
              "KALSHI_PRIVATE_KEY_PATH in .env", file=sys.stderr)
        return 2

    state_path = LIVE_STATE if args.live else DRY_STATE
    if args.balance is not None:
        state = ledger.new(args.balance)
        ledger.save(state_path, state)
        logs.log(f"Fresh dry ledger at ${args.balance:,.2f}.")
    else:
        state = ledger.load(state_path, cfg["starting_balance"])

    if args.live:
        cash = broker.wallet_balance()
        if cash is None:
            print("[error] could not read the Kalshi wallet; refusing to trade",
                  file=sys.stderr)
            return 2
        state["balance"] = cash
        ledger.roll_day(state, time.time())
        logs.log(f"Live Kalshi cash: ${cash:,.2f}.")

    run(cfg, state, state_path, live=args.live, minutes=args.minutes)
    return 0


def report(cfg: dict) -> int:
    now = time.time()
    logs.log("=" * 72)
    logs.log("KALSHI COMMODITY TREND | settings")
    logs.log(f"  {settings.brief(cfg)}")
    logs.log(f"  assets: {', '.join(cfg['assets'])}")
    logs.log("=" * 72)
    for asset in cfg["assets"]:
        label = markets.SERIES[asset][0]
        view = markets.live_market(asset, now)
        if view is None:
            logs.log(f"  {label:<9} no open 15-minute market")
            continue
        book = markets.quote(view["ticker"])
        if book is None:
            logs.log(f"  {label:<9} {view['ticker']}  no usable book")
            continue
        mid = (book["yes_bid"] + book["yes_ask"]) / 2.0
        logs.log(
            f"  {label:<9} yes {book['yes_bid']:.2f}/{book['yes_ask']:.2f} "
            f"mid {mid:.3f} | {now - view['open_ts']:.0f}s in | "
            f"{view['close_ts'] - now:.0f}s left | {view['ticker']}"
        )
    logs.log("No orders were placed.")
    return 0


def check_auth() -> int:
    if not broker.credentials_present():
        print("[error] KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH are not set",
              file=sys.stderr)
        return 2
    cash = broker.wallet_balance()
    if cash is None:
        print("[error] signed wallet request failed", file=sys.stderr)
        return 2
    logs.log(f"Credentials work. Kalshi cash: ${cash:,.2f}")
    return 0


def discover(assets: list[str], previous: dict, now: float) -> dict:
    """Refresh open markets, keeping a still-open previous view on a failed call."""
    found = {}
    for asset in assets:
        view = markets.live_market(asset, now)
        if view is None:
            old = previous.get(asset)
            if old is not None and old["close_ts"] > now:
                view = old
        if view is not None:
            found[asset] = view
    return found


def run(cfg: dict, state: dict, state_path: Path, live: bool,
        minutes: float | None) -> None:
    now = time.time()
    ledger.roll_day(state, now)
    mode = "LIVE" if live else "DRY RUN"
    logs.log("=" * 72)
    logs.log(f"KALSHI COMMODITY TREND | {mode}")
    logs.log(f"  {settings.brief(cfg)}")
    logs.log(f"  assets: {', '.join(cfg['assets'])}")
    logs.log(ledger.report(state, cfg))
    logs.log("=" * 72)

    positions = {
        trade["ticker"]: trade for trade in state["open_trades"]
        if trade.get("ticker")
    }
    if positions:
        logs.log(f"Recovered {len(positions)} open trade(s) from the ledger.")

    now = time.time()
    deadline = now + minutes * 60 if minutes and minutes > 0 else None
    active: dict[str, dict] = {}
    histories: dict[str, list[tuple[float, float]]] = {}
    last_quote: dict[str, float] = {}
    last_status: dict[str, float] = {}
    last_settle: dict[str, float] = {}
    attempted: set[str] = set()
    dead: set[str] = set()
    skipped: set[str] = set()
    warned: set[str] = set()
    last_discovery = 0.0

    try:
        while True:
            now = time.time()
            if now - last_discovery >= DISCOVERY_SEC:
                active = discover(cfg["assets"], active, now)
                last_discovery = now
                live_tickers = {view["ticker"] for view in active.values()}
                for ticker in list(histories):
                    if ticker not in live_tickers:
                        del histories[ticker]

            # Settle positions whose market has closed.
            for ticker, trade in list(positions.items()):
                if now < trade["close_ts"] + 1:
                    continue
                if now - last_settle.get(ticker, 0.0) < 3.0:
                    continue
                last_settle[ticker] = now
                result = markets.settled_result(ticker)
                if result is None:
                    if now - trade["close_ts"] > 900 and ticker not in warned:
                        logs.log(f"[wait] {ticker} is still unsettled; keeping it open.")
                        warned.add(ticker)
                    continue
                won = result == trade["side"]
                pnl = ledger.record_result(state, cfg, trade, won, now)
                del positions[ticker]
                ledger.save(state_path, state)
                mark = "WIN " if won else "LOSS"
                logs.log(
                    f"[{mark}] {trade['asset']} {trade['side'].upper()} "
                    f"{trade['contracts']}x @ ${trade['entry']:.3f} -> "
                    f"{result.upper()} | P&L {pnl:+.2f} | cash ${state['balance']:.2f}"
                )

            # Watch the books and enter at most once per market.
            for asset in cfg["assets"]:
                view = active.get(asset)
                if view is None:
                    continue
                ticker = view["ticker"]
                if ticker in dead:
                    continue
                if now - last_quote.get(asset, 0.0) < cfg["poll_seconds"]:
                    continue
                last_quote[asset] = now

                book = markets.quote(ticker)
                if book is None:
                    continue
                bid = book["yes_bid"]
                ask = book["yes_ask"]
                mid = (bid + ask) / 2.0
                history = histories.setdefault(ticker, [])
                history.append((now, mid))
                cutoff = now - (cfg["trend_seconds"] + max(5.0, cfg["poll_seconds"] * 2))
                histories[ticker] = [point for point in history if point[0] >= cutoff]
                history = histories[ticker]

                if now - last_status.get(asset, 0.0) >= STATUS_SEC:
                    baseline = trend_baseline(history, now, cfg["trend_seconds"])
                    change = (mid - baseline[1]) if baseline else 0.0
                    held = "holding" if ticker in positions else "watching"
                    logs.tick(
                        f"[watch] {view['label']:<9} yes {bid:.2f}/{ask:.2f} "
                        f"mid {mid:.3f} | {cfg['trend_seconds']}s "
                        f"{change:+.1f}c | {now - view['open_ts']:.0f}s in | "
                        f"{view['close_ts'] - now:.0f}s left | {held}"
                    )
                    last_status[asset] = now

                if ticker in positions or ticker in attempted:
                    continue
                signal = entry_signal(
                    {**view, "yes_bid": bid, "yes_ask": ask},
                    history, cfg, now,
                )
                if signal is None:
                    continue

                can_trade, reason = ledger.can_enter(
                    state, cfg, now, len(positions), asset
                )
                if not can_trade:
                    key = f"{ticker}:{reason}"
                    if key not in skipped:
                        logs.tick(f"[skip] {view['label']}: {reason}")
                        skipped.add(key)
                    continue

                count = ledger.size_position(
                    state, cfg, signal["entry"],
                    book["yes_bid_size"] if signal["side"] == "no"
                    else book["yes_ask_size"],
                )
                if count <= 0:
                    key = f"{ticker}:size"
                    if key not in skipped:
                        logs.tick(
                            f"[skip] {view['label']}: no size inside the "
                            f"per-trade cap"
                        )
                        skipped.add(key)
                    continue

                attempted.add(ticker)
                if live:
                    fill = broker.buy(
                        ticker, signal["side"], signal["entry"], count,
                        exchange_index=view["exchange_index"],
                    )
                    if fill and fill.get("dead"):
                        dead.add(ticker)
                        logs.log(f"[closed] {view['label']}: market disappeared "
                                 f"before the order landed.")
                        continue
                    if not fill:
                        logs.log(f"[miss] {view['label']}: order did not fill.")
                        continue
                    entry = fill["avg_price"]
                    count = fill["filled"]
                else:
                    entry = signal["entry"]

                fee = ledger.kalshi_fee(count, entry)
                cost = count * entry + fee
                if cost > state["balance"]:
                    logs.log("[skip] the fill cost more than the remaining cash.")
                    continue

                trade = {
                    "ticker": ticker,
                    "asset": asset,
                    "side": signal["side"],
                    "entry": round(entry, 4),
                    "contracts": count,
                    "cost": round(cost, 4),
                    "opened_at": now,
                    "close_ts": view["close_ts"],
                    "dry_run": not live,
                }
                ledger.record_entry(state, trade)
                positions[ticker] = trade
                ledger.save(state_path, state)
                logs.log(
                    f"[ENTRY] {view['label']} {signal['side'].upper()} "
                    f"{count}x @ ${entry:.3f} (${cost:.2f} cost) | "
                    f"mid {signal['base_mid']:.3f} -> {signal['mid']:.3f} "
                    f"({signal['change']:+.3f} over {signal['trend_seconds']:.0f}s) "
                    f"| {view['close_ts'] - now:.0f}s left"
                )

            if deadline is not None and now >= deadline:
                logs.log("[stop] Run window elapsed.")
                break
            if state["halted"]:
                logs.log(f"[stop] {state['halt_reason']}")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        logs.log("[stop] Interrupted.")
    finally:
        state["open_trades"] = list(positions.values())
        ledger.save(state_path, state)
        logs.log("=" * 72)
        logs.log(
            f"FINAL | cash ${state['balance']:.2f} | today "
            f"{state['pnl_today']:+.2f} | total {state['pnl_total']:+.2f} | "
            f"{state['wins']}W-{state['losses']}L | "
            f"{ledger.win_rate(state):.0%} win rate"
        )
        logs.log("=" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
