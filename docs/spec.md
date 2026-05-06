# AI Trading Agent — V1 Spec

Status: Draft · Branch: `claude/ai-trading-agent-design-UwA6e`

## 1. Goal

A daily-loop agent that, for a curated watchlist of US equities, proposes
buy / sell / trim actions with limit and stop levels. Proposals are pushed to
Telegram for human approval; approved orders are placed via the Trading 212
API. The user retains the authorisation gate on every order.

## 2. Non-goals (V1)

- Intraday or HFT trading. Daily cadence only.
- Crypto execution (deferred to phase 2 — Revolut has no retail API).
- Options, futures, leveraged products.
- Fully autonomous trading. Every order requires explicit human approval.
- Predictive price targets framed as forecasts. The agent ranks candidates
  and synthesises evidence; it does not claim to predict prices.

## 3. Phases

| Phase | Scope |
|---|---|
| **V1** | US equities, T212 paper account, free-tier data, ~30-name watchlist, daily digest, Telegram approval, backtest harness |
| **V1.1** | Move to T212 live account once paper results are validated |
| **V2** | Add crypto. Decide between (a) Revolut signals-only or (b) Coinbase/Kraken full automation |
| **V2.1** | Intraday signals, paid data tier (Polygon/Tiingo) if edge justifies cost |

## 4. Architecture

```
┌──────────────────────────────────────────────────────┐
│  Data ingestion (cron: daily 06:30 UTC)              │
│  yfinance · Finnhub free · EDGAR · FRED · news feed  │
└──────────────────┬───────────────────────────────────┘
                   ▼
            ┌──────────────┐
            │ SQLite DB    │  bars · fundamentals · news · proposals · orders
            └──────┬───────┘
                   ▼
       ┌────────────────────────┐
       │ Feature pipeline       │  pandas-ta indicators · regime tag · ATR
       └───────────┬────────────┘
                   ▼
       ┌────────────────────────┐
       │ Claude agent (tool use)│  reads portfolio + features + news
       │ → ranked proposals     │  buy/sell, limit, stop, size, rationale
       └───────────┬────────────┘
                   ▼
       ┌────────────────────────┐
       │ Telegram bot           │  inline buttons: Approve · Edit · Reject
       └───────────┬────────────┘
                   ▼ (on approve)
       ┌────────────────────────┐
       │ T212 order placement   │  limit / stop_limit orders
       └────────────────────────┘
```

## 5. Components

| Component | Tech | Notes |
|---|---|---|
| Language | Python 3.11+ | Mature ecosystem for finance tooling |
| Broker SDK | Direct REST to T212 | No mature SDK; thin wrapper is fine |
| Market data | `yfinance`, `finnhub-python` (free), `sec-edgar-api`, `fredapi` | All free tier |
| Indicators | `pandas-ta` | Avoid TA-Lib's C dependency |
| Backtest | `vectorbt` | Fast, vectorised, good portfolio support |
| Agent | `anthropic` SDK, Claude Sonnet 4.6 | Tool-use for portfolio/quote/news lookup |
| Bot | `python-telegram-bot` v21+ | Webhook mode |
| Scheduler | `APScheduler` | In-process cron for the daily loop |
| Storage | SQLite via `sqlmodel` | One file, easy backup |
| Deploy | Single VPS or local container | No HA needed in V1 |

## 6. Data sources (all free tier)

- **yfinance** — daily OHLCV, splits, dividends. Primary.
- **Stooq** or **Finnhub free** — backup OHLCV adapter; switch on yfinance failure.
- **Finnhub free** — earnings calendar, analyst recommendations, basic news.
- **SEC EDGAR** — 10-K, 10-Q, 8-K filings for fundamentals & event drift.
- **FRED** — macro series (rates, CPI, unemployment) for regime context.
- **NewsAPI free** or **Marketaux free** — headlines for the LLM to synthesise.

Adapter pattern: every data source implements `DataSource` interface so we can
swap to paid providers later without touching downstream code.

## 7. Universe

- **Holdings list:** every position currently held in T212. Auto-synced.
- **Candidate watchlist:** ~30 names, manually curated, stored in
  `config/watchlist.yml`. Edited by hand. Mix of mega-caps you follow plus
  thematic plays.
- **Future layer:** weekly screener proposes new candidates for promotion
  into the watchlist; you approve before they become eligible.

## 8. Signal stack

Three layers, fed to Claude as numeric context — none are auto-traded:

1. **Technicals (deterministic):** SMA 50/200, EMA 20, RSI 14, MACD, Bollinger
   bands, ATR 14 (for stop sizing), ADX (trend strength), volume vs 20-day avg.
2. **Regime tag per ticker:** trending up / trending down / ranging / breakout,
   from price-vs-200DMA + ADX threshold.
3. **Narrative synthesis (LLM):** Claude reads recent news + earnings calendar
   + technicals + regime, produces:
   - thesis (one paragraph)
   - confidence label (low / medium / high)
   - upside / downside scenarios
   - proposed action with limit & stop

## 9. Risk rails (hard limits, enforced in code, not by the LLM)

- **Position sizing:** max 5% of equity per single position.
- **Stop placement:** ATR-based; default 2× ATR(14) below entry. Never wider
  than 8% of entry.
- **Daily turnover cap:** max 20% of equity traded per day.
- **Concentration cap:** max 30% in any single sector.
- **Cooldown:** no re-entry into a stopped-out name for 5 trading days.
- **Tax-loss-harvesting block:** no sell of a name held <30 days for ISA accounts.
- **Kill switch:** Telegram command `/halt` blocks all new order placement.

## 10. Approval flow

1. **06:30 UTC daily**: data ingestion, feature pipeline, agent run.
2. Agent emits N proposals (typically 0–5).
3. Telegram digest message sent: portfolio P&L summary + per-proposal cards
   with inline buttons.
4. **Per proposal:** ✅ Approve · ✏️ Edit (price/size) · ❌ Reject · ⏭ Defer.
5. Approval triggers immediate order placement via T212 API.
6. **Staleness guard:** proposals expire after 60 minutes. Approving an
   expired proposal triggers a re-price prompt.
7. **Fills & stops:** intraday monitor sends Telegram updates on fills,
   stop triggers, and end-of-day summary at 21:30 UTC.

## 11. Backtest harness (built first)

- Load historical bars for the watchlist, 5+ years.
- Replay daily bar-by-bar, run feature pipeline + Claude proposal generator.
- Apply risk rails as code. Simulate fills at next-day open with realistic
  slippage assumption (e.g. 5 bps).
- Output: equity curve, max drawdown, win rate, Sharpe, per-trade ledger.
- **Gate:** no live wiring until backtest shows non-trivial edge over
  buy-and-hold SPY on the same names.

## 12. Milestones

| # | Deliverable | Acceptance |
|---|---|---|
| M0 | Repo scaffold, config, data adapters | yfinance, Finnhub, EDGAR, FRED working |
| M1 | Feature pipeline + watchlist load | Indicators computed for full watchlist on demand |
| M2 | Backtest harness w/ deterministic strategy | Equity curve produced for SMA-cross baseline |
| M3 | Claude agent integration | Proposals generated for backtest dates |
| M4 | Backtest with LLM proposals | Reports vs SPY benchmark |
| M5 | T212 paper integration | Read portfolio, place demo orders |
| M6 | Telegram bot + approval flow | End-to-end demo on paper account |
| M7 | Risk rails + kill switch | All limits enforced, /halt works |
| M8 | One-week paper run | Daily digests, approvals, fills logged |
| M9 | Go-live decision point | User reviews paper results, decides on live |

## 13. Open questions

- T212 account type (cash / ISA / invest)? Affects tax-loss rules.
- Telegram chat: 1:1 with bot, or a private channel?
- LLM cost ceiling per day?
- Where does this run — local machine, VPS, container?
- Secrets management approach (env file, 1Password, etc.)?
