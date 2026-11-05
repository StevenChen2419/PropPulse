import type { ResearchHistory, TrendWindow } from "@/lib/types";
import { trendSeasonLabel } from "@/lib/researchLabels";

const EXCLUSION_LABELS: Record<string, string> = {
  unsupported_sport: "Unsupported sport",
  sport_mismatch: "Different sport",
  unsupported_source: "Unverified history source",
  invalid_date: "Invalid game date",
  at_or_after_prop: "At or after the selected game's start",
  future_game: "Future game",
  preseason: "Preseason",
  not_completed: "Game not completed",
  completion_unknown_today: "Same-day completion unconfirmed",
  missing_statistic: "Missing market statistic",
  invalid_statistic: "Invalid market statistic",
  duplicate_game: "Duplicate game",
};

export function historyMessage(history?: ResearchHistory | null): string {
  switch (history?.status) {
    case "no_history":
      return "No stored game history is available for this player.";
    case "no_valid_market_statistics":
      return "Stored game history has no valid statistics for this market.";
    case "excluded_history":
      return "Stored statistics are available, but none qualify as completed results before this prop's game.";
    default:
      return "No eligible historical results are available for this market.";
  }
}

export function ResearchHistorySummary({ history }: { history?: ResearchHistory | null }) {
  if (!history) return null;
  const exclusions = Object.entries(history.excluded_counts ?? {}).filter(([, count]) => Number.isFinite(count) && count > 0);
  const unknownExclusions = exclusions.filter(([reason]) => !EXCLUSION_LABELS[reason]).reduce((total, [, count]) => total + count, 0);
  return (
    <div className="mt-3 space-y-1 text-xs text-gray-500">
      {history.status !== "available" && <p>{historyMessage(history)}</p>}
      <p>{history.eligible_games} eligible historical results · {history.current_season_games} in the {history.selected_season} season</p>
      {exclusions.length > 0 && <p>Excluded results: {[
        ...exclusions.filter(([reason]) => EXCLUSION_LABELS[reason]).map(([reason, count]) => `${EXCLUSION_LABELS[reason]}: ${count}`),
        ...(unknownExclusions ? [`Other eligibility exclusions: ${unknownExclusions}`] : []),
      ].join(" · ")}</p>}
      {history.previous_season_games > 0 && <p>Recent samples may include previous seasons ({history.previous_season_games} eligible results).</p>}
      {(history.insufficient_l5 || history.insufficient_l10) && (
        <p>Limited sample: fewer than {history.insufficient_l5 ? "5" : "10"} eligible results. Available results are shown without filling missing games.</p>
      )}
      <p>Historical results against the displayed line; these are not predictions.</p>
      <p>{history.competition_scope}</p>
      {history.completion_scope && <p>{history.completion_scope}</p>}
    </div>
  );
}

export function HistoricalTrendSummary({ label, window }: { label: string; window: TrendWindow }) {
  const scope = trendSeasonLabel(window);
  return (
    <div className="min-w-0 bg-gray-50 p-3 text-center">
      <p className="text-lg font-bold text-gray-900">{window.hit_rate == null ? "-" : `${Math.round(window.hit_rate * 100)}%`}</p>
      <p className="mt-0.5 text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-xs text-gray-400">{window.hits}/{window.decisions} hits · {window.games} games</p>
      {scope && <p className="mt-1 text-xs text-gray-400">{scope}</p>}
    </div>
  );
}
