import type { SelectedOffer } from "@/lib/types";
import { availabilityLabel, formatOdds, offerObservation, isActionable } from "@/lib/propSides";

function time(value?: string | null) {
  if (!value) return null;
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York",
  }).format(date) + " ET" : null;
}

export function SelectionPrice({ selection, gameTime }: { selection?: SelectedOffer; gameTime?: string }) {
  const label = availabilityLabel(selection ?? {}, gameTime);
  const current = label === "Live odds" || label === "Last known odds" ? selection?.odds : null;
  const usable = selection?.odds != null && isActionable(selection, gameTime);
  const reason = label === "Game started" ? "The game has started."
    : label === "Expired odds" ? "The stored price has expired."
    : !time(selection && offerObservation(selection)) ? "Sportsbook observation time is unknown."
    : label === "Last known odds" ? "Last-known prices are for reference only."
    : selection?.odds == null ? "No sportsbook price is available for this selection."
    : "This market is unavailable.";
  return <div className="my-2 space-y-1 text-xs text-muted">
    <p>{selection?.original_odds == null ? "Original price unavailable. No price was recorded when this selection was saved." : `Originally selected: ${formatOdds(selection.original_odds)}`}</p>
    {time(selection?.original_observed_at) && <p>Original observation: {time(selection?.original_observed_at)}</p>}
    <p>{current == null ? "Current price unavailable." : `Latest observed: ${formatOdds(current)}${selection?.price_change ? ` · ${selection.price_change}` : ""}`}</p>
    <p>Latest observation: {time(selection && offerObservation(selection)) ?? 'Unknown'}</p>
    <p>{label}{usable ? " · Actionable" : " · Excluded from estimates"}</p>
    {!usable && <p>{reason} Your original selection is kept.</p>}
  </div>;
}
