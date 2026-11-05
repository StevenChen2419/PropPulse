import type { GameIdentity } from "./types";

/** Filter values distinguish canonical identity from compatibility-only keys. */
export function gameIdentityValue(game: GameIdentity): string {
  return game.event_id ? `event:${game.event_id}` : game.game_key ? `legacy:${game.game_key}` : "";
}

export function gameQuery(value: string): { event_id?: string; game_key?: string } {
  if (!value) return {};
  if (value.startsWith("legacy:")) return { game_key: value.slice(7) };
  if (value.startsWith("event:")) return { event_id: value.slice(6) };
  // Route segments without a legacy delimiter are Event IDs, including malformed
  // UUIDs: let API validation reject them rather than guessing another matchup.
  return value.includes("|") ? { game_key: value } : { event_id: value };
}

export function gameHref(game: GameIdentity): string {
  return `/games/${encodeURIComponent(game.event_id || game.game_key || "")}`;
}

export function decodeGameSegment(segment: string): string {
  // Router values may already be decoded. A legacy delimiter proves that the
  // compatibility key is present; decoding again could alter literal % escapes.
  if (segment.includes("|")) return segment;
  try { return decodeURIComponent(segment); } catch { return segment; }
}

export function propResearchHref(playerId: string, propId: string, selection?: { sportsbook: string; line: number; side?: string }): string {
  const params = new URLSearchParams({ prop_id: propId });
  if (selection) {
    params.set('sportsbook', selection.sportsbook); params.set('offer_line', String(selection.line));
    if (selection.side) params.set('side', selection.side);
  }
  return `/player/${encodeURIComponent(playerId)}?${params}`;
}

export function formatGameContext(game: GameIdentity & { game_time?: string | null }): string {
  const matchup = game.away_team && game.home_team ? `${game.away_team} @ ${game.home_team}` : "Game context unavailable";
  const value = game.scheduled_start_at || game.game_time;
  if (!value) return matchup;
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return matchup;
  return `${matchup} · ${new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short",
  }).format(date)}`;
}

/** Never expose API/database details or use errors to select a different subject. */
export function errorMessage(error: unknown, subject = "selection"): string {
  const status = typeof error === "object" && error !== null && "status" in error ? error.status : undefined;
  if (status === 400) return `This ${subject} request has invalid or conflicting selections. Please check the link.`;
  if (status === 404) return `This ${subject} could not be found. The selected identity has not been replaced.`;
  if (status === 409) return "This legacy selection is ambiguous. Choose a verified Event or an exact player prop.";
  if (status === 422) return `The ${subject} link is malformed. Please check its identifier.`;
  return `Could not refresh this ${subject}. Check your connection and try again.`;
}
