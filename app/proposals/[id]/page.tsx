import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { StatusPill } from "@/app/components/StatusPill";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { buildSparkline, computeIndicators } from "@/lib/indicators";
import {
  getOrderForProposal,
  getProposal,
  getProposalReasoning,
  getRecentBars,
  type Bar,
  type ProposalReasoning,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function ProposalDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const id = Number(params.id);
  if (!Number.isFinite(id) || id <= 0) notFound();

  const proposal = await getProposal(id).catch(() => null);
  if (!proposal) notFound();

  const [order, bars, reasoning] = await Promise.all([
    getOrderForProposal(id).catch(() => null),
    getRecentBars(proposal.symbol, 30).catch(() => [] as Bar[]),
    getProposalReasoning(id).catch(() => null as ProposalReasoning | null),
  ]);

  const indicators = computeIndicators(bars);
  const closes = bars.map((b) => Number(b.close));
  const limit = Number(proposal.limit_price);
  const sparkline = buildSparkline(
    closes,
    600,
    100,
    Number.isFinite(limit) ? limit : null,
  );

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            Proposal #{proposal.id}
          </h1>
          <a
            href="/proposals"
            className="text-sm text-zinc-500 hover:text-zinc-300"
          >
            ← Back
          </a>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <div className="flex items-baseline justify-between">
                <div>
                  <p className="font-mono text-2xl">{proposal.symbol}</p>
                  <p className="mt-1 text-sm text-zinc-400">
                    {proposal.side.toUpperCase()} {proposal.quantity} @{" "}
                    <span className="font-mono">${proposal.limit_price}</span>
                    {proposal.stop_price ? (
                      <>
                        {" · stop "}
                        <span className="font-mono">
                          ${proposal.stop_price}
                        </span>
                      </>
                    ) : null}
                  </p>
                </div>
                <StatusPill status={proposal.status} />
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-zinc-500">Created</dt>
                <dd>{new Date(proposal.created_at).toLocaleString()}</dd>
                <dt className="text-zinc-500">Expires</dt>
                <dd>{new Date(proposal.expires_at).toLocaleString()}</dd>
                <dt className="text-zinc-500">Confidence</dt>
                <dd>{proposal.confidence}</dd>
                <dt className="text-zinc-500">Decided at</dt>
                <dd>
                  {proposal.decided_at
                    ? new Date(proposal.decided_at).toLocaleString()
                    : "—"}
                </dd>
                <dt className="text-zinc-500">Decided by</dt>
                <dd>{proposal.decided_by ?? "—"}</dd>
              </dl>
            </div>

            <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                Rationale
              </h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-zinc-200">
                {proposal.rationale || "(no rationale recorded)"}
              </p>
            </div>

            {reasoning ? (
              <>
                <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
                  <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                    Why Claude proposed this
                  </h2>
                  <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-950 p-3 text-xs leading-5 text-zinc-300">
                    {reasoning.response_text ||
                      "(no assistant text — see full prompt below)"}
                  </pre>
                </div>

                <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
                  <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                    Token cost
                  </h2>
                  <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-4">
                    <Fact label="Model" value={reasoning.model} />
                    <Fact
                      label="Input tokens"
                      value={reasoning.input_tokens.toLocaleString()}
                    />
                    <Fact
                      label="Output tokens"
                      value={reasoning.output_tokens.toLocaleString()}
                    />
                    <Fact
                      label="Est. cost"
                      value={estimateCost(
                        reasoning.model,
                        reasoning.input_tokens,
                        reasoning.output_tokens,
                      )}
                    />
                  </dl>
                </div>
              </>
            ) : null}

            <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                Indicators (last 30 daily bars)
              </h2>
              {bars.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-500">
                  No bars stored for {proposal.symbol} yet.
                </p>
              ) : (
                <dl className="mt-3 grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-4">
                  <Fact
                    label="Latest close"
                    value={fmtNum(indicators.latestClose, 2)}
                  />
                  <Fact label="RSI(14)" value={fmtNum(indicators.rsi14, 1)} />
                  <Fact label="SMA(50)" value={fmtNum(indicators.sma50, 2)} />
                  <Fact
                    label="Vol vs 20d avg"
                    value={
                      indicators.volumeVs20Avg !== null
                        ? `${indicators.volumeVs20Avg.toFixed(2)}×`
                        : "—"
                    }
                  />
                </dl>
              )}
            </div>

            <div className="mt-6 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                30-day price
              </h2>
              {sparkline ? (
                <Sparkline geom={sparkline} />
              ) : (
                <p className="mt-3 text-sm text-zinc-500">
                  Not enough bars to draw a chart.
                </p>
              )}
            </div>
          </section>

          <aside>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
                Linked order
              </h2>
              {order ? (
                <dl className="mt-3 grid grid-cols-1 gap-y-2 text-sm">
                  <Fact label="Status">
                    <StatusPill status={order.status} />
                  </Fact>
                  <Fact label="Type" value={order.order_type} />
                  <Fact label="Quantity" value={order.quantity} />
                  <Fact
                    label="Limit"
                    value={order.limit_price ? `$${order.limit_price}` : "—"}
                  />
                  <Fact
                    label="Filled qty"
                    value={order.filled_quantity ?? "0"}
                  />
                  <Fact
                    label="Avg fill"
                    value={
                      order.avg_fill_price ? `$${order.avg_fill_price}` : "—"
                    }
                  />
                  <Fact
                    label="Broker ID"
                    value={order.broker_order_id ?? "—"}
                  />
                  <Fact
                    label="Submitted"
                    value={
                      order.submitted_at
                        ? new Date(order.submitted_at).toLocaleString()
                        : "—"
                    }
                  />
                </dl>
              ) : (
                <p className="mt-3 text-sm text-zinc-500">
                  No order linked yet.
                </p>
              )}
            </div>
          </aside>
        </div>
      </main>
    </>
  );
}

/** Estimate USD cost based on model pricing.
 * Opus 4: $15/M input, $75/M output.
 * Haiku 4: $1/M input, $5/M output.
 * Sonnet 4.6 (default): $3/M input, $15/M output.
 */
function estimateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
): string {
  let inputPricePerM = 3.0;
  let outputPricePerM = 15.0;
  const lower = model.toLowerCase();
  if (lower.includes("opus")) {
    inputPricePerM = 15.0;
    outputPricePerM = 75.0;
  } else if (lower.includes("haiku")) {
    inputPricePerM = 1.0;
    outputPricePerM = 5.0;
  }
  const cost =
    (inputTokens / 1_000_000) * inputPricePerM +
    (outputTokens / 1_000_000) * outputPricePerM;
  return `$${cost.toFixed(4)}`;
}

function Fact({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-zinc-500">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono">{children ?? value ?? "—"}</dd>
    </div>
  );
}

function fmtNum(n: number | null, digits: number): string {
  if (n === null || !Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function Sparkline({
  geom,
}: {
  geom: ReturnType<typeof buildSparkline> & object;
}) {
  return (
    <div className="mt-3">
      <svg
        viewBox={`0 0 ${geom.width} ${geom.height}`}
        preserveAspectRatio="none"
        className="h-24 w-full"
        role="img"
        aria-label="30-day price sparkline"
      >
        <path
          d={geom.path}
          fill="none"
          stroke="rgb(52 211 153)"
          strokeWidth="1.5"
        />
        {geom.priceLineY !== null ? (
          <line
            x1="0"
            x2={geom.width}
            y1={geom.priceLineY}
            y2={geom.priceLineY}
            stroke="rgb(244 114 182)"
            strokeWidth="1"
            strokeDasharray="4,3"
          />
        ) : null}
      </svg>
      <div className="mt-1 flex justify-between text-xs text-zinc-500">
        <span>min ${geom.min.toFixed(2)}</span>
        <span>max ${geom.max.toFixed(2)}</span>
      </div>
    </div>
  );
}
