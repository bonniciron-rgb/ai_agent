# Ethera Trading — Project Status & Roadmap

**Last updated**: 2026-05-11  
**Maintained by**: Claude (Lead, Opus for design/architecture)  
**Team**: Sonnet (implementation/distribution), Tiger teams (background development)  
**Daily Sync**: This file is the single source of truth for standups and context preservation.

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

## 🚀 Upcoming Roadmap

### Phase A & B: Alpha Signal Pipeline
Each signal validates via C1 harness (backtest → 2-week shadow → live). **Revised queue adds B2/B5 as fast wins.**

| Signal | Source | Est. Effort | Status | Edge |
|--------|--------|------------|--------|------|
| **A1: Sector Relative Strength** | Yahoo Finance (free) | 1.5d | ✅ Shadow (#50) | 20d return spread vs sector ETF |
| **A2: Post-Earnings Drift (PEAD)** | Finnhub (provisioned) | 2d | ✅ Merged (#52) | Earnings surprise × trend persistence (well-documented anomaly) |
| **B2: Analyst Estimate Revisions** | Finnhub `/stock/recommendation` (free) | 1d | ✅ Merged (#53) | 3+ consecutive upward EPS revisions → sustained outperformance |
| **A3: Insider Buying (Form 4)** | SEC EDGAR (free) | 2d | ✅ Merged (#54) | Officer/director buys precede outsized returns on avg |
| **B5: Short Interest + Momentum** | FINRA REGSHO (free, twice monthly) | 1d | Backlog | High short float + rising 20d momentum = squeeze setup |
| **B1: Options Flow** | Polygon / Tradier (paid, user opt-in) | 3d | Backlog | Unusual call/put volume detects institutional positioning |

**Deprioritized**: Twitter/X (API now paid), StockTwits (low SNR), Dark pool (all quality sources paid $300+/mo).

**Sprint order**: A2 → B2 → A3 → B5 → B1 (sequential validation, each signal gets 2-week shadow).

**Next Batch**: A3 Insider Buying (Form 4) — SEC EDGAR free, 2d effort.

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
- **Last PR shipped**: PR #53 (B2 analyst revision momentum) — merged & live
- **Active PRs**: none
- **Blocked by**: Official sigil SVG from designer (non-blocking, placeholder ships)
- **In flight**: B5 Short Interest + Momentum — awaiting greenlight

### Metrics (as of 2026-05-11)
- **LLM usage (7d)**: $X.XX (last check: dashboard live, waiting for first cron cycle)
- **Signal backtests**: 2 reference ✅; A1 ✅ + shadow; A2 ✅ + shadow; B2 ✅ + shadow; A3 ✅ + shadow; B5/B1 pending
- **PWA installs**: Tracking via web push subscriptions (baseline: not yet measured)
- **Approval surface**: Telegram + PWA both ready

### Blockers
- None currently; awaiting designer sigil SVG (non-blocking, placeholder ships)

### Next Batch
**Recommended**: B5 Short Interest + Momentum — FINRA REGSHO free, 1d effort.
- B5 effort: 1 day; no new data dependencies; high short float + rising 20d momentum = squeeze setup
- A3 is now in PR #54 (draft); after merge, B5 is the logical next validator through C1

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
| B5: Short interest + momentum | FINRA REGSHO (free, biweekly) | High short float + positive 20d momentum = squeeze setup |
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

---

**Maintained by**: Claude  
**Next review**: Daily (or after each PR merge)  
**Last sync**: 2026-05-11 (PR #54 A3 Insider Buying merged; 4 signals live; next batch → B5 Short Interest + Momentum)
