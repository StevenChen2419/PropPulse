import type { PlayerSeasonSummary as SeasonSummary, SeasonStatistic } from "@/lib/types";
import { StatisticsStatus } from '@/components/DataStatus';

function calendarDate(value: string | null): string {
  if (!value) return "Unavailable";
  // The API supplies an Eastern calendar date, not a game-start instant.
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  }).format(parsed);
}

function observation(value: string | null): string {
  if (!value) return "Unavailable";
  const utcValue = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const parsed = new Date(utcValue);
  if (Number.isNaN(parsed.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "America/New_York", timeZoneName: "short",
  }).format(parsed);
}

function Statistic({ metric, appearances }: { metric: SeasonStatistic; appearances: number }) {
  return <>
    <span className="font-semibold text-gray-900 break-normal">{metric.average == null ? "Unavailable" : metric.average.toFixed(1)}</span>
    <span className="mt-0.5 block text-[11px] leading-relaxed font-normal text-gray-500">{metric.valid_samples}/{appearances} valid</span>
  </>;
}

function metricValue(window: SeasonSummary["l5"], key: string): SeasonStatistic {
  const value = (window as unknown as Record<string, SeasonStatistic | number>)[key];
  return typeof value === "object" && value !== null ? value : { average: null, valid_samples: 0 };
}

export function PlayerSeasonSummary({ data, now = new Date() }: { data?: SeasonSummary | null; now?: Date }) {
  if (!data) return null;
  // An old selected Event must not make historical statistics appear current.
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  const reference = /^(\d{4})-(\d{2})-\d{2}$/.exec(today);
  const selectedSeason = /^(\d{4})-\d{2}$/.exec(data.season);
  const referenceSeasonYear = reference ? Number(reference[1]) - (Number(reference[2]) < 10 ? 1 : 0) : null;
  const historical = data.sport && !["NBA", "NHL"].includes(data.sport)
    ? Number(data.season) < Number(reference?.[1])
    : selectedSeason !== null && referenceSeasonYear !== null && Number(selectedSeason[1]) < referenceSeasonYear;
  const title = historical ? "Historical Performance" : "Recent Performance";
  const historicalLabel = historical ? <p className="mt-1 text-xs text-gray-600">Historical season statistics; not current live form.</p> : null;
  const source = ({ nba_com_stats: "NBA.com · NBA Stats", espn_nba: "ESPN", wehoop_wnba_stats: "wehoop · WNBA Stats", nhl_web: "NHL Web API", nflverse: "nflverse", mlb_stats_api: "MLB StatsAPI" } as Record<string,string>)[data.source ?? ""] ?? data.source ?? "Source unavailable";
  const metrics = data.metrics ?? [ { key: "points", label: "Points" }, { key: "rebounds", label: "Rebounds" }, { key: "assists", label: "Assists" }, { key: "minutes", label: "Minutes" } ];
  if (data.status === "unavailable") return <section aria-label="Season statistics" className="season-summary mb-4 rounded-lg border border-gray-100 bg-white p-5">
    <h2 className="font-semibold text-gray-800">{title}</h2>
    {historicalLabel}
    {data.coverage && <StatisticsStatus coverage={data.coverage} />}
    <p className="mt-2 text-sm text-gray-600">Season statistics unavailable · {data.season} · {data.competition}</p>
    <p className="mt-1 text-xs text-gray-600">{data.sport && data.sport !== "NBA" ? "No verified appearances recorded for this sport, season and competition." : data.source === "espn_nba" ? "No ESPN appearances recorded in this scope." : "No NBA.com appearances recorded for this season and competition."} Player statistics are separate from sportsbook odds and team context.</p>
    <p className="mt-1 text-xs text-gray-500">{source} · 0 recorded appearances. L5/L10 and player rest are unavailable.</p>
    <p className="mt-1 text-xs text-gray-500">{data.notes.join(" ") || "No eligible recorded appearances in this scope."}</p>
  </section>;

  return <section aria-label="Season statistics" className="season-summary mb-4 space-y-4 rounded-lg border border-gray-100 bg-white p-5">
    <div>
      <h2 className="font-semibold text-gray-800">{title}</h2>
      {historicalLabel}
      {data.coverage && <StatisticsStatus coverage={data.coverage} />}
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
        <span className="rounded-lg border border-gray-100 px-3 py-2">L5 · {data.l5.appearances} appearances</span>
        <span className="rounded-lg border border-gray-100 px-3 py-2">L10 · {data.l10.appearances} appearances</span>
      </div>
      <div className="my-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {metrics.map(({key, label}) => <div key={key} role="group" aria-label={label} className="metric-card">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{label}</h3>
          <dl className="grid grid-cols-2 gap-2">
            {(["l5", "l10"] as const).map(window => <div key={window}><dt className="mb-1 text-[11px] uppercase text-muted">{window.toUpperCase()}</dt><dd className="text-xl tabular-nums"><Statistic metric={metricValue(data[window], key)} appearances={data[window].appearances} /></dd></div>)}
          </dl>
        </div>)}
      </div>
      <p className="mt-1 text-xs text-gray-500">Newest recorded appearances first. Each average uses its own valid values; missing values do not add older games.</p>
    </div>
    <div className="border-t border-gray-100 pt-3">
      <h3 className="text-sm font-semibold text-gray-800">Rest</h3>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-xs text-gray-600 sm:grid-cols-3">
        <div className="col-span-2 sm:col-span-1"><dt>Last recorded appearance</dt><dd className="mt-1 font-medium text-gray-900">{calendarDate(data.latest_appearance)}</dd></div>
        <div><dt>Calendar days since</dt><dd className="mt-1 font-medium text-gray-900">{data.calendar_day_gap ?? "Unavailable"}</dd></div>
        <div><dt>Full intervening days</dt><dd className="mt-1 font-medium text-gray-900">{data.full_intervening_days ?? "Unavailable"}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-gray-500">Reference: {calendarDate(data.reference_date)} (Eastern). {data.date_precision === "eastern_date" ? "Appearance dates have Eastern calendar-day precision; game times are unavailable. " : ""}Recorded gaps do not establish missed games or inactive status.</p>
    </div>
    {!!data.opponent_history?.length && <div className="border-t border-gray-100 pt-3">
      <h3 className="text-sm font-semibold text-gray-800">Recorded opponent history</h3>
      <p className="mt-1 text-xs text-gray-500">Provider team identifiers; no inferred link to the selected sportsbook Event.</p>
      {data.opponent_history.map(opponent => <details key={opponent.opponent_id} className="mt-2 text-xs text-gray-600">
        <summary>Opponent {opponent.opponent_id} · {opponent.l10.appearances} recent recorded appearances</summary>
        <dl className="mt-2 grid grid-cols-2 gap-2">{metrics.map(({key,label}) => <div key={key}><dt>{label} · L5 / L10</dt><dd>
          <Statistic metric={metricValue(opponent.l5,key)} appearances={opponent.l5.appearances} /> / <Statistic metric={metricValue(opponent.l10,key)} appearances={opponent.l10.appearances} />
        </dd></div>)}</dl>
      </details>)}
    </div>}
    <div className="border-t border-gray-100 pt-3 text-xs text-gray-600">
      <h3 className="text-sm font-semibold text-gray-800">Coverage</h3>
      <p className="mt-2">{data.season} · {data.competition} · {source}</p>
      <p className="mt-1">{data.recorded_appearances} recorded appearances · {calendarDate(data.coverage_start)} – {calendarDate(data.coverage_end)}</p>
      <p className="mt-1">Last observation: {observation(data.last_observed_at)}</p>
      <p className="mt-2">Recorded coverage may be partial; this is not necessarily the player&apos;s complete season history.</p>
      {data.notes.map(note => <p key={note} className="mt-1">{note}</p>)}
    </div>
  </section>;
}
