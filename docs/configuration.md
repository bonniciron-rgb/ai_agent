# Configuration & Deployment

End-to-end setup for the AI trading agent. Once complete, the system runs autonomously every weekday at 06:30 UTC, sending trade proposals to Telegram for human approval.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│ GitHub Actions  │────▶│  Daily loop  │────▶│  Trading 212 │
│  06:30 UTC cron │     │ (Python)     │     │   (broker)   │
└─────────────────┘     └──────┬───────┘     └──────────────┘
                               │
                               ▼
                        ┌──────────────┐     ┌──────────────┐
                        │ Neon Postgres│◀───▶│   Vercel     │
                        │  (proposals, │     │  (webhook)   │
                        │  orders, …)  │     └──────┬───────┘
                        └──────────────┘            │
                                                    ▼
                                           ┌──────────────┐
                                           │   Telegram   │
                                           │  (approval)  │
                                           └──────────────┘
```

| Component | Provider | Cost |
|-----------|----------|------|
| Cron + repo | GitHub Actions | Free |
| Database | Neon Postgres | Free tier (3 GB) |
| Webhook host | Vercel | Free tier (100 GB/mo) |
| LLM | Anthropic Claude API | Pay-per-token (~$3/day cap) |
| Broker | Trading 212 | Free (demo + live) |

---

## Step 1 — Neon Postgres database

Stores trade proposals, orders, OHLCV bars, positions, and LLM usage.

1. Sign up at **https://neon.tech** (free tier, no credit card required).
2. Create a new project, name it `ai_agent`. Choose the region closest to your GitHub Actions runners (`us-east-2` is a safe default).
3. Open **Dashboard → Connection Details** and copy the **connection string**:
   ```
   postgresql://user:password@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Save this string as `DATABASE_URL` — you'll paste it into both Vercel (Step 3) and GitHub Secrets (Step 5).

The schema is created automatically on the first cron run via `init_schema()` in `daily_loop.py`. No manual migration needed.

---

## Step 2 — Vercel project

Hosts the Telegram webhook (`api/telegram_webhook.py`).

1. Sign up at **https://vercel.com** with your GitHub account.
2. **Add New Project → Import** `bonniciron-rgb/ai_agent`.
3. Framework Preset: **Other**.
4. Root Directory: `/` (default).
5. Build & Output Settings: leave blank.
6. Click **Deploy**. The first build takes ~2 minutes.
7. Copy the production URL (looks like `https://ai-agent-abc123.vercel.app`).

Vercel detects `api/telegram_webhook.py` automatically and serves it at `/api/telegram_webhook` using its Python runtime.

---

## Step 3 — Vercel environment variables

The webhook and dashboard need several env vars to function.

In Vercel → **Project → Settings → Environment Variables**, add:

| Name | Value | Source |
|------|-------|--------|
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF…` | [@BotFather](https://t.me/botfather) `/newbot` |
| `TELEGRAM_CHAT_ID` | `-1001234567890` | See "How to find chat ID" below |
| `DATABASE_URL` | `postgresql://…` | From Step 1 |
| `DASHBOARD_BASE_URL` | `https://ai-agent-abc123.vercel.app` | Your Vercel production URL (from Step 2) — **no trailing slash** |
| `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME` | `my_trading_bot` | Bot username (no `@`) — exposes the bot link in the dashboard login page |

Apply to all environments (Production / Preview / Development). After saving, **Redeploy** the latest deployment so the new vars take effect.

### How to find chat ID

1. Add the bot to your Telegram group/channel.
2. Send any message in the chat (`hello`).
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Find `"chat":{"id":-1001234567890,…}` in the JSON. Use the integer (with the leading `-` for groups/channels).

---

## Step 3b — Verify environment variables on Vercel

After setting the four env vars above, verify they're deployed:

1. Go to Vercel → **Deployments → Latest deployment → Logs**.
2. Send `/status` in your Telegram group.
3. If the bot replies, the webhook is working.
4. Send `/login` in your Telegram group.
5. The bot should reply with a clickable magic link. If it says `"Could not determine dashboard URL"`, then `DASHBOARD_BASE_URL` is not set correctly.

---

## Step 4 — Register the Telegram webhook

Tell Telegram to POST every update to your Vercel URL.

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_VERCEL_URL>/api/telegram_webhook"
```

Successful response:
```json
{"ok":true,"result":true,"description":"Webhook was set"}
```

**Verify**: send `/status` in your Telegram group. The bot should reply within a few seconds.

To inspect or remove the webhook later:
```bash
# inspect
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# remove (e.g., to switch back to polling for local testing)
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

---

## Step 4b — Dashboard login (desktop & mobile)

Once `DASHBOARD_BASE_URL` is configured, users can log in to the dashboard from any device.

**Login flow:**
1. Open `https://<your-vercel-url>` in a browser (desktop or mobile).
2. You'll see the login page with instructions.
3. Send `/login` to the bot via Telegram (from the same account configured as `TELEGRAM_CHAT_ID`).
4. The bot replies with a clickable magic link. The link is valid for 5 minutes.
5. Click the link from inside Telegram (it opens in your browser).
6. You're logged in — session cookie is valid for 7 days.

**On desktop:** You can have Telegram open in a separate window, click the link from the bot, and it opens your dashboard in the browser.

**On mobile:** The link opens directly in your browser.

---

## Step 5 — GitHub Secrets for the cron job

The daily loop on GitHub Actions needs broker, LLM, DB, and Telegram credentials.

Go to **Repo → Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value | Notes |
|--------|-------|-------|
| `DATABASE_URL` | `postgresql://…` | Same connection string from Step 1 |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | https://console.anthropic.com/settings/keys |
| `T212_API_KEY` | `xxxx-xxxx` | T212 app → Settings → API → Generate (start with **demo**) |
| `TELEGRAM_BOT_TOKEN` | Same as Vercel | |
| `TELEGRAM_CHAT_ID` | Same as Vercel | |

Then under **Variables** (different tab; not encrypted, can be changed without a redeploy):

| Variable | Value | Notes |
|----------|-------|-------|
| `T212_ENV` | `demo` | Switch to `live` when ready (after weeks of paper trading) |
| `TRADING_HALTED` | (empty) | Set to `1` to instantly pause trading without a code push |

### Kill switch

Three independent ways to halt trading:
1. **GitHub variable**: set `TRADING_HALTED=1` (takes effect on next cron run).
2. **Telegram command**: send `/halt` in the group (sets a flag in DB; daily loop checks it).
3. **Disable workflow**: GitHub → Actions → `daily-trade-loop` → ⋯ → Disable.

---

## Step 6 — End-to-end test

### A. Webhook smoke test
Send `/status` in your Telegram group → expect `(i) Status: agent running normally.`

If nothing happens:
- Check `getWebhookInfo` for a non-empty `last_error_message`.
- Check Vercel → Deployments → Logs for the function invocation.
- Confirm `TELEGRAM_CHAT_ID` matches the chat where you're sending the command.

### B. Cron dry-run
GitHub → **Actions → daily-trade-loop → Run workflow** → tick **dry_run: true** → Run.

Expected behaviour: workflow logs show portfolio NAV, agent iterations, proposal count, and `[dry_run] Would save N proposals` — no DB writes, no Telegram messages.

### C. First live cron run
1. Wait for 06:30 UTC on the next weekday.
2. Telegram group should receive 0–5 proposal messages with inline approval buttons.
3. Tap **✅ Approve** on one proposal — the bot edits the message to `✅ Proposal #N (TICKER) approved — submitting order.`
4. Verify in Trading 212's app that the order appears in the **Pending orders** tab.

---

## Watchlist configuration

The agent only analyses tickers in `watchlist.yaml` at the repo root.

Example:
```yaml
entries:
  - symbol: AAPL
    sector: Technology
    notes: Long-term AI play
  - symbol: MSFT
    sector: Technology
  - symbol: JPM
    sector: Financials
    tags: [dividend, large-cap]
```

`sector` is used by the **Sector cap** risk rail (max 30 % of NAV in one sector). Tickers without a sector are allowed through with a warning.

---

## Risk rails (hardcoded)

Defined in `src/ai_agent/risk/rails.py`. To change a limit, edit the constant at the top of the file and open a PR — they are intentionally not configurable via env vars.

| Constant | Default | Effect |
|----------|---------|--------|
| `POSITION_CAP_PCT` | 5 % | Max single-ticker notional as fraction of NAV |
| `ATR_STOP_MULTIPLIER` | 2 | Min stop distance = 2 × ATR-14 |
| `DAILY_TURNOVER_CAP_PCT` | 20 % | Max cumulative buy notional per day |
| `SECTOR_CAP_PCT` | 30 % | Max notional in a single sector |
| `COOLDOWN_DAYS` | 5 | Min trading days between sell and re-buy |

---

## Cost monitoring

| Item | Free? | Hard limit |
|------|-------|------------|
| GitHub Actions | 2 000 min/mo on free tier; daily run uses ~5 min | — |
| Neon Postgres | Free tier: 3 GB storage, 100 hr compute/mo | — |
| Vercel | Free hobby plan: 100 GB-hr/mo functions | — |
| Anthropic Claude | Pay-per-token | `LLM_DAILY_COST_CAP_USD=3.0` (in `Settings`) |

The agent stops calling Claude once `llm_daily_cost_cap_usd` is hit (tracked in the `llm_usage` table). Default cap is **$3/day** — adjust in `src/ai_agent/settings.py` if needed.

---

## Going from demo to live

1. Run on `T212_ENV=demo` for **at least 2–4 weeks**.
2. Review every approved proposal in the DB:
   ```sql
   SELECT symbol, side, quantity, limit_price, status, decided_at, decided_by
   FROM proposal
   ORDER BY created_at DESC LIMIT 50;
   ```
3. Run the backtest harness on the same period for an apples-to-apples Sharpe comparison.
4. When satisfied, generate a **live** T212 API key and update the `T212_API_KEY` secret + flip `T212_ENV` to `live`.
5. Start with a small NAV (£500–£1 000). Position cap (5 %) means max £25–£50 per trade.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Bot doesn't reply to `/status` | Webhook not registered or wrong URL | Re-run `setWebhook`, check `getWebhookInfo` |
| Cron fails with `KeyError: 'TELEGRAM_BOT_TOKEN'` | Secret not set | Add to GitHub Secrets, re-run |
| `psycopg.OperationalError: SSL connection has been closed` | Neon's autosuspend killed the idle connection | Already handled (`pool_pre_ping=True`) — retry the workflow |
| `403 Forbidden` from T212 | Demo key on live URL or vice versa | Match `T212_ENV` to the key's environment |
| All proposals blocked by ATR rail | `Bar` table empty for the ticker | Backfill OHLCV via `python -m ai_agent.data.backfill --symbol AAPL` |
| Telegram says "message is not modified" | Double-tap on a button | Harmless — message already updated |

---

## Local development

Run the daily loop against demo T212 + a local SQLite DB:

```bash
export DATABASE_URL="sqlite+pysqlite:///./local.db"
export TELEGRAM_BOT_TOKEN=<your-token>
export TELEGRAM_CHAT_ID=<your-chat-id>
export T212_API_KEY=<demo-key>
export ANTHROPIC_API_KEY=<your-key>

pip install -e ".[production,dev]"
python -m ai_agent.loop.daily_loop --dry-run
```

For unit tests (no API keys required — all external services mocked):
```bash
pytest -q
```
