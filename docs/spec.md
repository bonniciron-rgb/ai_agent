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

Three managed services, no always-on box:

```
┌────────────────────────────────────────────────────────────────┐
│  GitHub Actions — daily cron 06:30 UTC + intraday poll 5-15min │
│  · ingest data (yfinance · Finnhub · EDGAR · FRED · news)      │
│  · run feature pipeline (pandas-ta indicators)                 │
│  · invoke Claude agent → proposals                             │
│  · push digest to Telegram                                     │
└──────────────────┬─────────────────────────────────────────────┘
                   │ writes / reads
                   ▼
            ┌──────────────────┐
            │ Neon Postgres    │  bars · proposals · orders · audit log
            └──────────────────┘
                   ▲
                   │ reads / writes
┌──────────────────┴─────────────────────────────────────────────┐
│  Vercel serverless functions                                   │
│  · POST /telegram/webhook  ← Telegram approval taps            │
│  · POST /t212/proxy        ← signed exec relay (phase 2 only)  │
│  · GET  /healthz                                               │
└──────────────────┬─────────────────────────────────────────────┘
                   │ on approve
                   ▼
            ┌──────────────────┐
            │ Trading 212 API  │  limit / stop_limit orders
            └──────────────────┘
```

State is in Neon (Postgres). Each GitHub Actions run is stateless and
short-lived. Vercel functions are stateless. Nothing is "always on" except
the managed DB.

## 5. Components

| Component | Tech | Notes |
|---|---|---|
| Language | Python 3.11+ | Mature ecosystem for finance tooling |
| Broker SDK | Direct REST to T212 | No mature SDK; thin wrapper is fine |
| Market data | `yfinance`, `finnhub-python` (free), `sec-edgar-api`, `fredapi` | All free tier |
| Indicators | `pandas-ta` | Avoid TA-Lib's C dependency |
| Backtest | `vectorbt` | Fast, vectorised, good portfolio support |
| Agent | `anthropic` SDK, Claude Sonnet 4.6 | Tool-use for portfolio/quote/news lookup |
| Bot | `python-telegram-bot` v21+ on Vercel functions | Webhook mode (Vercel-hosted endpoint) |
| Scheduler | GitHub Actions cron | No always-on host needed |
| Storage | Postgres via `sqlmodel` (async) on **Neon free tier** | 512MB; well within V1 budget |
| Compute (cron) | GitHub Actions runners | ~1500 min/month projected use; under free 2000 limit |
| Compute (webhooks) | Vercel serverless functions (Python runtime) | scales to zero |
| Secrets | GitHub Actions secrets · Vercel env vars · Neon connection string | encrypted at rest |
| Cost | **£0/month at V1 volume** | upgrade triggers in §15 |

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
| M0 | Repo scaffold, config, data adapters | yfinance, Finnhub, EDGAR, FRED working; CI lint+test green |
| M1 | Feature pipeline + watchlist load | Indicators computed for full watchlist on demand |
| M2 | Backtest harness w/ deterministic strategy | Equity curve produced for SMA-cross baseline |
| M3 | Claude agent integration | Proposals generated for backtest dates |
| M4 | Backtest with LLM proposals | Reports vs SPY benchmark |
| M5 | T212 paper integration | Read portfolio, place demo orders |
| M6 | Telegram bot + approval flow on Vercel | End-to-end demo on paper account |
| M7 | Risk rails + kill switch | All limits enforced, /halt works |
| M7.5 | GitHub Actions cron + Neon DB wiring | Daily run executes end-to-end on schedule |
| M8 | One-week paper run | Daily digests, approvals, fills logged |
| M9 | Go-live decision point | User reviews paper results, decides on live |

## 13. Decisions (resolved)

| # | Decision |
|---|---|
| Account type | **T212 ISA** (Invest as fallback if annual allowance is exhausted; tax-aware sell rail in §9 covers both) |
| Telegram surface | **Private group containing user + bot** (upgradeable to multi-approver later) |
| LLM cost cap | **$3/day hard cap, $2/day alert.** Tracked in DB, refuses calls on breach, posts Telegram alert |
| Hosting | **GitHub Actions (cron) + Vercel (webhooks) + Neon Postgres (state).** £0/month at V1 volume |
| Secrets | **GitHub Actions secrets + Vercel env vars** for runtime keys; T212 key kept short-rotation, no host IP allowlist available on this stack |

## 14. Stack-specific risks & mitigations

| Risk | Mitigation |
|---|---|
| GitHub Actions cron is best-effort (5–30 min drift possible) | T212 enforces stops broker-side via `stop_limit` orders; agent only reports detection. Drift is cosmetic, not financial |
| Free GitHub Actions minutes (2000/mo) | Projected ~1500/mo with daily run + 12 intraday polls; alert at 1800/mo. Upgrade to Pro ($4/mo) if breached |
| No static-IP for T212 API allowlisting | Rotate T212 key quarterly; T212 MFA + withdrawal protections still apply. Phase-2 option: small static-IP relay (Cloudflare Worker or £4 VPS) |
| Vercel cold starts (~300ms) on Telegram approval | Acceptable — humans tap buttons in seconds, not milliseconds |
| Neon free-tier compute hours (191/month) | Connections short-lived from cron; well under budget. Alert at 150h/month |
| Secrets sprawl across 3 services | Documented in `docs/runbook.md` (M0). Quarterly rotation checklist |

## 15. Upgrade triggers

- Backtest shows edge → flip to T212 live (V1.1)
- GitHub Actions minutes exceeded → GitHub Pro ($4/mo) or move cron to Pi/VPS
- Need intraday bars or higher-frequency news → Polygon or Tiingo (£25–£40/mo)
- Need static-IP for T212 allowlist → small relay box
- Multi-user / multi-portfolio → real auth layer + per-user state in Neon
