import type { SlipSelection } from "./types";
import { getSelectionOdds } from "./propSides";

export function americanToDecimal(odds: number): number | null {
  if (!Number.isFinite(odds) || Math.abs(odds) < 100) return null;
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

export function decimalToAmerican(decimal: number): number | null {
  if (!Number.isFinite(decimal) || decimal <= 1) return null;
  return Math.round(decimal >= 2 ? (decimal - 1) * 100 : -100 / (decimal - 1));
}

function eventKey(item: SlipSelection): string | null {
  if (item.odds_event_id) return `${item.player.sport}:${item.odds_event_id}`;
  // Team labels mix abbreviations and names; only provider IDs establish
  // distinct events reliably enough to multiply their prices.
  return null;
}

export function calculateParlay(items: SlipSelection[], stake: number) {
  const blocked = (reason: string) => ({ reason, decimal: null, american: null, profit: null, payout: null });
  if (!items.length) return blocked("Add a pick to calculate a return.");
  if (!Number.isFinite(stake) || stake <= 0) return blocked("Enter a stake greater than zero.");
  if (new Set(items.map((item) => item.selection?.sportsbook ?? item.sportsbook)).size > 1) {
    return blocked("A parlay must use prices from one sportsbook.");
  }
  const events = new Set<string>();
  let decimal = 1;
  for (const item of items) {
    if (items.length > 1) {
      const key = eventKey(item);
      if (!key) return blocked("Event details are missing. Confirm parlay pricing at the sportsbook.");
      if (events.has(key)) return blocked("Same-game picks: get the combined price from the sportsbook. Individual odds cannot price this parlay.");
      events.add(key);
    }
    const odds = getSelectionOdds(item);
    const leg = odds == null ? null : americanToDecimal(odds);
    if (leg == null) return blocked("A selected price is unavailable. Choose another offer.");
    decimal *= leg;
  }
  const payout = decimal * stake;
  if (!Number.isFinite(payout) || payout > Number.MAX_SAFE_INTEGER / 100) return blocked("This combination exceeds the calculator limit.");
  return { reason: null, decimal, american: decimalToAmerican(decimal), payout, profit: payout - stake };
}

export function groupBySportsbook(items: SlipSelection[]): [string, SlipSelection[]][] {
  const groups = new Map<string, SlipSelection[]>();
  for (const item of items) {
    const book = item.selection?.sportsbook ?? item.sportsbook;
    groups.set(book, [...(groups.get(book) ?? []), item]);
  }
  return [...groups];
}
