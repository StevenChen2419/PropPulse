import type { RestWorkloadResearch, VerifiedRestContext, WorkloadWindow } from "@/lib/types";

function number(value: number | null, digits = 1): string {
  return value == null ? "Unavailable" : value.toFixed(digits);
}
function signed(value: number | null): string {
  return value == null ? "Unavailable" : `${value > 0 ? "+" : ""}${value.toFixed(1)} min`;
}
function date(value: string | null): string {
  if (!value) return "Unknown";
  // Dates in the contract are UTC instants; display the game calendar in Eastern time.
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "America/New_York" }).format(instant);
}
function range(start: string | null, end: string | null): string {
  return start && end ? `${date(start)} – ${date(end)}` : "No dated sample";
}
const CATEGORY: Record<string, string> = {
  back_to_back: "Back-to-back", short_rest: "Short rest", extended_rest: "Extended rest",
};
const EXCLUSIONS: Record<string, string> = {
  unsupported_sport: "Unsupported sport", player_mismatch: "Different player",
  conflicting_game_logs: "Conflicting game records", synthetic_identity: "Synthetic game identity",
  no_observed_statistics: "No observed statistics",
  unsupported_source: "Unverified source", sport_mismatch: "Different sport", invalid_date: "Invalid date",
  at_or_after_reference: "At or after reference time", at_or_after_prop: "At or after selected game",
  future_game: "Future game", completion_unknown_today: "Same-day completion unconfirmed",
  missing_game_identity: "Missing game identity", did_not_play: "Did not play",
  not_completed: "Not completed", preseason: "Preseason", duplicate_game: "Duplicate game",
  conflicting_duplicate: "Conflicting duplicate", invalid_minutes: "Invalid minutes",
};
function MinutesWindow({ label, window }: { label: string; window: WorkloadWindow }) {
  return <div className="min-w-0 rounded bg-gray-50 p-3">
    <dt className="text-xs font-medium text-gray-500">{label}</dt>
    <dd className="mt-1 text-lg font-semibold text-gray-900">{window.average_minutes == null ? "Unavailable" : `${number(window.average_minutes)} min`}</dd>
    <dd className="mt-1 text-xs text-gray-500">{window.games} of {window.observed_games} games with minutes{window.insufficient_sample ? " · Limited sample" : ""}</dd>
    <dd className="mt-1 text-xs text-gray-500">{range(window.date_start, window.date_end)}</dd>
    <dd className="mt-1 text-xs text-gray-500">{window.seasons.length ? `Seasons: ${window.seasons.join(", ")}` : "No season sample"}</dd>
  </div>;
}

function VerifiedRest({ verified }: { verified?: VerifiedRestContext | null }) {
  const status = verified?.status === "confirmed" ? "Confirmed" : verified?.status === "partial" ? "Partial coverage" : "Unknown";
  const player = verified?.last_confirmed_appearance;
  const team = verified?.last_completed_team_game;
  const exactMissed = verified?.confirmed_missed_games;
  return <div className="space-y-3 border-b border-gray-100 pb-4">
    <p className="text-xs text-gray-500">Participation and final-game evidence: <span className="font-semibold text-gray-700">{status}</span></p>
    <div className="grid gap-3 sm:grid-cols-2">
      <section aria-labelledby="player-rest-title" className="min-w-0 rounded border border-gray-100 p-3">
        <h3 id="player-rest-title" className="text-sm font-medium text-gray-800">Player rest</h3>
        <dl className="mt-2 space-y-2 text-xs text-gray-600">
          <div><dt>Last confirmed appearance in coverage</dt><dd className="mt-1 font-semibold">{player ? `${date(player.game_at)} · ${player.status === "confirmed" ? "Confirmed" : "Partial coverage"}` : "Unknown"}</dd></div>
          {player?.time_precision === "eastern_date" && <div><dt>Date precision</dt><dd className="mt-1">Eastern calendar date only; actual game time unavailable.</dd></div>}
          <div><dt>Player date gap / full intervening rest days</dt><dd className="mt-1 font-semibold">{player ? `${player.gap_days} / ${player.full_rest_days} days` : "Unknown"}</dd></div>
          <div><dt>Confirmed missed team games</dt><dd className="mt-1 font-semibold">{exactMissed != null ? `${exactMissed} · Confirmed` : verified?.partial_missed_games_lower_bound ? `At least ${verified.partial_missed_games_lower_bound} · Partial coverage` : "Unknown"}</dd></div>
        </dl>
        {verified && (verified.dnp_games > 0 || verified.inactive_games > 0) && <p className="mt-2 text-xs text-gray-500">Confirmed non-appearances: {verified.dnp_games} DNP · {verified.inactive_games} inactive.</p>}
      </section>
      <section aria-labelledby="team-schedule-title" className="min-w-0 rounded border border-gray-100 p-3">
        <h3 id="team-schedule-title" className="text-sm font-medium text-gray-800">Team schedule</h3>
        <dl className="mt-2 space-y-2 text-xs text-gray-600">
          <div><dt>Previous final team game in coverage</dt><dd className="mt-1 font-semibold">{team ? `${date(team.game_at)} · ${team.status === "confirmed" ? "Confirmed" : "Partial coverage"}` : "Unknown"}</dd></div>
          {team?.time_precision === "eastern_date" && <div><dt>Date precision</dt><dd className="mt-1">Eastern calendar date only; actual game time unavailable.</dd></div>}
          <div><dt>Team date gap / full intervening rest days</dt><dd className="mt-1 font-semibold">{team ? `${team.gap_days} / ${team.full_rest_days} days` : "Unknown"}</dd></div>
          <div><dt>Back-to-back if playing on reference date</dt><dd className="mt-1 font-semibold">{verified?.team_back_to_back == null ? "Unknown" : `${verified.team_back_to_back ? "Yes" : "No"} · Confirmed`}</dd></div>
        </dl>
      </section>
    </div>
    <p className="text-xs text-gray-500">Date gaps use Eastern calendar dates; full intervening rest days exclude the game dates. A player can miss a team game, so player rest and team rest can differ. Team context comes from dated membership; provider game identities do not establish an association with the selected Event.</p>
    {verified && <p className="text-xs text-gray-500">Unknown participation: {!player ? "Unknown" : `${verified.unknown_participation_games} games`} · Uncovered schedule: {!player ? "Unknown" : `${verified.uncovered_games} games`}{!verified.schedule_complete ? " · Partial coverage; counts may not describe the full schedule." : "."}</p>}
    {!verified || verified.status === "unknown" || !player ? <p className="text-xs text-gray-500">Confirmed player participation coverage is incomplete or unavailable. Missing logs do not establish DNP, inactive status, or zero missed games. Unknown and uncovered game counts are not established without a confirmed appearance baseline.</p> : null}
    {verified && <details className="text-xs text-gray-500">
      <summary className="cursor-pointer rounded py-1 font-medium text-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">Participation evidence &amp; coverage</summary>
      <div className="mt-2 space-y-2">
        <p>Sources: {verified.provenance.length ? verified.provenance.join(", ") : "No confirmed provider evidence"}</p>
        {verified.notes.map(note => <p key={note}>{note}</p>)}
      </div>
    </details>}
  </div>;
}

export function RestWorkloadSection({ data }: { data?: RestWorkloadResearch | null }) {
  if (!data) return null;
  const { coverage, rest, workload } = data;
  const excluded = Object.entries(coverage.excluded_counts).filter(([, count]) => count > 0);
  const known = excluded.filter(([reason]) => EXCLUSIONS[reason]);
  const other = excluded.filter(([reason]) => !EXCLUSIONS[reason]).reduce((total, [, count]) => total + count, 0);
  return <section aria-labelledby="rest-workload-title" className="mb-4 space-y-4 rounded-lg border border-gray-100 bg-white p-5">
    <div>
      <h2 id="rest-workload-title" className="font-semibold text-gray-800">Rest &amp; Workload</h2>
      <p className="mt-1 text-xs text-gray-500">Recorded game observations and derived context. No predictive model is used in these indicators.</p>
    </div>
    {data.status === "unsupported_sport" ? <p className="text-sm text-gray-600">Rest and workload research is currently available for NBA players only.</p> : <>
      <p className="text-xs text-gray-500">Reference: {data.reference.source === "event" ? "selected verified Event" : "research as of"} · {date(data.reference.at)} (Eastern)</p>
      <VerifiedRest verified={data.verified} />
      {!coverage.schedule_complete && <p className="rounded bg-amber-50 p-3 text-xs text-amber-900">Schedule coverage is incomplete. Recorded appearances do not establish a complete team schedule or full upcoming coverage.</p>}
      {data.status === "no_history" && <p className="text-sm text-gray-600">No eligible completed game observations. Recorded appearance rest and minutes remain unavailable.</p>}
      <div>
        <h3 className="mb-2 text-sm font-medium text-gray-700">Recorded appearances: derived rest context</h3>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          {[
            ["Days since last recorded game", number(rest.days_since_last_game, 0)],
            ["Recorded back-to-back", rest.back_to_back == null ? "Unknown" : rest.back_to_back ? "Yes" : "No"],
            ["Recorded games / 7 days", number(rest.games_in_7d, 0)],
            ["Recorded games / 14 days", number(rest.games_in_14d, 0)],
            ["Rest category", rest.category ? CATEGORY[rest.category] ?? "Unknown" : "Unknown"],
            ["Schedule density", rest.schedule_density == null ? "Unavailable" : `${number(rest.schedule_density, 2)} games/day`],
          ].map(([label, value]) => <div key={label} className="min-w-0 rounded bg-gray-50 p-3"><dt className="text-xs text-gray-500">{label}</dt><dd className="mt-1 font-semibold text-gray-900">{value}</dd></div>)}
        </dl>
        <p className="mt-2 text-xs text-gray-500">{rest.explanation}</p>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium text-gray-700">Observed minutes</h3>
        <dl className="grid gap-3 sm:grid-cols-3">
          <MinutesWindow label="Last 5 games" window={workload.l5} />
          <MinutesWindow label="Last 10 games" window={workload.l10} />
          <MinutesWindow label="Current season" window={workload.season} />
        </dl>
        <dl className="mt-3 grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
          <div><dt>L5 vs season average</dt><dd className="mt-1 font-semibold">{signed(workload.l5_vs_season)}</dd></div>
          <div><dt>Minutes trend</dt><dd className="mt-1 font-semibold">{signed(workload.minutes_trend)}</dd></div>
          <div><dt>Recent variability</dt><dd className="mt-1 font-semibold">{workload.variability == null ? "Unavailable" : `${number(workload.variability)} min`}</dd></div>
        </dl>
        <p className="mt-2 text-xs text-gray-500">{workload.explanation}</p>
        <p className="mt-1 text-xs text-gray-500">{workload.missing_minutes} eligible games without valid minutes. Missing minutes are excluded from minute averages, never filled with zero.</p>
      </div>
      {data.rest_splits.length > 0 && <div>
        <h3 className="text-sm font-medium text-gray-700">Historical comparisons by rest</h3>
        <p className="mt-1 text-xs text-gray-500">Descriptive samples from recorded appearances; points averages are not hit rates or predictions.</p>
        <div className="mt-2 space-y-3">{data.rest_splits.map(split => <div key={split.category} className="rounded border border-gray-100 p-3 text-xs text-gray-600">
          <p className="font-medium text-gray-800">{CATEGORY[split.category] ?? "Unknown rest"} · {split.games} games{split.games < 5 ? " · Limited sample" : ""}</p>
          <p className="mt-1">Minutes: {number(split.average_minutes)} ({split.minutes_games} games) · Points: {number(split.average_points)} ({split.points_games} games)</p>
          <p className="mt-1">{range(split.date_start, split.date_end)}</p>
        </div>)}</div>
      </div>}
      <div className="border-t border-gray-100 pt-3 text-xs text-gray-600">
        <p className="font-medium">Heuristic interpretation: {data.interpretation.label}</p>
        <p className="mt-1">{data.interpretation.explanation}</p>
        <p className="mt-1">These indicators do not measure injury risk, guarantee performance changes, or establish a betting edge.</p>
      </div>
      <details className="text-xs text-gray-500">
        <summary className="cursor-pointer rounded py-1 font-medium text-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">Data coverage &amp; calculation details</summary>
        <div className="mt-2 space-y-2">
          <p>{coverage.eligible_games} eligible of {coverage.stored_games} stored games · {range(coverage.date_start, coverage.date_end)}</p>
          <p>Sources: {coverage.sources.length ? coverage.sources.join(", ") : "No eligible provider history"}</p>
          {excluded.length > 0 && <p>Excluded: {[...known.map(([reason, count]) => `${EXCLUSIONS[reason]}: ${count}`), ...(other ? [`Other eligibility exclusions: ${other}`] : [])].join(" · ")}</p>}
          {coverage.notes.map(note => <p key={note}>{note}</p>)}
          <p>Possession-based usage is unavailable; minutes and points do not establish a usage rate.</p>
        </div>
      </details>
    </>}
  </section>;
}
