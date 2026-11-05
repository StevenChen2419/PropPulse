import type { OfferAvailability, StatisticsCoverage } from '@/lib/types';
import { availabilityLabel, offerObservation } from '@/lib/propSides';

const sources: Record<string, string> = { nba_com_stats: 'NBA.com · NBA Stats', espn_nba: 'ESPN',
  wehoop_wnba_stats: 'wehoop · WNBA Stats', nhl_web: 'NHL Web API', nflverse: 'nflverse', mlb_stats_api: 'MLB StatsAPI' };

function instant(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatObservation(value?: string | null): string {
  const date = instant(value);
  return date ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short' }).format(date) : 'Unknown';
}

export function OddsStatus({ offer, gameTime, now = Date.now() }: { offer: OfferAvailability; gameTime?: string; now?: number }) {
  const observed = offerObservation(offer);
  const date = instant(observed);
  const age = date ? now - date.getTime() : NaN;
  const elapsed = !Number.isFinite(age) || age < 0 ? 'observation time unknown'
    : age < 60000 ? 'observed just now' : age < 3600000 ? `observed ${Math.floor(age / 60000)}m ago`
    : age < 86400000 ? `observed ${Math.floor(age / 3600000)}h ago` : `observed ${Math.floor(age / 86400000)}d ago`;
  return <p className="my-1 text-xs leading-relaxed text-gray-500" title={`Sportsbook price observed ${formatObservation(observed)}. Ingestion and page reload do not renew this observation.`}>
    {availabilityLabel(offer, gameTime)} · {elapsed}
    {date && <span className="block">Sportsbook observation: {formatObservation(observed)}</span>}
  </p>;
}

export function StatisticsStatus({ coverage }: { coverage?: StatisticsCoverage | null }) {
  if (!coverage) return <p className="my-1 text-xs text-gray-500">Statistics coverage unavailable</p>;
  const day = coverage.last_game_date;
  const parsed = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? new Date(`${day}T12:00:00Z`) : null;
  const through = parsed && !Number.isNaN(parsed.getTime()) ? new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(parsed) : null;
  const historical = coverage.season_scope === 'historical';
  const label = coverage.state === 'source_unavailable' ? `${coverage.season} · Statistics source unavailable`
    : coverage.state === 'no_recorded_games' ? `${historical ? 'Historical · ' : ''}${coverage.season} · No completed games recorded`
    : `${historical ? 'Historical stats' : 'Stats'}${through ? ` through ${through}` : ' · game date unknown'} · ${coverage.recorded_appearances} games`;
  return <details className="my-2 min-w-0 text-xs leading-relaxed text-gray-500">
    <summary className="cursor-pointer break-words focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">{label}{coverage.state === 'partial_current_season' ? ' · Partial sample' : ''}</summary>
    <div className="mt-1 space-y-1 border-l border-gray-200 pl-2">
      <p>{historical ? 'Historical season' : 'Selected season'} · {coverage.season} · {coverage.competition}</p>
      <p>{sources[coverage.source ?? ''] ?? coverage.source ?? 'Source unavailable'} · Source coverage uncertain</p>
      <p>L5: {coverage.l5_samples} appearances · L10: {coverage.l10_samples} appearances{coverage.state === 'partial_current_season' ? ' · Partial sample' : ''}. Metric samples may differ.</p>
      <p>Source observed: {formatObservation(coverage.source_observed_at)}. Observation time is separate from the last game represented.</p>
      {!!coverage.recorded_weeks?.length && <p>Recorded weeks: {coverage.recorded_weeks.join(', ')}; missing weeks are not inferred.</p>}
      {coverage.limitations.map(note => <p key={note}>{note}</p>)}
      <p>Statistics coverage does not determine sportsbook price availability.</p>
    </div>
  </details>;
}
