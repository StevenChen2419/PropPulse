import type { TrendWindow } from "./types";

export function trendSeasonLabel(window: TrendWindow): string | null {
  const scope = window.season_scope === "mixed_seasons" ? "Across seasons"
    : window.season_scope === "previous_seasons" ? "Previous seasons"
    : window.season_scope === "current_season" ? "Current season"
    : window.season_scope === "empty" ? "No eligible results" : null;
  return scope ? `${scope}${window.seasons?.length ? ` (${window.seasons.join(", ")})` : ""}` : null;
}
