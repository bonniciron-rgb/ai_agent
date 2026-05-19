# Ethera Trading — Project Status & Roadmap

**Last updated**: 2026-05-17 (Recorded new business requirements — proposal risk score, market-leaders tracker)
**Maintained by**: Claude (Lead, Opus for design/architecture)
**Team**: Sonnet (implementation/distribution), Tiger teams (background development)
**Daily Sync**: This file is the single source of truth for standups and context preservation.

> **Ops note (2026-05-15):** Vercel's Hobby plan blocks deployments of a private
> repo that contain commits authored by anyone other than the account owner.
> Agent commits must therefore be authored as `bonniciron-rgb <bonniciron@gmail.com>`
> (done via per-commit `git -c user.name=… -c user.email=… commit` — no persistent
> config change). If Vercel deploys start failing with "commit author did not have
> contributing access", check the author of recent commits first.

---

## 🎯 Strategic Pivot — 2026-05-11

After 10 days of building 5 selective signals (A1, A2, B2, A3, B5) and running 2 real-data backtests against SPY across 4 years (2022–2026), **none of the signals showed positive alpha vs the benchmark**. This is consistent with academic literature: most published anomalies have decayed 60-80% post-publication, and single-factor long-only strategies typically lose to passive in bull markets.

### Decision: Reframe from "Alpha Generator" to "Disciplined Exposure Manager"

**Old framing**: AI picks individual stocks to outperform SPY.
**New framing**: AI holds SPY by default, **tilts allocation 50-150%** based on composite factor model, removes emotional/timing friction.

**Why this works**:
- Behavioral finance research: retail investors lose 2-4% CAGR through bad timing decisions; automating that captures real value
- Multi-factor blends consistently beat single-factor in academic literature (modest alpha, ~1-2% per year)
- The LLM + agent infrastructure's real strength is decision support + automation, not alpha discovery
- We're not competing with Renaissance/AQR (hundreds of factors, billions of capital) — we're solving a real retail problem

### v1 + v2 Backtest Findings (Source of Truth)

| Signal | v1 Sharpe | v2 Sharpe | v2 Alpha | Verdict |
|---|---:|---:|---:|---|
| SPY (4yr benchmark) | 1.14 | 1.02 | — | — |
| A1 Sector RS | 0.83 | 0.67 | -12.0% | Underperforms; mean-reverts on defensives |
| A2 PEAD | 0.18 | 0.43 | -17.1% | Working as designed; data sparse |
| B2 Analyst Rev (3mo) | **1.51** | 0.75 | -16.4% | v1 config was right; v2 relaxation degraded |
| A3 Insider | -0.05 | 0.00 | -17.3% | Broken; dynamic CIK lookup needs debug |
| B5 Short Squeeze | 0.00 | **-0.90** | **-29.6%** | Catastrophic falling-knife trap |

### New Product Vision (under revision — see ⚠️ below)

> *"I hold SPY by default. When my factor model says risk-on, I tilt to 120%. When risk-off, 70%. The AI handles timing, sizing, rebalancing, and reporting so I don't have to think about it daily."*

### ⚠️ Status update — 2026-05-12 (Batch 21)

The breadth-based SPY-tilt implementation of this vision **passed in-sample (2022-2026: Sharpe 1.14 vs SPY 0.99) but failed out-of-sample (2015-2019: Sharpe 0.51 vs SPY 0.73, CAPM α −1.75%)** — the timing edge did not generalize. What *did* survive both windows: **A1 sector relative strength as a low-beta defensive equity sleeve** (~+1.7% CAPM alpha, β ≈ 0.5, ~⅔ SPY drawdown). A2/B2 are non-viable on free Finnhub data.

So the *deliverable, honest* product is currently "**a low-beta equity sleeve**" rather than "a smart SPY-timing overlay". A regime-gated tilt (using the macro regime detector instead of stock breadth) is the next thing to test before concluding timing has no edge here. The exposure-manager infrastructure (tilt engine, ExposureSnapshot) is built and reusable. **Directional decision pending.**

---

## Project Overview

**Ethera Trading** is an AI-powered algorithmic trading agent with proposal-approval workflow, cost tracking, signal validation harness, and mobile-first PWA for on-the-go trading decisions.

### Brand Identity
- **Navy**: #0E2138
- **Teal**: #1F6B82
- **Cream**: #F2F0EC
- **App Background**: #0A0E1A
- **Logo**: Geometric hex sigil (placeholder `branding/sigil.svg`; awaiting official designer export)

---

## ✅ Shipped Features

### Batch 1: Infrastructure & Cost Tracking [Merged]
**PR #46 + supporting infrastructure**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| LLM Usage Dashboard | `app/llm-usage/page.tsx`, `UsageClient.tsx`, `DailyCostChart.tsx` | ✅ | Period selector (7/30/90d), summary cards, cache hit rate, model/pass breakdown |
| Cost Alert API | `src/ai_agent/digest/daily_digest.py` | ✅ | Daily proposal + cost aggregation, dual Telegram + web-push delivery |
| Watchlist Editor (DB-backed) | `app/watchlist/page.tsx`, `WatchlistClient.tsx`, `src/ai_agent/db/watchlist_store.py` | ✅ | No redeploy needed, CRUD from UI, replaces yaml |
| Macro Regime Detector | `src/ai_agent/macro/regime_detector.py`, `app/regime/page.tsx` | ✅ | VIX-based classification (crisis/bear/correction/bull/sideways/mixed), 30d history |
| Schema-missing hotfix | `app/api/llm-usage/route.ts`, `app/api/macro-regime/route.ts` | ✅ | Catches 42P01, returns `schemaPending: true`, UI shows amber "first-run pending" banner |

**Cost reduction achieved**: 65–75% via tiered LLM routing (Haiku screening → Opus analysis) + prompt caching.

---

### Batch 2: Signal Validation Harness (C1) [Merged]
**PR #46 + signal framework**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal Protocol | `src/ai_agent/signals/base.py` | ✅ | `Signal`, `SignalContext`, `SignalResult` dataclasses; protocol-based |
| Backtest Orchestration | `src/ai_agent/signals/runner.py`, `scripts/backtest_signal.py` | ✅ | Multi-symbol, persists to `SignalBacktest` table (sharpe, cagr, alpha, trade_count) |
| Reference Signals | `src/ai_agent/signals/reference.py` | ✅ | `AlwaysFlatSignal` (sanity), `SmaCrossSignal` (proof-of-concept) |
| DB Model | `src/ai_agent/db/models.py:SignalBacktest` | ✅ | signal_name, version, period, metrics, timestamps |
| Test Suite | 22 new tests | ✅ | Classifier logic, orchestration, persistence |

**Validation gate**: All signals must backtest (2+ years, daily) with proven sharpe >0.5 before 2-week shadow, then live.

---

### Batch 3: PWA Phase 1 — Scaffold & Icons [Merged]
**PR #47**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Manifest (Next.js typed) | `app/manifest.ts` | ✅ | Auto-published at `/manifest.webmanifest` |
| Viewport + Meta Tags | `app/layout.tsx` | ✅ | Apple mobile web app, icons, theme color |
| Service Worker | `public/sw.js` | ✅ | Cache-first shell, network-first /api/*, v2 (bumped for P2 push) |
| SW Registration | `app/components/RegisterServiceWorker.tsx` | ✅ | Client-side, safe no-op if unavailable |
| iOS Install Banner | `app/components/InstallPrompt.tsx` | ✅ | "Add to Home Screen" dismissible prompt (Safari 15+) |
| Favicon & Icons | `app/icon.tsx`, generated PNGs | ✅ | 32px favicon fallback, 192/512/maskable-512, apple-touch-152/167/180 |
| Icon Generator Script | `scripts/generate-icons.mjs` | ✅ | Sharp-based, one-command build |
| Splash Screens | Generated iphone-x, iphone-15-pro | ✅ | Automatic generation at build time |

**Installable**: Desktop (Chrome/Edge), iOS (Safari 16.4+), Android (all modern browsers).

---

### Batch 4: PWA Phase 2 — Web Push & Notifications [Merged]
**PR #48**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Push Subscription Store | `src/ai_agent/db/models.py:PushSubscription`, `src/ai_agent/db/push_store.py` | ✅ | CRUD ops, endpoint idempotency, last_used tracking |
| VAPID Keypair Gen | `scripts/generate_vapid_keys.py` | ✅ | One-time setup, base64url output |
| Push Sender | `src/ai_agent/digest/push_sender.py` | ✅ | Batch send via pywebpush, auto-cleanup of 410-Gone (unsubscribed) |
| Digest Integration | `src/ai_agent/digest/daily_digest.py` | ✅ | Added `format_digest_summary()`, `_send_web_push_safe()`, parallel Telegram + web-push |
| API: VAPID Public Key | `app/api/push/vapid-public-key/route.ts` | ✅ | GET (public) |
| API: Subscribe | `app/api/push/subscribe/route.ts` | ✅ | POST (auth), idempotent |
| API: Unsubscribe | `app/api/push/unsubscribe/route.ts` | ✅ | POST (auth) |
| Subscribe Button | `app/components/PushSubscribeButton.tsx` | ✅ | Three-state UI (Enable / Enabled ✓ / Blocked) |
| SW Push Handler | `public/sw.js` push event + notificationclick | ✅ | Handles incoming push, click-through navigation |
| Test Suite | 12 new tests | ✅ | CRUD, send_to_all (mocked), 410 cleanup, error paths |

**Delivery channels**: Telegram (existing) + web-push (new, parallel). Daily digest + cost alerts via both.

---

### Batch 5: PWA Phase 3 — Mobile Approval UI [Merged PR #49]
**PR #49 (CI: ✅ passed 2026-05-10)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Approval API Routes | `app/api/proposals/[id]/{approve,reject,defer}/route.ts` | ✅ | Mirrors Python `DbDecisionStore.record_decision` exactly; 409 if already decided, 404 if not found |
| Shared Helper | `lib/proposal-actions.ts` | ✅ | Deduped API logic (status update, decided_at, decided_by, shadow flip for approve/reject) |
| Approval Actions Component | `app/proposals/[id]/ApprovalActions.tsx` | ✅ | Sticky-bottom mobile bar, inline desktop buttons, bottom-sheet modal, `navigator.vibrate(50)` haptic, auto-dismiss toast, `router.refresh()` |
| Mobile Card Layout | `app/proposals/MobileProposalCard.tsx` | ✅ | Card view for list page (`<sm`): symbol, side, qty, limit, stop, rationale, confidence, created |
| Responsive Pages | `app/proposals/page.tsx`, `[id]/page.tsx` | ✅ | Mobile cards hidden on sm+; desktop table hidden on mobile |
| Hamburger Navigation | `app/components/Nav.tsx` (client) | ✅ | Converted to `"use client"`, drawer for `<sm`, desktop nav preserved, 10 nav links |
| Test Suite | 396 tests, tsc clean, build ok | ✅ | Full approval flow coverage |

**Approval surface**: Web PWA now feature-parity with existing Telegram channel. Users can approve from either.

---

### Batch 6: A1 Sector Relative-Strength Signal [Merged PR #50]
**PR #50 (CI: ✅ passed 2026-05-11, format fix in commit 129f177)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal implementation | `src/ai_agent/signals/sector_rs.py` | ✅ | `SectorRelativeStrengthSignal` — long when stock 20d return exceeds sector ETF by ≥2% |
| `__init__.py` export | `src/ai_agent/signals/__init__.py` | ✅ | `SectorRelativeStrengthSignal` added to public API |
| CLI registration | `scripts/backtest_signal.py` | ✅ | `sector_relative_strength` choice + `--sector-map` JSON flag |
| Test suite | `tests/signals/test_sector_rs.py` | ✅ | 16 tests (outperform→long, underperform→flat, threshold edge, SPY fallback, insufficient history) |

**First real signal flowing through C1 harness.** Validated 2026-05-11 (synthetic data, harness verified).

---

### Batch 7: C1 Harness Fix + A1 Backtest Validation [Merged PR #51]
**PR #51 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Harness bug fix | `src/ai_agent/signals/runner.py` | ✅ | `_inject_sector_prices()` — ETF bars now wired into signal before per-symbol loop; was producing 0 trades |
| Backtest report | `reports/a1-backtest.md` | ✅ | 18 symbols × 521 days; synthetic data (sandbox network blocked); Sharpe 0.46, harness verified |
| Backtest script | `scripts/run_a1_backtest.py` | ✅ | Reproducible real-data script (runs when network available) |

**Critical fix**: without this, every signal relying on external prices would silently produce 0 trades in production.

---

### Batch 9: B2 Analyst Estimate Revision Momentum Signal [Merged PR #53]
**PR #53 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal implementation | `src/ai_agent/signals/analyst_revisions.py` | ✅ | `AnalystRevisionMomentumSignal` + `RecommendationSnapshot` dataclass; long when bullish score strictly improves for ≥3 consecutive months |
| Finnhub `recommendation_trends()` | `src/ai_agent/data/finnhub_source.py` | ✅ | New method calling `GET /stock/recommendation`; mirrors `earnings_calendar()` style |
| Finnhub injection helper | `src/ai_agent/signals/runner.py` | ✅ | `_inject_recommendations()` + call in `backtest_signal()`; mirrors A1/A2 pattern |
| `__init__.py` export | `src/ai_agent/signals/__init__.py` | ✅ | `RecommendationSnapshot`, `AnalystRevisionMomentumSignal` added to public API |
| CLI registration | `scripts/backtest_signal.py` | ✅ | `analyst_revision_momentum` choice in `REGISTRY` |
| Test suite | `tests/signals/test_analyst_revisions.py` | ✅ | 28 tests across 8 classes (streak, plateau, stale, custom thresholds, empty data, formula, attributes) |

**Third real signal through C1.** Based on Hawkins et al. analyst revision momentum anomaly. Finnhub `/stock/recommendation` integrated via `_inject_recommendations()`.

---

### Batch 47: Held-position exit review + mandatory stops [2026-05-17]
**PR (draft)**

Made the agent a full buy-AND-sell trader. Previously it only found entries;
existing positions had no exit logic. Posture: active, fast turnover —
booking many small gains for steady cumulative profit.

- **`portfolio_snapshot.py`** — `_load_from_t212` now also captures per-symbol
  share quantities (so a SELL can be sized).
- **`daily_loop.py`** — `get_portfolio` returns each position's quantity +
  GBP value, keyed by plain symbol.
- **`agent/runner.py`** — held tickers, excluded from buy-screening (Batch 46),
  now rejoin the *decision* pass so the agent reviews them for an exit.
- **`agent/prompts.py`** — new "Managing existing positions" section: propose
  a SELL when a position has run its course (profit fading, regime turned,
  structure broken); take steady gains, don't churn, cut losers. Stop rule
  hardened: every buy must carry a stop.
- **`risk/rails.py`** — a buy with no `stop_price` is now rejected.
- **`agent/tools.py`** — tool descriptions updated to match.

Known limit: exit review only covers holdings with price data — US stocks,
not the London ETFs (no working data feed for those tickers).

---

### Batch 46: Exclude already-held tickers from screening [2026-05-17]
**PR (draft)**

The agent's no-re-entry rule (don't buy what you already hold) was applied in
the *decision* pass — *after* screening had already spent shortlist slots on
held names. On a recent run 4 of 5 shortlisted names were held, leaving the
Opus decision pass just 1 genuine new candidate → "no trade".

- **`agent/runner.py`** — `_run_tiered` now drops already-held tickers from
  the screening universe up front (`_held_symbols()` reads the portfolio,
  strips the T212 venue suffix). The empty-shortlist fallback uses the
  un-held universe too. So all shortlist slots go to real new candidates.
- **`tests/agent/test_tiered_routing.py`** — covers suffix-stripping and
  held-ticker exclusion.

Note: held names are still skipped for *buys* by the prompt rule; active
exit-management of held positions would be a separate dedicated pass.

---

### Batch 45: Fix — relabel "considered" → "proposed" on analysis card [2026-05-17]
**PR (draft)**

The "Today's analysis" card showed `{proposals_generated} considered`, which
read as "symbols considered" — alarming as "0 considered" when the agent
simply generated no proposals (its normal no-trade outcome). `proposals_`
`generated` is the count of proposals the agent *produced*, not symbols
analysed. Relabelled to "proposed" on `app/proposals/page.tsx` and
`app/analysis/AnalysisClient.tsx`. UI-only; no behaviour change.

---

### Batch 44: Fix — buzz tracker via ApeWisdom (Reddit blocks Vercel) [2026-05-17]
**PR (draft)**

Reddit blocks unauthenticated `.json` requests from datacenter IPs, so the
Batch 43 `/buzz` page showed "Reddit is unreachable" on Vercel.

- **`lib/buzz.ts`** (new, replaces `lib/reddit.ts`) — sources buzz from
  ApeWisdom (apewisdom.io), a keyless Reddit-mention aggregator that works
  from any IP. Its 24h-ago counts enable a real **momentum** filter:
  tickers are classed rising / steady / fading by mention acceleration,
  ranked by engagement-weighted buzz, low-traction names dropped.
- **`app/buzz/page.tsx`** — adds a "vs 24h" momentum column + Trend badge;
  the "Accelerating" callout flags sharply-rising buzz.

---

### Batch 43: BR-2 — Reddit retail-buzz tracker (noise-filtered) [2026-05-17]
**PR (draft)**

A `/buzz` page surfacing the most-discussed tickers on investing subreddits,
with layered noise-filtering so it highlights real trends, not chatter.

- **`lib/reddit.ts`** (new) — pulls hot posts from r/wallstreetbets,
  r/stocks, r/StockMarket. Filters: ticker candidates validated against the
  SEC ticker universe, slang stopwords dropped, one-off mentions (<3)
  discarded, ranked by **engagement-weighted** buzz (log-damped upvotes +
  comments) so low-effort posts can't fake a trend. Top filtered cluster is
  flagged "strong". Cached 6h.
- **`app/buzz/page.tsx`** (new) — ranked table + a "worth a look" callout;
  clearly labelled a sentiment signal, not a buy recommendation.
- **`Nav.tsx`** — "Buzz" link under Markets.

---

### Batch 42: BR-2 — Insider (Form 4) activity tracker [2026-05-17]
**PR (draft)**

The free alternative to the deferred X/Twitter leader feed: track corporate
insiders buying/selling their own stock via SEC Form 4 filings.

- **`lib/insiders.ts`** (new) — fetches Finnhub's insider-transactions
  endpoint (Form 4 data) for the active watchlist, last 90 days; keeps
  open-market buys/sells (codes P/S), cached 6h. Degrades gracefully if
  `FINNHUB_API_KEY` is unset.
- **`app/insiders/page.tsx`** (new) — table of date, symbol, insider,
  buy/sell, shares, value.
- **`Nav.tsx`** — "Insiders" link under Markets.

Completes BR-2's "follow the leaders" theme without the paid X API.

---

### Batch 41: BR-2 — IPO calendar tracker [2026-05-17]
**PR (draft)**

Second visible slice of BR-2: a `/ipos` page tracking recent and upcoming
US IPOs (the "emerging companies" half of the requirement).

- **`lib/ipos.ts`** (new) — fetches Finnhub's IPO-calendar endpoint for a
  -30d/+60d window; cached 6h. Degrades gracefully if `FINNHUB_API_KEY` is
  absent in the environment.
- **`app/ipos/page.tsx`** (new) — sortable table: date, symbol, company,
  exchange, price, status (with upcoming/priced/withdrawn styling).
- **`Nav.tsx`** — "IPOs" link under Markets.

Follow-up: agent integration (screen fresh IPOs into proposals) and
X/Twitter leader feeds (paid API).

---

### Batch 40: BR-2 — Agent can read institutional 13F holdings [2026-05-17]
**PR (draft)**

Wires the 13F "smart money" data into the trading agent so it can weigh what
notable investors hold when forming proposals.

- **`data/thirteenf.py`** (new) — Python 13F fetcher (mirrors
  `lib/thirteenf.ts`): pulls a manager's latest 13F-HR from SEC EDGAR, parses
  the information-table XML with `xml.etree`, merges lots by issuer, ranks by
  portfolio %. Process-cached (13F data is quarterly).
- **`agent/tools.py`** — new `get_institutional_holdings` tool: returns each
  tracked manager's top holdings with portfolio %. Backward-compatible
  (no-op default on `Toolbox`).
- **`loop/daily_loop.py`** — wires the tool into the agent's Toolbox.

The tool description tells the agent to treat 13F as supportive conviction
context, not a timing signal (data is up to 45 days stale).

---

### Batch 39: BR-2 (start) — Institutional 13F "smart money" tracker [2026-05-17]
**PR (draft)**

First slice of BR-2: a `/leaders` page tracking what widely-followed
institutional investors hold, from their quarterly SEC 13F filings.

- **`lib/thirteenf.ts`** (new) — fetches a manager's latest 13F-HR from SEC
  EDGAR (submissions → filing index → information-table XML), merges lots by
  issuer, ranks by value. Keyless; EDGAR responses cached 6h.
- **`app/leaders/page.tsx`** (new) — per-manager card with top-10 holdings by
  portfolio %. Curated set: Berkshire (Buffett), Scion (Burry), Pershing
  Square (Ackman).
- **`Nav.tsx`** — "Leaders" link under Markets.

Follow-ups: agent integration (screen 13F holdings → proposals), the
IPO/emerging-company half of BR-2, and X/Twitter leader feeds (paid API).

---

### Batch 38: BR-1 — Per-proposal risk score [2026-05-17]
**PR (draft)**

Implements business requirement BR-1: every proposal carries a 1-5 risk
score (1 = lowest risk) with a short reason.

- **`risk/scoring.py`** (new) — `score_proposal()`: rule-based 1-5 score from
  three measurable factors (position size vs NAV, ATR volatility, stop-loss
  width). Transparent, unit-tested, no LLM cost.
- **`db/models.py`** — `Proposal` gains `risk_score` + `risk_score_reason`
  (nullable; the Batch 33 schema reconciler adds the columns next loop run).
- **`loop/daily_loop.py`** — scores each passing proposal, persists it.
- **`digest/daily_digest.py`** — digest line shows `risk N/5`.
- **`lib/queries.ts`** + new **`RiskBadge`** component — score surfaced on
  the `/proposals` list, the proposal detail page, and the mobile card.

Macro regime was considered as a 4th factor but left out for now.

---

### Batch 37: Replace broken Stooq backup with Yahoo chart API [2026-05-17]
**PR (draft)**

Stooq's free CSV download is now gated behind an API key — it returns an
"apikey" advert instead of data (the `source_failed` warnings). It was the
backup OHLCV source, so there was effectively no working fallback.

- **`data/yahoo_chart_source.py`** (new) — `YahooChartSource`, a keyless
  adapter for Yahoo's stable `/v8/finance/chart` JSON endpoint. Resilient to
  *yfinance-library* breakage (the most common failure mode) since it does
  its own HTTP + parsing.
- **`data/stooq_source.py`** + its test — deleted.
- **`loop/daily_loop.py`** — OHLCV chain is now
  `[YFinanceSource, YahooChartSource]`.
- **`scripts/backfill_watchlist.py`**, **`scripts/check_signals.py`** — moved
  off the deleted Stooq source onto `YahooChartSource`.

---

### Batch 36: Loop currency normalisation to GBP [2026-05-17]
**PR (draft)**

The loop mixed currencies: NAV is GBP, but position prices are quoted in the
instrument's currency (USD, GBX pence) and proposal limit prices are USD —
so the risk caps compared USD/GBX notionals against a GBP NAV.

- **`broker/fx.py`** (new) — `get_gbp_rates()` (frankfurter.app, no key,
  process-cached) + `to_gbp()`: GBP unchanged, GBX/GBp ÷100, others ÷rate.
- **`broker/t212_client.py`** — `get_instruments()` → `{ticker: currencyCode}`.
- **`loop/portfolio_snapshot.py`** — position values converted to GBP via
  instrument currency + FX before populating `position_values`.
- **`risk/rails.py`** — `RiskChecker` gains `usd_to_gbp`; order notionals are
  converted to GBP (proposals are US-listed → USD). Default 1 = no-op.
- **`loop/daily_loop.py`** — wires the live USD→GBP rate into the checker.
- **`tests/conftest.py`** — autouse fixture seeds the FX cache so no test
  reaches the live rate service.

Residual: the agent still *sizes* its proposals currency-naively (treats the
GBP NAV as USD); the corrected rails accept the result (slightly under 5%).
Making the agent FX-aware for exact sizing is a separate follow-up.

---

### Batch 35: Fix — positions load (fxPpl null) + NAV double-count [2026-05-17]
**PR (draft)**

First fully-clean live run (exit 0, schema self-healed 4 columns) still
showed "no open positions" and surfaced a latent NAV bug:

- **`broker/models.py`** — `/api/v0/equity/portfolio` returned 200 but
  `OpenPosition` rejected `fxPpl: null`. T212 sends `fxPpl=null` for
  account-currency (non-FX) instruments like GBP London ETFs; a field
  default only covers an *absent* key, not an explicit null. Added a
  `before` validator coercing `None → Decimal(0)` for `ppl`/`fx_ppl`.
- **`loop/portfolio_snapshot.py`** — `_load_from_t212` computed
  `nav = free + invested + Σ(position values)`, double-counting the
  invested portion once positions load. NAV is now T212's `total`
  (the account NAV) directly.

Known follow-up: per-position values + the agent's sizing are still
currency-naive (GBX/USD not normalised to GBP — the FX/metadata logic
PR #75 added to the dashboard is not yet ported to the loop).

---

### Batch 34: Agent skips paused (not-followed) watchlist tickers [2026-05-17]
**PR (draft)**

The watchlist editor already had a Pause/Resume toggle (`WatchlistTicker.`
`paused`), but `to_watchlist()` — the agent-facing loader used by the daily
loop — returned every row regardless. Paused tickers were still ingested,
screened, and sent to the (expensive) decision pass.

- **`db/watchlist_store.py`** — `to_watchlist()` now excludes `paused` rows.
  The watchlist editor reads raw rows via `/api/watchlist`, so paused
  tickers stay visible and editable there.

Lets the user mute junk tickers (e.g. London-ETF symbols with no US data)
without deleting them.

---

### Batch 33: Fix — Daily loop crash + endpoint/parse bugs [2026-05-17]
**PR (draft)**

First run that reached live T212 (NAV £3310.59) surfaced three bugs:

- **`t212_client.py`** — `get_positions()` used `/api/v0/equity/portfolio/`
  `open-positions`, which T212 treats as ticker `open-positions` → 404.
  Corrected to `/api/v0/equity/portfolio` (the endpoint the dashboard
  already uses). Position concentration rails were running blind.
- **`db/engine.py`** — FATAL: `column order.idempotency_key does not exist`
  crashed the loop (exit 1) during the risk-rail check, *after* the agent
  produced its proposal. `create_all` never ALTERs existing tables, so a
  model column added later stays missing. `init_schema()` now reconciles
  drift via `ADD COLUMN IF NOT EXISTS` (Postgres-only, nullable-only). The
  loop calls `init_schema()` at startup, so it self-heals next run.
- **`agent/screening.py`** — Haiku wrapped its JSON in a ```` ```json ````
  fence; `json.loads` failed → empty shortlist → decision pass ran on all
  30 symbols instead of 5 (≈6× Opus cost). Added `_extract_json_object()`
  to slice the outermost `{...}`.

Known follow-up (data, not code): watchlist still holds London-ETF junk
tickers (AIQGL/JAYL/VHYDL/VWRPL/FB/MSFD/NVDD/SZZL) — no US bar data.

---

### Batch 32: Fix — Default T212 env to live [2026-05-17]
**PR (draft)**

Daily loop kept hitting `demo.trading212.com` and 401'ing with live
credentials → NAV $0 → no sized proposals. Commit `702e104` patched the
`daily.yml` workflow default (`|| 'demo'` → `|| 'live'`) but left the Python
code defaulting to demo.

- **`settings.py`** — `Settings.t212_env` default `demo` → `live`. The account
  is live-only; when `T212_ENV` is unset (or a re-run reuses a pre-`702e104`
  workflow file) the loop now reads the live endpoint instead of 401ing.
  Order placement stays gated by `run_mode`, not this.
- **`test_settings.py`** — default-assertion updated to `T212Env.live`.

---

### Batch 31: Portfolio — Normalise Position Values to GBP [2026-05-17]
**PR (merged)**

User reported a holding showing a ~£18,900 value it couldn't be worth.
Cause: London-listed ETFs quote in **pence (GBX)**, and the route treated the
quote price as pounds — inflating every London holding ~100×.

- **`route.ts`** — instrument metadata now also yields `currencyCode`;
  `toGbp()` converts each position's prices to GBP: `GBX`/`GBp` ÷100 (a unit,
  not FX), other currencies via live FX (`api.frankfurter.app`, cached 12h).
  `PortfolioPosition` gains a `currency` field.
- **`PortfolioClient.tsx`** — shows the native quote currency (e.g. `· USD`)
  next to non-GBP tickers so the conversion is transparent.

Total value / 1d-7d change were already correct (T212's cash `total` is in
account currency); this fixes per-position values + the donut.

---

### Batch 30: Portfolio — Friendly Instrument Names [2026-05-17]
**PR #74 (merged)**

The positions table showed bare tickers (`VWRP`, `NVDA`). It now shows the
human-readable instrument name:
- **`route.ts`** — `getInstrumentNames()` fetches T212's
  `/api/v0/equity/metadata/instruments` once, builds a raw-ticker → name map,
  and caches it in module memory for 24h (the endpoint returns the whole
  instrument universe). Each `PortfolioPosition` gains a `name` field
  (falls back to the symbol if metadata is unavailable).
- **`PortfolioClient.tsx`** — the table's first column ("Holding") shows the
  name with the symbol as a mono sub-label.

---

### Batch 29: Portfolio — Value Insights (1d/7d Change, Count, Donut) [2026-05-17]
**PR #73 (merged)**

Richer Portfolio dashboard:
- **`portfoliovaluesnapshot` table** — created + upserted by `/api/portfolio`
  on every successful load (one row per day, keyed `as_of`). Stores total
  value, free cash, invested, position count.
- **1-day / 7-day change** — `route.ts` reads snapshot history and returns
  `valueChange.d1` / `.d7` (vs the nearest earlier snapshot). Null until
  history accumulates; the UI shows a "tracking has started" note meanwhile.
- **`PortfolioClient.tsx`** — total-value headline with 1d/7d deltas, a
  Holdings (ticker count) card, and a hand-rolled SVG **donut** showing the
  value distribution across holdings + cash (top 8 + "Other").

---

### Batch 28: Default T212_ENV to live in Workflows [2026-05-17]
**PR #72 (merged)**

The daily loop kept hitting `demo.trading212.com` → `401` because the
`T212_ENV` repo *variable* never took effect. `daily.yml`, `reconcile.yml`,
`signals_check.yml` now default `T212_ENV` to `live` (the account is live;
all three only read from T212). `vars.T212_ENV` still overrides if set.

---

### Batch 27: Portfolio — Restrict Watchlist Sync to US-Listed Holdings [2026-05-17]
**PR #71 (merged)**

First real daily-loop run after the Portfolio page surfaced a problem: the
"Add holdings to watchlist" button had added the user's **London-listed ISA
ETFs** (VWRP, VHYD, AIQG, JAY …). The agent's data pipeline (yfinance/Stooq)
and factor signals are built for **US single stocks** — so bar ingestion failed
for every London ticker (`possibly delisted; no timezone found`).

Fix — keep the screening watchlist US-only:
- **`route.ts`** — each `PortfolioPosition` now carries `usListed`
  (`ticker.includes("_US_")`). `plainSymbol()` also strips T212's trailing
  lowercase `l` London marker (`VWRPl_EQ` → `VWRP`, not `VWRPL`).
- **`PortfolioClient.tsx`** — "Add holdings to watchlist" only POSTs US-listed
  holdings; non-US positions show a muted `not screened` badge and a note.

Also surfaced (config, user-side): the daily-loop GitHub Actions run hit
`demo.trading212.com` and 401'd because the `T212_ENV` **repository variable**
is unset → defaults to `demo`. Must be set to `live`.

---

### Batch 26: Portfolio Page — Live T212 Holdings + Watchlist Sync [2026-05-16]
**PR #70 (merged)**

New **Portfolio** page surfacing the live Trading 212 account so held symbols
can flow into the agent's watchlist:

- **`app/api/portfolio/route.ts`** — GET route. Fetches `/api/v0/equity/account/cash`
  and `/api/v0/equity/portfolio` in parallel via HTTP Basic auth, returns cash
  (free/invested/total) + positions. Each position is flagged `inWatchlist` by
  cross-referencing the `watchlistticker` table. Strips the T212 venue suffix
  (`AAPL_US_EQ` → `AAPL`). Surfaces config/401 problems as `ok:false` + message.
- **`app/portfolio/page.tsx` + `PortfolioClient.tsx`** — account summary cards
  + positions table with per-position P&L (£ and %). A one-click **"Add holdings
  to watchlist"** button POSTs each untracked symbol to `/api/watchlist`
  (handles 409 "already exists" gracefully), so holdings are reflected in the
  watchlist immediately.
- **`Nav.tsx`** — "Portfolio" added to the primary nav.

---

### Batch 25: Fix Empty Agent Analysis — Data-Aware Screening [2026-05-16]
**PR #69**

Two-part fix for the confirmed bug causing every daily analysis row to show 0 iterations, no reasoning, and 0 proposals:

- **Part A (screening.py + runner.py):** Before calling Haiku screening, fetch `get_features` for each watchlist symbol and pass the JSON context to `build_screening_user_message`. Haiku now sees real price/indicator data (close, regime, RSI, etc.) instead of bare ticker names, so it can make meaningful shortlist decisions.
- **Part B (runner.py):** When Haiku returns an empty shortlist, fall back to running the Opus decision pass on the full watchlist (`stop_reason="screening_empty_fallback"`) instead of returning early. The decision pass now always runs, guaranteeing real reasoning and proposals are recorded every day.

---

### Batch 24: Fix T212 Auth — HTTP Basic (key + secret) [2026-05-16]
**PR #68**

Root cause of the persistent `401`s when connecting Trading 212: the API was
**updated** to use **HTTP Basic auth** — `Authorization: Basic base64(API_KEY:API_SECRET)`
— but `t212_client.py` was built against the old single-raw-key scheme
(`Authorization: <key>`). Confirmed against docs.trading212.com/api: the key is
the username, the secret is the password. (Also confirmed the API supports
**Invest + Stocks ISA** — an earlier claim that ISA was unsupported was wrong.)

Changes:
- `T212Client.__init__` takes `api_secret`; builds `Basic base64(key:secret)`,
  `.strip()`-ing both halves (guards against env-var newline — a 401 cause).
- `settings.py`: new `t212_api_secret`. Call sites (`reconciliation.py`,
  `daily_loop.py`) and workflows (`daily.yml`, `reconcile.yml`) pass it.
- Dashboard `/api/connection/t212`: builds the Basic header; needs both
  `T212_API_KEY` + `T212_API_SECRET` in Vercel env.
- `.env.example` documents both halves.

**User action:** set `T212_API_SECRET` (the secret) alongside `T212_API_KEY`
(the key id) in Vercel env *and* GitHub Actions secrets, then redeploy.

617 tests passing; `tsc` clean.

---

### Batch 23: Connections Page + Nav Redesign [2026-05-16]
**PR #67**

New **Connections** dashboard page (`/connections`):
- **Test T212 connection** — `GET /api/connection/t212` calls the T212 cash
  endpoint with the dashboard's `T212_API_KEY`; shows free/invested/total on
  success or the exact HTTP error (e.g. 401 = bad/expired key). Read-only.
- **Sync now** — `POST /api/sync` triggers the `daily-trade-loop` workflow via
  GitHub `workflow_dispatch`; dry-run by default. Needs `GITHUB_DISPATCH_TOKEN`
  in Vercel env.

Nav redesign: the flat 12-item bar was too cluttered. Now 4 daily-use links
(Dashboard, Proposals, Analysis, Orders) stay visible; the rest move under a
grouped **More** dropdown (Markets / Tracking / System). Mobile drawer mirrors
the grouping.

Note: T212 env vars must be set in **Vercel** (separate from the GitHub Actions
secrets the cron uses). `tsc` clean; UI not browser-tested in this environment.

---

### Batch 22: Fix Zero-Proposal Bug — Regime Gate Loosened [2026-05-16]
**PR #66 (bundled with the Vercel ops-doc commit)**

The live agent had been proposing **nothing** every day ("No trade proposals
today — no signals met the criteria"). Root cause: the system prompt's signal
hierarchy forbade proposing in the `ranging` regime — buys were allowed *only*
in `trending_up`/`breakout`. On a mega-cap watchlist, most names sit in
`ranging` (ADX < 25) on a typical day, so the agent was structurally gated to
zero output.

Fix (`agent/prompts.py`): rewrote signal-hierarchy rule 1 from a hard regime
veto into a per-regime playbook — `ranging` now gets an explicit mean-reversion
strategy (buy lower Bollinger band when RSI oversold, trim upper band when
overbought). This is faithful to `features/regime.py`'s own documented intent
(*"don't propose breakouts in a ranging market"* implies mean-reversion belongs
there). Only `unknown` (warm-up, no data) still blocks a proposal. Also
clarified that `low`-confidence technical-only proposals are valid.

No risk rails changed; all proposals still require human approval. Expect the
agent to start producing daily suggestions again — review the first few before
connecting a live T212 key.

---

### Batch 21: Out-of-Sample Test (2015-2019) — SPY Tilt Does NOT Generalize [2026-05-12]
**Workflow run with `BACKTEST_START=2015-01-01 BACKTEST_END=2019-12-31`**

| Strategy | Sharpe | CAGR | MaxDD | CAPM α | β | Trades |
|----------|--------|------|-------|--------|---|--------|
| **SPY (benchmark)** | **0.73** | 9.4% | -20.2% | — | 1.0 | — |
| A1 Sector RS (10 sym) | 0.74 | 6.4% | -13.4% | **+1.7%** | 0.49 | 498 |
| A2 PEAD | — | — | — | — | — | 0 (no pre-2020 Finnhub earnings) |
| B2 Analyst Rev | — | — | — | — | — | 0 (Finnhub rec history too shallow) |
| Composite | 0.74 | 6.4% | -13.4% | +1.7% | 0.49 | 498 (= A1) |
| **SPY Tilt 50-100%** | **0.51** | 4.0% | -14.2% | **−1.75%** | 0.60 | 319 |

**Verdict: the v4 "SPY Tilt beats SPY" result was period-specific.** In 2022-2026 the tilt had Sharpe 1.14 vs SPY 0.99 (+0.15) and positive timing alpha. In 2015-2019 it has Sharpe 0.51 vs SPY 0.73 (**−0.22**) and CAPM α **−1.75%** — worse than a constant ~61% SPY position (≈5.7% CAGR / 0.73 Sharpe). The breadth-based timing de-risked at the wrong moments. **Not a robust edge.**

**What DID hold up: A1 itself.** +1.7% CAPM alpha, β ≈ 0.5, Sharpe matching SPY, ~⅔ the drawdown — consistent across both windows. A1 is a real (modest) *low-beta defensive equity sleeve*, not an alpha generator or a smart SPY-timing overlay.

**A2/B2 are non-viable on free Finnhub** for any historical work — no pre-2020 earnings actuals, shallow rec history. The composite is effectively just A1.

**Decision: PAUSE Phase B.3 product UI** — don't build a tilt dashboard around a timing overlay that subtracts value out-of-sample. The `ExposureSnapshot`/tilt-engine plumbing is retained (can drive whatever allocation logic we settle on). Reframe options under consideration:
- **(a) Low-beta equity sleeve** — hold the A1-leading basket; ~half SPY's vol, +1-2% structural alpha, smaller drawdowns. Deliverable today, honest.
- **(b) Regime-gated exposure** — replace the breadth-tilt input with the macro regime detector (VIX + SPY trend). De-risk on regime, not on stock breadth. Needs its own backtest. *(Lead's recommendation for next cycle.)*
- **(c) Accept "constant ~65% equity"** — what a target-date fund does for free.

---

### Batch 20: Phase B.3 — Exposure Tilt Engine + Daily Digest Wiring [Merged PR #63]
**PR #63 (CI: ✅ merged 2026-05-12) — infra retained even though the breadth-tilt itself is paused (Batch 21)**

| Component | Files | Status | Notes |
|-----------|-------|--------|-------|
| `ai_agent.exposure` package | `src/ai_agent/exposure/{tilt,job}.py` | ✅ | `score_to_allocation()` (shared formula — `SpyTiltStrategy` delegates to it), `TiltSnapshot` + `compute_tilt_snapshot()` (current allocation from latest bars), `tilt_summary_line()` (Telegram one-liner), `build_composite_signal()` / `make_snapshot()` (live A1+A2+B2 composite over the 11-symbol universe), `persist_snapshot()` / `latest_snapshot()` |
| `ExposureSnapshot` DB model | `src/ai_agent/db/models.py` | ✅ | Daily target SPY allocation + composite score + per-symbol breakdown; upsert by `as_of` |
| `SECTOR_MAP` single source of truth | `exposure/job.py` ← `run_all_backtests.py` imports it | ✅ | Backtest and live tilt can't disagree about the universe |
| Daily digest section | `src/ai_agent/digest/daily_digest.py` | ✅ | "📈 Exposure tilt: 65% SPY (composite +0.09, 11 names)" — reads latest snapshot, gracefully omitted if none |
| `scripts/tilt_snapshot.py` CLI | + `python -m ai_agent.exposure.job` | ✅ | Fetches latest bars (yfinance), builds sector_prices, persists an `ExposureSnapshot`; `--dry-run` to log only. Cron-able like `macro_regime.py` |
| Tests | `tests/exposure/test_{tilt,job}.py`, digest tests | ✅ | 614 total passing |

**Still pending in Phase B.3**: `app/tilt/page.tsx` dashboard + `app/api/tilt/route.ts` (need browser/visual QA), drawdown protection (auto-reduce to 50% on VIX > 30 / bear regime), Kelly-style sizing.

---

### Batch 19: v4 Results — Phase B Exposure Manager Validated [2026-05-12]
**Workflow run on main after PRs #59/#60/#61**

| Strategy | Sharpe | CAGR | MaxDD | Trades | Verdict |
|----------|--------|------|-------|--------|---------|
| **SPY (benchmark)** | 0.99 | 16.6% | -19.0% | — | — |
| A1 Sector RS (11 sym) | 0.90 | 9.8% | -12.6% | 517 | Real signal, sub-SPY return |
| A2 PEAD | 0.22 | 0.2% | -0.8% | 7 | Data-limited (free Finnhub lacks deep earnings history) |
| B2 Analyst Rev | 1.10 | 1.3% | -0.7% | 11 | High-quality, very low-frequency |
| Composite | 0.93 | 10.3% | -12.6% | 528 | ≈ A1 (A2/B2 barely contribute) |
| **SPY Tilt 50-100%** | **1.14** | 11.8% | **-11.2%** | 279 | **Beats SPY on Sharpe + halves drawdown** |

**Verdict: the exposure-manager thesis holds.** SPY Tilt has a 15% higher Sharpe than buy-and-hold SPY and 41% smaller max drawdown. Critically, a naive constant-65% SPY position would have ~0.99 Sharpe (scaling exposure doesn't change Sharpe) — the tilt's 1.14 is genuine timing skill (de-risk before drawdowns, re-risk before rallies) worth ~0.15 Sharpe + ~1% CAGR over the constant version. This is the "modest factor premium + behavioral discipline" the strategic pivot promised.

`score_distribution`: min 0.0 (→50% SPY), median 0.091 (→~65% SPY), max 0.455 (→100% SPY). Tilt now genuinely swings the full band (279 trades vs 49 in the broken near-constant version).

**Open caveats**: (1) mild survivorship bias — 11-symbol universe chosen after seeing v3 losers; (2) one 4yr mostly-bull window — needs out-of-sample (2015-2019) validation; (3) composite is really "A1 breadth → SPY tilt", not a 3-factor blend; (4) reported `alpha` (CAGR diff) is unfair to low-beta strategies — added `capm_alpha`/`beta` in Batch 18.

**Decision: green-light Phase B.3** (tilt dashboard + Telegram digest). Next analytical priority: out-of-sample backtest via the new `BACKTEST_START`/`BACKTEST_END` env override.

---

### Batch 18: Backtest Period Override + CAPM Alpha [2026-05-12]
**PR #62 (in progress)**

| Change | Rationale | Status |
|--------|-----------|--------|
| **`BACKTEST_START`/`BACKTEST_END`/`BACKTEST_LOOKBACK_DAYS` env override** in `run_all_backtests.py` | Enables out-of-sample runs (e.g. 2015-2019) without code changes — the #1 validation gap | ✅ |
| **`capm_alpha_beta()` in `metrics.py`** | Jensen's alpha + beta from OLS regression of daily excess returns; fair to low-beta exposure-manager strategies (the naive CAGR-diff `alpha` structurally penalizes them). Exposed in `summary()` and the backtest JSON. | ✅ |
| **8 new tests** | beta=1 self-regression, beta=0.5 half-exposure, zero-variance benchmark, insufficient overlap, positive-alpha case | ✅ (582 total) |

---

### Batch 17: SPY Tilt Score Normalization [Merged PR #60]
**PR #60 (CI: ✅ merged 2026-05-12)**

| Change | Rationale | Status |
|--------|-----------|--------|
| **Add `score_floor`/`score_ceiling` to `SpyTiltStrategy`** | Composite per-symbol score = (A1+A2+B2)/3; A2/B2 abstain ~98% of bars, so universe-average peaks near ~0.30. Without rescaling the tilt is stuck at ~55% SPY — useless as an exposure manager. `score_ceiling=0.30` maps the realistic range to the full 50-100% band. | ✅ |
| **Emit score distribution in backtest JSON** | `spy_tilt.score_distribution` (min/median/max) so we can tune `score_ceiling` empirically from real runs | ✅ |
| **6 new tests** | normalization no-op default, ceiling compression, clamping above/below, floor offset | ✅ (576 total) |

---

### Batch 16: v4 Tuning — A2 Fix + Universe Narrowing [2026-05-12]
**PR #59 (in progress)**

| Change | Rationale | Status |
|--------|-----------|--------|
| **Paginate Finnhub earnings fetch** in 90-day chunks | Root cause of A2's 9 trades: free tier caps `/calendar/earnings` at 3-month range. Single 1460-day call silently truncated. Now 16 chunks × 11 symbols = ~176 API calls. | ✅ |
| **Narrow A1 universe to 11 symbols** | Removed JNJ (-0.47), PEP (-0.53), PFE (-0.60), PG (-0.40), UNH (-0.11), KO (marginal +0.24). Retained: AAPL MSFT GOOGL (XLK), JPM BAC GS (XLF), XOM CVX (XLE), AMZN HD TSLA (XLY). | ✅ |
| **Update etheratrading.md** with v3 findings + v4 decisions | Documentation sync | ✅ |

---

### Batch 15: Phase B — SpyTiltStrategy (Exposure Manager) [Merged PR #58]
**PR #58 (CI: ✅ merged 2026-05-12)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| `SpyTiltStrategy` | `src/ai_agent/backtest/spy_tilt.py` | ✅ | Pre-computes avg composite score across universe per date; maps score → SPY allocation fraction `[min_alloc, max_alloc]`; rebalances only when gap ≥ 5% |
| `FractionalSignalStrategy` | `src/ai_agent/signals/strategy_adapter.py` | ✅ | Per-stock variant: deploys `score × cash` (0.33 → 33%, 0.67 → 67%, 1.0 → 100%) instead of all-in binary |
| SPY tilt backtest run | `scripts/run_all_backtests.py` | ✅ | `SPY_tilt_50_100` run added (50-100% SPY allocation band) |
| Tests | `tests/backtest/test_spy_tilt.py`, `tests/signals/test_strategy_adapter.py` | ✅ | 30 new tests; total 570 passing |

---

### Batch 14: Phase A — CompositeFactorSignal + Strategic Pivot [Merged PR #57]
**PR #57 (CI: ✅ merged 2026-05-12)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| `CompositeFactorSignal` | `src/ai_agent/signals/composite.py` | ✅ | Weighted-average blender; continuous score [0,1]; custom weights + name suffix; 23 tests |
| Kill A3/B5 | `signals/__init__.py`, `scripts/backtest_signal.py` | ✅ | Removed from public API + CLI registry; source files archived |
| v3 backtest rewrite | `scripts/run_all_backtests.py` | ✅ | B2 reverted to 3-month streak; A1/A2 kept at v2 thresholds; composite run added |
| Tests | `tests/signals/test_composite.py` | ✅ | 23 tests; full suite 540+ passing |

---

### Batch 13: v3 Backtest Results (Real Data, 2022-2026) [2026-05-12]
**Workflow run on main after PR #57 merge**

| Signal | Sharpe | CAGR | MaxDD | Alpha | Trades | Verdict |
|--------|--------|------|-------|-------|--------|---------|
| **SPY (benchmark)** | **0.99** | **16.6%** | **-19.0%** | — | — | — |
| A1 Sector RS | 0.68 | 5.4% | -9.4% | -11.2% | 720 | Real signal; defensives drag it down |
| A2 PEAD | 0.43 | 0.2% | -0.4% | -16.4% | **9** | **Data starvation (fixed in v4)** |
| B2 Analyst Rev | 1.16 | 0.9% | -0.5% | -15.7% | **12** | Best per-trade quality; too sparse |
| Composite equal | 0.71 | 5.7% | -9.4% | -10.9% | 732 | Dominated by A1 (A2/B2 near-zero) |
| **SPY Tilt 50-100%** | *pending v4* | | | | | First run pending |

**Key insights from v3**:
1. A2 fired only 9 times in 4 years across 17 symbols — confirmed Finnhub API truncation bug (3-month limit)
2. B2's 1.16 Sharpe on 12 trades is *directionally* valid — GOOGL, AAPL, TSLA all worked when it fired
3. A1's composite includes JNJ/PEP/PFE/PG which reliably lose; removing them is the highest-ROI fix
4. Composite ≈ A1/3 because A2/B2 inject zeros on ~98% of bars → not truly a multi-factor blend yet

---

### Batch 13 (old): v2 Backtest Validation + Strategic Pivot Decision [2026-05-11]
**Two real-data backtest runs against SPY 2022-2026**

| Run | Window | Universe | Key Finding |
|-----|--------|----------|-------------|
| **v1** | 2024-2026 (2yr bull) | 17 large-caps | SPY 1.14 Sharpe; 0/5 signals beat. A1 overtrading (1,112 trades). B2 highest at 1.51 Sharpe but sparse. A3 only UNH fired. B5 zero trades. |
| **v2** | 2022-2026 (4yr) | 17 LC + 8 mid-cap (A3) + 6 high-short (B5) | SPY 1.02 Sharpe. A1 trades dropped to 722 (good). B2 degraded to 0.75 with relaxation (v1 was better). A3 zero data (dynamic CIK broken). B5 catastrophic (-0.90 Sharpe, -99% MaxDD on BYND). |

**Verdict**: 0/5 signals have positive alpha. Selective signal approach won't beat SPY at retail scale.

**Strategic decision (user-confirmed 2026-05-11)**: Pivot from alpha discovery to **disciplined exposure manager**. Combine surviving signals (A1, A2, B2) into composite factor blend driving SPY allocation tilt 50-150%. See top-of-doc strategic pivot section.

---

### Batch 12: Unified Real-Data Backtest Infrastructure [Merged PR #56]
**PR #56 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Unified backtest script | `scripts/run_all_backtests.py` | ✅ | Pulls 2y of yfinance OHLCV + short interest, Finnhub earnings + recs, SEC EDGAR Form 4; runs A1/A2/B2/A3/B5 against same 17-symbol universe + SPY benchmark; writes `backtest_results.json` |
| GitHub Actions workflow | `.github/workflows/signal-backtests.yml` | ✅ | `workflow_dispatch` + monthly cron; uploads `backtest_results.json` artifact (90-day retention); prints summary table per run |
| Shared data fetch | (inside script) | ✅ | One yfinance call covers prices + sector ETFs + benchmark; one Finnhub pass covers earnings + recs; one SEC pass covers all CIKs — eliminates redundant network for cross-signal validation |

**Validates the 5 shipped signals end-to-end on real market data.** Needs `FINNHUB_API_KEY` secret. First run produces portfolio Sharpe/CAGR/alpha-vs-SPY + per-symbol breakdowns for every signal in a single JSON artifact.

---


**PR #55 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal implementation | `src/ai_agent/signals/short_interest.py` | ✅ | `ShortInterestMomentumSignal` — long when `short_percent_of_float >= 15%` AND 20d return `>= 3%`; avoids falling-knife trap |
| yfinance injection helper | `src/ai_agent/signals/runner.py` | ✅ | `_inject_short_interest()` + call in `backtest_signal()`; yfinance `shortPercentOfFloat`; try/except → default 0.0 offline |
| `__init__.py` export | `src/ai_agent/signals/__init__.py` | ✅ | `ShortInterestMomentumSignal` added to public API |
| CLI registration | `scripts/backtest_signal.py` | ✅ | `short_interest_momentum` choice in `REGISTRY` |
| Test suite | `tests/signals/test_short_interest.py` | ✅ | 19 tests across 8 classes (squeeze setup, low short, negative momentum, flat momentum, exact thresholds, custom params, insufficient history, missing data, attributes) |

**Fifth real signal through C1.** Squeeze-setup logic: short interest as squeeze fuel + price momentum as trigger. Data source: yfinance `shortPercentOfFloat` — no FINRA REGSHO parser needed; NYSE/NASDAQ publish snapshot ~twice monthly.

---

### Batch 10: A3 Insider Buying (Form 4) Signal [Merged PR #54]
**PR #54 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal implementation | `src/ai_agent/signals/insider_buying.py` | ✅ | `InsiderBuyingSignal` + `InsiderBuy` dataclass; long when ≥2 distinct officers/directors buy ≥$50k combined within 90d; filters code==P, direct==D, officer OR director |
| SEC EDGAR client | `src/ai_agent/data/sec_edgar_source.py` | ✅ | `SecEdgarSource` — no API key; User-Agent with email required (SEC policy); fetches submissions JSON + parses Form 4 XML `nonDerivativeTransaction` rows |
| EDGAR injection helper | `src/ai_agent/signals/runner.py` | ✅ | `_inject_insider_events()` + `SYMBOL_TO_CIK` Phase-1 dict (30 large-caps); wired into `backtest_signal()` alongside A1/A2/B2 injectors |
| `__init__.py` export | `src/ai_agent/signals/__init__.py` | ✅ | `InsiderBuy`, `InsiderBuyingSignal` added to public API |
| CLI registration | `scripts/backtest_signal.py` | ✅ | `insider_buying` choice in `REGISTRY` |
| Test suite | `tests/signals/test_insider_buying.py` | ✅ | 31 tests across 8 classes (sufficient buying, single insider, low value, stale events, non-buy codes, indirect ownership, 10%-owner exclusion, custom thresholds, empty data, attributes) |

**Fourth real signal through C1.** Based on Cohen, Malloy & Pomorski (2012) insider buying anomaly. SEC EDGAR free API integrated via `_inject_insider_events()`. Phase-1 CIK map hardcoded for 30 large-caps; dynamic lookup is Phase-2 follow-up.

---

### Batch 8: A2 Post-Earnings Drift (PEAD) Signal [Merged PR #52]
**PR #52 (CI: ✅ passed 2026-05-11)**

| Feature | Files | Status | Notes |
|---------|-------|--------|-------|
| Signal implementation | `src/ai_agent/signals/pead.py` | ✅ | `PostEarningsDriftSignal` + `EarningsEvent` dataclass; long when earnings surprise ≥ threshold within lookback/holding windows |
| Finnhub injection helper | `src/ai_agent/signals/runner.py` | ✅ | `_inject_earnings_events()` — fetches `/calendar/earnings` via existing `FinnhubSource`, mirrors `_inject_sector_prices()` pattern |
| `__init__.py` export | `src/ai_agent/signals/__init__.py` | ✅ | `EarningsEvent`, `PostEarningsDriftSignal` added to public API |
| CLI registration | `scripts/backtest_signal.py` | ✅ | `post_earnings_drift` choice in `REGISTRY` |
| Test suite | `tests/signals/test_pead.py` | ✅ | 20 tests across 8 classes (surprise thresholds, windows, zero-consensus guard, multi-event, empty list) |

**Second real signal through C1.** Based on Bernard & Thomas (1989/1990) PEAD anomaly. FinnhubSource wrapper reused (no new deps).

---

## 🚀 Roadmap — v4 Tuning + Exposure Manager Product

### Phase A: Composite Factor Blend [✅ SHIPPED — PR #57]
| Task | Priority | Status |
|------|----------|--------|
| Kill A3 + B5 — remove from registry | P0 | ✅ Done |
| Revert B2 to `min_consecutive_months=3` | P0 | ✅ Done |
| Build `CompositeFactorSignal` | P0 | ✅ Done |
| Backtest composite vs SPY | P0 | ✅ Done (v3 results: 0.71 Sharpe, -10.9% alpha) |

### Phase B: Exposure Manager Core [✅ SHIPPED — PR #58]
| Task | Priority | Status |
|------|----------|--------|
| `FractionalSignalStrategy` — score-proportional position sizing | P0 | ✅ Done |
| `SpyTiltStrategy` — SPY allocation 50-100% (backtest) / 50-150% (live w/ margin) | P0 | ✅ Done |
| SPY tilt backtest run in v3 script | P0 | ✅ Done (first results pending v4 run) |

### Phase B.2: Data Quality Fixes [✅ DONE — PRs #59/#60/#61]
| Task | Priority | Status |
|------|----------|--------|
| Fix A2 data starvation: paginate earnings fetch in 90-day chunks | P0 | ✅ Done (#59) — but free Finnhub still lacks deep history; A2 effectively data-limited |
| Narrow A1 universe: remove defensive/pharma (6 symbols) | P0 | ✅ Done (#59) — Sharpe 0.68 → 0.90 |
| Fix SPY tilt near-constant allocation (score normalization) | P0 | ✅ Done (#60) — tilt now swings 50-100% |
| Throttle Finnhub to free-tier rate limit | P0 | ✅ Done (#60) — A2/B2 data restored |
| Reconciliation: skip gracefully when T212 unconfigured | P1 | ✅ Done (#61) |
| v4 in-sample backtest (2022-2026) | P0 | ✅ Done — SPY Tilt Sharpe 1.14 vs SPY 0.99 (later shown period-specific — see Batch 21) |
| Out-of-sample backtest (2015-2019) | P0 | ✅ Done (#62 env override) — **SPY Tilt does NOT generalize** (Sharpe 0.51 vs SPY 0.73, CAPM α −1.75%). A1 alone holds up (+1.7% CAPM α). See Batch 21. |

### Phase B.3: Exposure Manager Product UI [⏸ PAUSED — see Batch 21]
The breadth-based SPY tilt failed out-of-sample, so the dashboard/digest product is on hold pending a directional decision (low-beta sleeve vs regime-gated tilt vs accept constant exposure). Tilt-engine + ExposureSnapshot plumbing is shipped (#62/#63) and reusable for whatever we pick.
| Task | Priority | Status |
|------|----------|--------|
| Tilt-engine + ExposureSnapshot + digest wiring | P0 | ✅ Shipped (#62/#63) — kept regardless of direction |
| `app/tilt/page.tsx` dashboard + API route | P1 | ⏸ Paused — don't build UI around a non-robust strategy |
| Directional decision: (a) low-beta sleeve / (b) regime-gated tilt / (c) constant exposure | P0 | Pending user call |
| Regime-gated exposure backtest (if (b)) | P1 | Pending |

### Phase C: Discipline + Automation Features [Week 3+]
- Tax-loss harvesting suggestions
- Automatic rebalancing alerts
- Cost-basis tracking integration
- Behavioral coaching (delayed trades, cooldown periods)

### Killed/Deprioritized
- **A3 (Insider Buying)**: Dynamic CIK lookup broken; even when fixed, mid-cap insider data sparse. Archive code, revisit if paid Form 4 feed (InsiderInsights, OpenInsider) becomes affordable.
- **B5 (Short Squeeze)**: Catastrophic falling-knife trap (-0.9 Sharpe, -99% MaxDD on BYND). Signal logic fundamentally flawed without a proper trend filter. Archive.
- **B1 (Options Flow)**: Paid feed required; deprioritized until exposure manager ships.
- **T212 / MarketWatch / Twitter / StockTwits / Dark Pool**: All rejected (low SNR or paid).

---

### Phase B: Native iOS [Decision Gate]
**Blocker**: Requires 2-week PWA adoption data (install rate, daily active users, retention).

**Scope if approved**:
- Xcode project targeting iOS 15.4+
- ORCA (in-app trading interface) parity with PWA
- Push notifications via APN (not web-push)
- Home screen persistence, biometric auth

**Decision**: Check adoption metrics end of May 2026; greenlight only if DAU >50% of installs.

---

### Phase C: Broker Integration (Out of Scope, Q3+ 2026)
- Order submission to Alpaca / Interactive Brokers
- Account state sync (positions, buying power)
- Trade confirmation flow
- Requires full compliance / audit trail

---

## 👥 Team Structure

| Role | Name | Responsibilities | Tools |
|------|------|------------------|-------|
| **Lead (Design & Architecture)** | Claude (Opus 4.7) | System design, PR reviews, decision gates, docs, context preservation | Anthropic API |
| **Implementation & Distribution** | Claude (Sonnet 4.6) | Feature coding, bug fixes, testing, push-to-staging | Anthropic API |
| **Background Development** | Tiger teams (Sonnet 4.6) | Parallel feature branches, hotfixes, infrastructure automation | Anthropic API |

**Daily workflow**:
1. **Opus** reviews daily sync (this file) and pending PRs; decides next shipment batch
2. **Sonnet** picks up approved batch, codes features, runs tests locally, opens PR
3. **Tiger teams** support parallel work (e.g., alternate signal implementations while main branch ships mobile UI)
4. **Daily standup**: 15min sync using this file; context preserved across sessions via `/root/.claude/projects/` transcript

---

## 📋 Daily Sync Template

### Status
- **Last PR shipped**: PR #56 (unified real-data backtest infra) — merged & live
- **Active PRs**: Strategic pivot v3 cleanup (in progress)
- **Blocked by**: nothing — strategic direction confirmed by user 2026-05-11
- **In flight**: Phase A composite factor blend (kill A3/B5, revert B2, build CompositeFactorSignal)

### Metrics (as of 2026-05-11)
- **LLM usage (7d)**: $X.XX (last check: dashboard live, waiting for first cron cycle)
- **Signal backtests**: v1 + v2 real-data runs complete; 0/5 signals beat SPY
- **Strategic conclusion**: Pivot to composite factor blend + exposure manager (see top of doc)
- **PWA installs**: Tracking via web push subscriptions (baseline: not yet measured)
- **Approval surface**: Telegram + PWA both ready

### Blockers
- None currently; strategic direction confirmed

### Next Batch — v3 Strategic Pivot
**Phase A (this week)**: Composite factor blend
1. Kill A3 + B5 from registry (archive code in place)
2. Revert B2 to `min_consecutive_months=3` (v1 config had Sharpe 1.51)
3. Build `CompositeFactorSignal` — continuous 0.0-1.0 score blending A1+A2+B2
4. Convert `SignalStrategy` to fractional position sizing
5. Backtest composite vs SPY — the real test of whether the blend has edge

**Phase B (next week)**: Tilt-to-SPY exposure manager
- 50-150% allocation bounds (no leverage by default)
- Kelly sizing capped at 100%
- Daily Telegram tilt digest

---

## 🛠️ Technical Notes & Glossary

### Tiered LLM Routing
- **Haiku** (cheap, fast): Screening, classification, simple decisions
- **Opus** (expensive, powerful): Deep analysis, synthesis, design
- **Sonnet** (balanced): Implementation, testing, distribution
- **Cost reduction**: 65–75% vs. uniform Opus usage (screened 80% of proposals by Haiku, only complex ones to Opus)

### Prompt Caching
- Server-side cache of repeated system prompts / context
- Reduces token usage for multi-turn proposal analysis
- Integrated into daily digest flow

### Signal Validation (C1)
- **Backtest**: Multi-year, daily bar data, sharpe >0.5 gate
- **Shadow**: 2 weeks live production data, NO money deployed, only tracking
- **Live**: After shadow passes, real capital deployed

### Web Push vs. Telegram
- **Telegram**: Synchronous, user-initiated check-in (click message link)
- **Web Push**: Asynchronous, browser-initiated notification (arrives proactively)
- **Both run in parallel**: User can approve from either channel

### Responsive Design Breakpoints
- `<sm` (mobile, <640px): Card list, hamburger nav, sticky-bottom actions
- `>=sm` (tablet/desktop, ≥640px): Table grid, top nav, inline buttons

### PWA Capabilities
- **Installable**: Desktop, iOS, Android
- **Offline**: Cache-first shell (pages), network-first API (real-time)
- **Notifications**: Web Push API (push event → notificationclick handler)
- **Icons**: Auto-generated at build time from `branding/sigil.svg` (one-file update)

### Daily Operations Schedule
- **Daily agent loop**: `06:30 UTC, Mon–Fri` (US pre-market) — `.github/workflows/daily.yml`
  - Entry: `python -m ai_agent.loop.daily_loop`
  - Steps: init DB → load watchlist → halt check → ingest bars → build T212 client → run Claude agent → risk-rail filter → persist proposals → send Telegram digest
  - Manual trigger: GitHub Actions `workflow_dispatch` with optional `--dry-run`
  - Local trigger: `python -m ai_agent.loop.daily_loop --dry-run`
- **Daily digest (cost + proposals)**: shares the same cron; pushes to Telegram + web-push
- **Macro regime snapshot**: `.github/workflows/macro-regime.yml` (separate cron, refreshes regime classifier daily)
- **Shadow MTM**: `.github/workflows/shadow-mtm.yml` (marks-to-market shadow positions for validation accuracy)

### Signal Source Research (Lead Architect Notes — 2026-05-11)

**Constraint**: The agent ingests only **programmatic, machine-readable** signal sources. Video/audio channels (e.g., JdubTrades_Telegram) cannot be parsed natively — would need transcription pipeline or manual screenshot OCR.

**Tier 1 — On Roadmap (free or already provisioned)**
| Signal | Source | Edge basis |
|--------|--------|------------|
| A2: Post-earnings drift (PEAD) | Finnhub (provisioned) | Earnings surprise × trend persistence — academic anomaly (Bernard & Thomas) |
| A3: Insider Form 4 | SEC EDGAR (free) | Officer/director buys precede outsized returns (Cohen, Malloy, Pomorski) |
| B2: Analyst estimate revisions | Finnhub `/stock/recommendation` (free) | 3+ consecutive upward EPS revisions → 3–12mo outperformance (Hawkins et al.) |
| B5: Short interest + momentum | yfinance `shortPercentOfFloat` (free) | High short float + positive 20d momentum = squeeze setup |
| B1: Options flow | Polygon/Tradier (paid, opt-in) | Unusual call/put volume detects institutional positioning before price moves |

**Tier 2 — Considered, deprioritized**
| Source | Reason to skip |
|--------|----------------|
| Twitter/X sentiment | API gated behind $100+/mo paywall, coverage degraded |
| StockTwits | Free but high retail noise, low signal-to-noise |
| Dark pool / block trades | All quality sources paid ($300+/mo) |
| Bloomberg ESI | Enterprise pricing |
| 13F institutional positioning | 45-day filing lag limits short-term value (parking lot for future) |

**Tier 3 — Manual / external channels**
| Source | Status |
|--------|--------|
| External Telegram trading channels (e.g., JdubTrades) | Manual paste-and-analyze; video-only content not parseable. Future: build inbound webhook endpoint accepting structured payload (symbol, side, levels, source tag) |
| Discord / private Slack signal rooms | Same as above — manual interim, webhook future |

---

## 📝 New Business Requirements — 2026-05-17

Recorded from the product owner. Not yet scheduled or designed — captured here
as the source of truth for upcoming work.

### BR-1: Per-Proposal Risk Score  ✅ Shipped (Batch 38)
Every trade proposal must carry a **risk score of 1–5** (1 = lowest risk,
5 = highest risk) together with a short **reason** explaining that score.

- Surface it wherever proposals appear: the `/proposals` list + detail page,
  the mobile approval UI, and the daily digest (Telegram + web-push).
- Derive the score from measurable inputs — e.g. volatility/ATR, position
  size vs NAV, instrument liquidity, sector concentration, macro regime.
  Exact rubric TBD.
- Persist the score + reason on the `Proposal` record so decisions remain
  auditable after the fact.

### BR-2: Market Leaders & Emerging-Company Tracker  🚧 In progress (Batch 39 — 13F tracker)
A **separate section/page**, distinct from the watchlist flow, that tracks
market leaders and new/emerging companies — including **IPOs**.

- For each tracked opportunity, produce a proposal covering **what** to invest
  in and **when** (entry timing — e.g. post-IPO volatility window, lock-up
  expiry).
- Track the **channels/sources** used to follow notable leaders (e.g. Elon
  Musk, Warren Buffett) — X/Twitter accounts, Berkshire shareholder letters,
  13F filings, etc. — so the agent can monitor them as signal inputs.
- Scope, data sources, and ingestion mechanism TBD.

---

## 📍 Outstanding Items

| Item | Status | Notes |
|------|--------|-------|
| Official sigil SVG | Pending from designer | Placeholder `branding/sigil.svg` ships; replace file once received, rebuild icons |
| A1 real-data backtest | Pending (network access required) | Run `scripts/run_a1_backtest.py` when outbound network available; synthetic run confirmed harness works |
| Manual signal ingestion API | Backlog | No inbound API yet. Spec: `POST /api/proposals/manual` with `{symbol, side, entry, stop, target, rationale, source}` — flows through same approval UI. ~3hr Sonnet sprint when prioritized |
| Video signal channel parsing | Out of scope | External channels publishing video-only (e.g., JdubTrades) cannot be parsed; interim is screenshot OCR or manual transcription |
| iOS Phase 2 decision | Blocked on metrics | Measure PWA adoption (2 weeks from P3 ship), DAU >50% of installs = greenlight |
| Broker integration (Alpaca / IB) | Q3+ 2026 | Out of scope for May release |

---

## 🔗 Key Files & Locations

### Configuration & Branding
- `branding/sigil.svg` — Logo (placeholder)
- `branding/colors.json` — Brand tokens (navy, teal, cream, app-bg)
- `.env.local` → `NEXT_PUBLIC_PUSH_VAPID_PUBLIC_KEY` — Web push public key (generated once, in env)

### Backend (Python)
- `src/ai_agent/bot/store.py` — Decision store (approvals)
- `src/ai_agent/db/models.py` — SQLModel schemas (Proposal, ShadowPosition, SignalBacktest, PushSubscription, etc.)
- `src/ai_agent/db/watchlist_store.py` — Watchlist CRUD
- `src/ai_agent/digest/daily_digest.py` — Daily summaries (Telegram + web-push)
- `src/ai_agent/signals/` — Signal framework (base, runner, reference, adapter)
- `src/ai_agent/macro/regime_detector.py` — VIX classifier

### Frontend (Next.js / React)
- `app/layout.tsx` — Root layout, SW registration, manifests
- `app/manifest.ts` — PWA manifest (typed)
- `app/llm-usage/` — Cost dashboard
- `app/proposals/` — Approval UI (desktop + mobile)
- `app/watchlist/` — Watchlist editor
- `app/regime/` — Macro regime display
- `app/components/Nav.tsx` — Main navigation (hamburger drawer)
- `public/sw.js` — Service worker (cache + push handlers)

### Scripts
- `scripts/generate-icons.mjs` — Rebuild icon suite
- `scripts/generate_vapid_keys.py` — One-time VAPID setup
- `scripts/backtest_signal.py` — Run signal backtest CLI

---

## 📊 PR History

| PR | Title | Status | Merged | Notes |
|----|-------|--------|--------|-------|
| #46 | Infrastructure batch (cost, digest, watchlist, regime) | ✅ | 2026-05-10 | Schema hotfix included |
| #47 | PWA P1 scaffold + icons | ✅ | 2026-05-10 | Icons generated, placeholder sigil |
| #48 | PWA P2 web push | ✅ | 2026-05-10 | Parallel Telegram delivery |
| #49 | PWA P3 mobile approval UI | ✅ | 2026-05-11 | CI passed, all tests ✅ |
| #50 | A1 Sector relative strength signal | ✅ | 2026-05-11 | First real signal through C1 harness; format-fix follow-up commit 129f177 |
| #51 | C1 harness fix + A1 backtest validation | ✅ | 2026-05-11 | Critical: `sector_prices` bug fixed; backtest report + reproducible script |
| #52 | A2 post-earnings drift signal | ✅ | 2026-05-11 | Second real signal through C1; PEAD anomaly; Finnhub injection via `_inject_earnings_events()` |
| #53 | B2 analyst revision momentum signal | ✅ | 2026-05-11 | Third real signal through C1; Hawkins et al. basis; Finnhub `/stock/recommendation` via `_inject_recommendations()` |
| #54 | A3 insider buying (Form 4) signal | ✅ | 2026-05-11 | Fourth real signal through C1; Cohen-Malloy-Pomorski basis; SEC EDGAR via `_inject_insider_events()` |
| #55 | B5 short interest + momentum signal | ✅ | 2026-05-11 | Fifth real signal through C1; squeeze-setup logic; yfinance `shortPercentOfFloat` data source |

---

## ✨ Done & Live

- ✅ LLM usage tracking & cost dashboard
- ✅ Daily digest (proposal summary + cost alert)
- ✅ Web push notifications (parallel to Telegram)
- ✅ Watchlist editor (DB-backed, no redeploy)
- ✅ Macro regime detector (VIX-based 30d history)
- ✅ Signal validation harness (C1, backtest → shadow → live gate)
- ✅ PWA full stack (installable, offline-capable, notifications)
- ✅ Mobile proposal approval UI (sticky-bottom, haptic, toast)
- ✅ A1 sector relative-strength signal (first real alpha through C1 harness)
- ✅ C1 harness critical fix (`sector_prices` injection — was producing 0 trades in production)
- ✅ A2 post-earnings drift signal (Bernard & Thomas PEAD anomaly via Finnhub)
- ✅ B2 analyst revision momentum signal (Hawkins et al. via Finnhub recommendation trends)
- ✅ A3 insider buying (Form 4) signal (Cohen-Malloy-Pomorski anomaly via SEC EDGAR)
- ✅ B5 short interest + momentum signal (squeeze-setup: high short float + positive 20d return)

---

**Maintained by**: Claude  
**Next review**: Daily (or after each PR merge)  
**Last sync**: 2026-05-11 (PR #55 B5 merged; 5 free alpha signals live; next batch → B1 Options Flow [user opt-in / paid feed required])
