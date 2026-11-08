# Kalshi Commodity Trend Bot

A small, commodities-only bot for Kalshi's 15-minute markets. It reads each
contract's own order book, waits until **five minutes** have passed, and enters
when the YES mid-price has moved at least **3 cents over the last 30 seconds**
in the configured direction; `up` buys YES at the ask, `down` buys NO at
`1 - YES bid`, and every position is held to settlement. There is no external
price feed and no dashboard.

The strategy is one JSON file of numbers, not a Python class or plugin.

## What it does

For each open commodity window the bot reads the public Kalshi book. It records
the YES mid every `poll_seconds`, then compares the current mid with the mid
`trend_seconds` earlier. Once `entry_after_seconds` has elapsed, a move of at
least `min_move_cents` in the chosen direction triggers an immediate-or-cancel
buy. Only one entry is allowed per market, and there is no sell logic: the
contract settles YES or NO and the ledger records the result.

This is a simple momentum/trend rule, not a claim of edge. The default numbers
are a starting point for experimentation.

## Install

The project uses `uv` and Python 3.12.

```bash
uv sync
```

Public market data and dry runs need no Kalshi account. Live orders need an API
key ID and private key file. Put them in `.env`:

```dotenv
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/your-private-key.pem
```

## Commands

```bash
uv run kalshi-scalper --report
uv run kalshi-scalper --dry-run --minutes 60
uv run kalshi-scalper --live --minutes 60
uv run kalshi-scalper --check-auth
```

- `--report` prints the current open markets and books, then exits without
  placing an order.
- `--dry-run` is the default when `--live` is omitted. It uses a separate dry
  ledger and never signs or sends an order.
- `--live` requires valid credentials and sends real IOC orders. Use it only
  after a dry run.
- `--minutes` stops the process after a fixed run time.
- `--balance 100` resets the dry ledger to a fresh `$100` cash balance. It is
  not allowed in live mode.
- `--assets gold,wti` overrides the asset list in the config for one run.
- `--config my-config.json` chooses another settings file.
- `--quiet` hides the 10-second `[watch]` lines but keeps entries, settlements,
  warnings, and the final summary.

## The one config file

Edit `config.json`. All prices are in cents; risk percentages are decimals.

| Setting | Default | Meaning |
|---|---:|---|
| `assets` | all eight commodities | Kalshi series to watch |
| `direction` | `"up"` | `up` buys YES; `down` buys NO |
| `entry_after_seconds` | `300` | wait 5 minutes from the window open |
| `trend_seconds` | `30` | lookback for the trend move |
| `min_move_cents` | `3.0` | minimum net mid-price move |
| `poll_seconds` | `2.0` | how often each book is read |
| `max_spread_cents` | `6.0` | skip books wider than this |
| `min_price_cents` | `30.0` | cheapest entry price allowed |
| `max_price_cents` | `70.0` | most expensive entry price allowed |
| `stop_entering_seconds_left` | `60` | no new entries near settlement |
| `max_contracts` | `10` | hard contract cap per entry |
| `risk_per_trade_pct` | `0.10` | per-trade cap as a share of cash |
| `risk_per_trade_abs` | `2.00` | per-trade cash cap in dollars |
| `max_concurrent` | `2` | maximum open positions |
| `daily_loss_pct` | `0.20` | stop trading after this daily loss |
| `daily_profit_pct` | `0.50` | stop trading after this daily gain |
| `max_consecutive_losses` | `3` | losses before a cooldown |
| `cooldown_after_loss_seconds` | `180` | stand-down after one loss |
| `cooldown_after_streak_seconds` | `1800` | stand-down after the streak |
| `asset_cooldown_seconds` | `300` | cooldown for an asset that lost |
| `starting_balance` | `100.0` | starting cash for a new dry ledger |

A move is measured as:

```text
up:   current_mid - mid_30_seconds_ago >= 3 cents
down: current_mid - mid_30_seconds_ago <= -3 cents
```

The chosen entry must also fit the price band and the book spread. A market
that the bot has not watched for the full lookback will not fire just because
the process started late in the window.

## Files and state

```text
config.json                         the numbers you edit
state.json                          live cash ledger and open trades
state.dry.json                      dry-run cash ledger and open trades
bot.log                             rotating process log
src/kalshi_commodity_scalper/
  bot.py                            CLI and the loop
  markets.py                        public Kalshi discovery and books
  strategy.py                       the trend entry rule
  ledger.py                         cash, sizing, risk stops, settlement
  broker.py                         signed live orders and wallet
  logs.py                           console and file logging
  settings.py                       config loading and validation
```

The saved balance is **cash**, not mark-to-market equity. An entry subtracts
its premium and fee immediately; a win adds its settlement payout. Open trades
are stored in the ledger and recovered after a restart. The live run reads the
Kalshi cash balance at startup so the ledger starts from the account's actual
cash.

## Scope and safety

- Commodities only.
- Every trade is a binary contract and can lose its full premium.
- Positions are held to settlement; there is no take-profit or stop-loss order.
- The bot refuses to run live without credentials and refuses to read a live
  wallet if the signed request fails.
- No dashboard or web server is started.
- Do not treat the default rule or any dry-run result as financial advice.
