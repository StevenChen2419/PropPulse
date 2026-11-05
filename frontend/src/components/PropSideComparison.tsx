import { Check } from "lucide-react";
import type { Prop, PropSide, SelectedOffer } from "@/lib/types";
import { chooseOffer, formatOdds } from "@/lib/propSides";
import { trendSeasonLabel } from "@/lib/researchLabels";

interface Props {
  prop: Prop;
  selectedSide: PropSide;
  selection?: SelectedOffer;
  busy: boolean;
  onSelect: (side: PropSide) => void;
}

export function PropSideComparison({ prop, selectedSide, selection, busy, onSelect }: Props) {
  return (
    <>
      <div role="group" aria-label={`Choose a side for ${prop.player.name}`} className="mb-2 grid grid-cols-2 gap-2">
        {(["over", "under"] as const).map((side) => {
          const offer = chooseOffer(prop, side, selection) ?? (side !== selectedSide ? chooseOffer(prop, side) : undefined);
          const odds = offer?.odds ?? null;
          const selected = selectedSide === side;
          return (
            <button key={side} type="button" aria-pressed={selected} disabled={odds == null || busy}
              onClick={() => onSelect(side)}
              className={`min-w-0 rounded-xl border p-3 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${side === "over" ? selected ? "border-emerald-500 bg-emerald-50 ring-1 ring-emerald-500 focus-visible:ring-emerald-600" : "border-emerald-100 bg-emerald-50/40 hover:border-emerald-400 focus-visible:ring-emerald-600" : selected ? "border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500 focus-visible:ring-indigo-600" : "border-indigo-100 bg-indigo-50/40 hover:border-indigo-400 focus-visible:ring-indigo-600"}`}>
              <span className={`flex items-center justify-between text-xs font-semibold capitalize ${side === "over" ? "text-emerald-700" : "text-indigo-700"}`}>
                {side}<span className={`flex h-4 w-4 items-center justify-center rounded-full border ${selected ? "border-current" : "border-gray-300"}`}>{selected && <Check size={11} />}</span>
              </span>
              <span className="mt-2 block text-2xl font-bold tracking-tight text-gray-900">{offer?.line ?? (selected ? selection?.line : undefined) ?? prop.line}</span>
              <span className="block truncate text-[10px] text-gray-500">{offer?.sportsbook ?? (selected ? selection?.sportsbook : undefined) ?? prop.sportsbook}</span>
              <span className={`mt-1 block text-sm font-semibold ${side === "over" ? "text-emerald-700" : "text-indigo-700"}`}>{odds == null ? "Unavailable" : formatOdds(odds)}</span>
            </button>
          );
        })}
      </div>
      <p className="mb-4 text-[11px] text-gray-500">Select a side, then choose a sportsbook below.</p>
      {prop.trends && (!selection || selection.line === prop.trends.line) && (
        <div className="mb-3 rounded-xl border border-gray-100 p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-gray-700">History at {prop.trends.line}</p>
            <p className="text-[11px] text-gray-500">Eligible history avg {prop.trends.average}</p>
          </div>
          <div className="grid grid-cols-[48px_repeat(3,minmax(0,1fr))] gap-y-2 text-center text-xs">
            <span />
            {[prop.trends.l5, prop.trends.l10, prop.trends.season_window].map((window, index) => <div key={index} className="text-[10px] font-medium text-gray-400">
              <span className="block">{["L5", "L10", String(prop.trends!.season)][index]} · {window.games} games</span>
              {trendSeasonLabel(window) && <span className="block font-normal">{trendSeasonLabel(window)}</span>}
            </div>)}
            {(["over", "under"] as const).map((side) => (
              <div key={side} className="contents">
                <span className={`self-center text-left font-semibold capitalize ${side === "over" ? "text-emerald-700" : "text-indigo-700"}`}>{side}</span>
                {[prop.trends!.l5, prop.trends!.l10, prop.trends!.season_window].map((window, i) => {
                  const hits = side === "over" ? window.hits : window.decisions - window.hits;
                  return <div key={i} className={side === "over" ? "text-emerald-700" : "text-indigo-700"}>
                    <span className="block font-semibold">{window.decisions > 0 ? `${Math.round(hits / window.decisions * 100)}%` : "--"}</span>
                    <span className="text-[10px] text-gray-400">{hits}/{window.decisions}</span>
                  </div>;
                })}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[10px] text-gray-400">Historical hit rates · Pushes excluded · Not predictions</p>
          {prop.trends.competition_scope && <p className="mt-1 text-[10px] text-gray-400">{prop.trends.competition_scope}</p>}
        </div>
      )}
    </>
  );
}
