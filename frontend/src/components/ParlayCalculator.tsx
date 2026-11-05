"use client";
import { useEffect, useState } from "react";
import type { ParlayEstimate, ParlayEstimateRequest, SlipSelection } from "@/lib/types";
import { calculateParlay, decimalToAmerican, groupBySportsbook } from "@/lib/parlay";
import { formatOdds, getSelectionOdds } from "@/lib/propSides";
import { api } from "@/lib/api";

const money = (amount: number) => amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function hasSameGamePicks(items: SlipSelection[]): boolean {
  const events = items.filter((item) => item.odds_event_id).map((item) => item.player.sport + ":" + item.odds_event_id);
  return new Set(events).size < events.length;
}

function BookEstimate({ book, picks, stake, busy, assumption }: { book: string; picks: SlipSelection[]; stake: number; busy: boolean; assumption: number }) {
  const sameGame = hasSameGamePicks(picks);
  const unavailable = picks.some((item) => getSelectionOdds(item) == null);
  // Includes prices so refreshed offers invalidate the previous estimate; stake is local only.
  const requestKey = JSON.stringify({ items: picks.map((item) => ({ prop_id: item.id, side: item.side,
    sportsbook: item.selection?.sportsbook ?? item.sportsbook, line: item.selection?.line ?? item.line,
    odds: getSelectionOdds(item), event: item.odds_event_id ?? null })), assumed_correlation: assumption });
  const [remote, setRemote] = useState<{ key: string; result?: ParlayEstimate; error?: string } | null>(null);
  useEffect(() => {
    if (!sameGame || busy || unavailable) { setRemote(null); return; }
    let active = true;
    const controller = new AbortController();
    setRemote(null);
    const timer = setTimeout(() => {
      const parsed = JSON.parse(requestKey);
      const body: ParlayEstimateRequest = { assumed_correlation: parsed.assumed_correlation,
        items: parsed.items.map(({ prop_id, side, sportsbook, line }: ParlayEstimateRequest["items"][number]) => ({ prop_id, side, sportsbook, line })) };
      api.estimateParlay(body, controller.signal).then((result) => {
        if (active) setRemote({ key: requestKey, result });
      }).catch((error: unknown) => {
        if (active) setRemote({ key: requestKey, error: error instanceof Error ? error.message : "Could not estimate this parlay." });
      });
    }, 250);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [requestKey, sameGame, busy, unavailable]);

  const current = remote?.key === requestKey ? remote : null;
  const estimate = current?.result;
  const local = calculateParlay(picks, stake);
  const validStake = Number.isFinite(stake) && stake > 0;
  const decimal = sameGame ? estimate?.decimal ?? null : local.decimal;
  const payout = decimal == null ? null : decimal * stake;
  const tooLarge = payout != null && (!Number.isFinite(payout) || payout > Number.MAX_SAFE_INTEGER / 100);
  const reason = unavailable ? "A selected offer is unavailable. Remove or reselect this pick." : !validStake ? "Enter a stake greater than zero." : tooLarge ? "This combination exceeds the calculator limit."
    : sameGame ? current?.error ?? estimate?.reason ?? (estimate && (decimal == null || decimal <= 1) ? "An estimate is unavailable for these picks." : null) : local.reason;
  const loading = sameGame && !current;
  return <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
    <p className="text-xs font-semibold text-slate-700">{book} / {picks.length === 1 ? "Single" : picks.length + "-leg parlay"}</p>
    {sameGame && <div className="mt-2"><p className="text-sm font-bold text-amber-900">Same-game estimate</p><p className="text-xs font-semibold text-amber-800">Not a sportsbook quote</p></div>}
    {busy ? <p className="mt-2 text-xs text-slate-500">Updating picks...</p>
      : reason ? <p role="status" className="mt-2 text-xs text-amber-800">{reason}</p>
      : loading ? <p className="mt-2 text-xs text-slate-500">Calculating correlation estimate...</p>
      : decimal != null && payout != null ? <>
        <p className="mt-1 text-lg font-bold text-ink">{formatOdds(decimalToAmerican(decimal))} <span className="text-xs font-normal text-slate-500">({decimal.toFixed(3)} decimal)</span></p>
        <dl className="mt-2 grid grid-cols-2 gap-3 text-xs">
          <div><dt className="text-slate-500">Estimated profit</dt><dd className="mt-1 font-semibold text-emerald-700">{money(payout - stake)}</dd></div>
          <div><dt className="text-slate-500">Total return</dt><dd className="mt-1 font-semibold text-ink">{money(payout)}</dd></div>
        </dl>
      </> : null}
    {sameGame && <>
      {!busy && estimate && <div className="mt-2 space-y-1 text-[11px] text-slate-600">
        <p>{estimate.historical_pairs} historical pairs / {estimate.assumed_pairs} assumed pairs{estimate.min_shared_games != null ? " / At least " + estimate.min_shared_games + " shared games" : ""}</p>
        {!reason && estimate.independent_decimal != null && <p>Without correlation adjustment: {formatOdds(decimalToAmerican(estimate.independent_decimal))} ({estimate.independent_decimal.toFixed(3)} decimal)</p>}
        {estimate.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
      </div>}
      <p className="mt-2 text-[11px] leading-relaxed text-amber-800">This is an uncalibrated approximation. The sportsbook may price this combination differently or reject these picks.</p>
    </>}
  </div>;
}

export function ParlayCalculator({ items, busy }: { items: SlipSelection[]; busy: boolean }) {
  const [stake, setStake] = useState("10");
  const [assumption, setAssumption] = useState(0.15);
  const groups = groupBySportsbook(items);
  const sameGame = groups.some(([, picks]) => hasSameGamePicks(picks));
  return <section aria-label="Parlay calculator" className="border-t border-gray-100 bg-slate-50 p-3">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-ink">Payout calculator</h3>
      <label className="text-xs text-slate-600">
        {groups.length > 1 ? "Stake per sportsbook" : "Stake"}
        <input aria-label={groups.length > 1 ? "Stake per sportsbook" : "Stake"} type="number" min="0.01" step="0.01" inputMode="decimal"
          value={stake} onChange={(event) => setStake(event.target.value)}
          className="ml-2 w-20 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </label>
    </div>
    {groups.length > 1 && <p className="mt-2 text-xs text-slate-600">Separate bets by sportsbook. To build one parlay, choose the same sportsbook for every pick.</p>}
    {sameGame && <details className="mt-3 rounded-lg border border-slate-200 p-2 text-xs text-slate-600">
      <summary className="cursor-pointer font-semibold">Correlation assumptions</summary>
      <label className="mt-2 block">Assumed correlation: {assumption.toFixed(2)}
        <input aria-label="Assumed correlation" type="range" min="0" max="0.6" step="0.05" value={assumption}
          onChange={(event) => setAssumption(Number(event.target.value))} className="mt-2 block w-full" />
      </label>
      <p className="mt-2">Used when shared game history is insufficient. This is an assumption, not a measured correlation.</p>
      <p className="mt-1">For positively related stats, choosing the same side reduces the combined price. Opposite sides reverse the adjustment.</p>
    </details>}
    <div aria-live="polite" aria-busy={busy}>
      {groups.map(([book, picks]) => <BookEstimate key={book} book={book} picks={picks} stake={Number(stake)} busy={busy} assumption={assumption} />)}
    </div>
    <p className="mt-2 text-[11px] leading-relaxed text-slate-500">Return includes your stake, in the same currency. Estimates use current prices; final odds and eligible combinations are confirmed by the sportsbook. No boosts included.</p>
  </section>;
}
