import type { MatchupContext } from "@/lib/types";

function date(value: string | null) {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${value}T12:00:00Z`));
}

export function MatchupContextSection({ data }: { data?: MatchupContext | null }) {
  if (!data) return null;
  const team = data.team_context;
  const history = data.opponent_history;
  return <section aria-label="Matchup and team rest" className="mb-4 space-y-3 rounded-lg border border-gray-100 bg-white p-5">
    <h2 className="font-semibold text-gray-800">Matchup &amp; Team Rest</h2>
    {!team ? <p className="text-sm text-gray-600">{data.reason || "Select a supported game to view team and opponent context."}</p> : <>
      <p className="text-sm text-gray-700">{team.team_name} · vs {team.opponent_name}</p>
      <dl className="grid grid-cols-2 gap-3 text-xs text-gray-600 sm:grid-cols-3">
        <div className="col-span-2 sm:col-span-1"><dt>Last recorded completed team game</dt><dd className="mt-1 font-medium text-gray-900">{date(team.last_recorded_game?.date ?? null)}</dd></div>
        <div><dt>Calendar days since</dt><dd className="mt-1 font-medium text-gray-900">{team.calendar_day_gap ?? "Unavailable"}</dd></div>
        <div><dt>Full intervening team rest days</dt><dd className="mt-1 font-medium text-gray-900">{team.full_intervening_days ?? "Unavailable"}</dd></div>
      </dl>
      <p className="text-xs text-gray-600">Back-to-back: <strong>{team.conditional_back_to_back === "yes" ? "Yes, if the team plays the selected game" : "Unknown — incomplete schedule coverage"}</strong></p>
      <p className="text-xs text-gray-500">Selected Event: {date(team.reference_date)} (Eastern). Recorded gaps describe team results, not individual player rest or proof of no intervening games.</p>
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">Team source &amp; partial coverage</summary>
        {team.last_recorded_game && <p className="mt-1 break-words">NBA.com · {team.last_recorded_game.source} · Game {team.last_recorded_game.game_id} · Eastern date only · Observed {team.last_recorded_game.observed_at}</p>}
        {team.notes.map(note => <p key={note} className="mt-1">{note}</p>)}
      </details>
      <div className="border-t border-gray-100 pt-3">
        <h3 className="text-sm font-semibold text-gray-800">Against This Opponent</h3>
        {!history || history.status === "unavailable" ? <p className="mt-2 text-xs text-gray-600">No supported opponent appearances in this season and source scope.</p> : <>
          <p className="mt-2 text-xs text-gray-600">{history.recorded_appearances} recorded appearances vs {history.opponent_name} · {history.season} · {history.competition} · {history.source === "nba_com_stats" ? "NBA.com · NBA Stats" : history.source}</p>
          <p className="mt-1 text-xs text-gray-500">{date(history.coverage_start)} – {date(history.coverage_end)} · Partial recorded coverage</p>
          <table className="mt-3 w-full table-fixed text-left text-xs">
            <thead className="text-gray-500"><tr><th scope="col" className="pb-2 font-medium">Average</th>{(["overall", "l5", "l10"] as const).map((key, index) => <th scope="col" key={key} className="pb-2 font-medium">{["All", "L5", "L10"][index]}<span className="block text-[10px]">{history[key].appearances} games</span></th>)}</tr></thead>
            <tbody>{([ ["points", "PTS"], ["rebounds", "REB"], ["assists", "AST"], ["minutes", "MIN"] ] as const).map(([metric, label]) => <tr key={metric} className="border-t border-gray-100"><th scope="row" className="py-2 font-medium text-gray-600">{label}</th>{(["overall", "l5", "l10"] as const).map(key => <td key={key} className="py-2 text-gray-900">{history[key][metric].average?.toFixed(1) ?? "Unavailable"}<span className="block text-[10px] text-gray-500">{history[key][metric].valid_samples}/{history[key].appearances} valid</span></td>)}</tr>)}</tbody>
          </table>
          <details className="mt-2 text-xs text-gray-500"><summary className="cursor-pointer">Opponent appearance window dates</summary>{(["l5", "l10"] as const).map(key => <p key={key} className="mt-1">{key.toUpperCase()}: {history[key].appearances} appearances · {date(history[key].coverage_start)} – {date(history[key].coverage_end)}</p>)}</details>
          <p className="mt-2 text-xs text-gray-500">Newest opponent appearances define each window. Missing values do not add older games. Each metric uses its own valid sample count.</p>
        </>}
        <p className="mt-2 text-xs text-gray-500">Historical player performance is descriptive context, not a prediction or a measure of current opponent defensive strength.</p>
      </div>
    </>}
  </section>;
}
