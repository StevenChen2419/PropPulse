"use client";
import { useState } from 'react';
import type { ExactLineResearch, ExactResearchWindow, PropSide } from '@/lib/types';
import { PlayerResearchChart } from '@/components/PlayerResearchChart';
import { SportsbookComparison } from '@/components/SportsbookComparison';
import { SaveExactSelection } from '@/components/SaveExactSelection';
import { OddsStatus, StatisticsStatus, formatObservation } from '@/components/DataStatus';

function Window({ label, sample, side }: { label: string; sample: ExactResearchWindow; side: PropSide }) {
  return <div className="rounded-lg bg-gray-50 p-3 text-xs leading-relaxed text-gray-500">
    <h3 className="font-semibold text-gray-800">{label} · {sample.appearances} appearances</h3>
    <p className="mt-1 capitalize">{side} hits: {sample.hits}/{sample.valid_samples} valid outcomes{sample.raw_hit_rate == null ? ' · unavailable' : ` · ${(sample.raw_hit_rate * 100).toFixed(1)}%`}</p>
    <p>{sample.losses} losses · {sample.pushes} pushes · {sample.missing_samples} missing</p>
    <p>Over {sample.over_hits} · Under {sample.under_hits}</p>
    <p>Settled rate (pushes excluded): {sample.hits}/{sample.settled_decisions}{sample.settled_hit_rate == null ? ' · unavailable' : ` · ${(sample.settled_hit_rate * 100).toFixed(1)}%`}</p>
  </div>;
}
const messages = { unsupported_market: 'No trustworthy statistic mapping for this market.',
  unsupported_role: 'No verified appearances in the role required by this market.',
  missing_metric: 'Recorded appearances have no complete values for this market.',
  no_recorded_games: 'No eligible completed games recorded in this season and competition.', available: '' };

export function ExactLinePanel({ data, gameTime, onSelection }: { data: ExactLineResearch; gameTime?: string;
  onSelection: (sportsbook: string, line: number, side: PropSide) => void }) {
  const [opponentId, setOpponentId] = useState(data.current_opponent_id ?? '');
  const [window, setWindow] = useState<'l5' | 'l10'>('l10');
  const opponent = data.opponents.find(row => row.opponent_id === opponentId);
  // The API returns at most ten games; season denominators above are independent.
  const games = data.games.slice(0, window === 'l5' ? 5 : 10);
  const options = [...new Map([data.selection, ...data.offer_options].map(o => [JSON.stringify([o.sportsbook, o.line]), o])).values()];
  return <section aria-label="Verified exact-line research" className="mb-4 rounded-lg border border-gray-100 bg-white p-5">
    <h2 className="font-semibold text-gray-800">Exact-line research · {data.market.replace(/_/g, ' ')}</h2>
    <p className="mt-1 text-sm capitalize text-gray-600">{data.selection.sportsbook} · {data.side} {data.line} · {data.season} · {data.competition}</p>
    <div className="my-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
      <label className="min-w-0 text-xs text-muted">Sportsbook / line<select aria-label="Exact research sportsbook line" className="mt-1 w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm"
        value={JSON.stringify([data.selection.sportsbook, data.line])} onChange={e => { const [book, line] = JSON.parse(e.target.value); onSelection(book, line, data.side); }}>
        {options.map(o => <option key={JSON.stringify([o.sportsbook,o.line])} value={JSON.stringify([o.sportsbook,o.line])}>{o.sportsbook} · {o.line}</option>)}
      </select></label>
      <label className="text-xs text-muted">Direction<select aria-label="Exact research direction" className="mt-1 w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm" value={data.side}
        onChange={e => onSelection(data.selection.sportsbook, data.line, e.target.value as PropSide)}><option value="over">Over</option><option value="under">Under</option></select></label>
    </div>
    <OddsStatus offer={data.selection} gameTime={gameTime} />
    {data.comparison?.prop_id && <SaveExactSelection propId={data.comparison.prop_id} side={data.side} selection={data.selection} />}
    <p className="text-xs text-muted">Price availability is separate from historical line analysis. Changing research does not change saved or slip picks.</p>
    <SportsbookComparison comparison={data.comparison} side={data.side} line={data.line}
      sportsbook={data.selection.sportsbook} gameTime={gameTime}
      onSelect={(offer, side) => onSelection(offer.sportsbook, offer.line, side)} />
    {data.movement && <p className="my-2 text-xs text-muted">{data.movement.reason}</p>}
    <StatisticsStatus coverage={data.coverage} />
    {data.status !== 'available' && <p role="status" className="my-3 text-sm text-gray-500">{messages[data.status]}</p>}
    <p className="mt-3 text-xs text-muted">L5 / L10 use the last 5 / 10 recorded appearances in this season. Missing values are excluded from valid outcomes; pushes are excluded only from settled rates.</p>
    <div className="my-4 grid gap-2 sm:grid-cols-3">{([['L5',data.l5],['L10',data.l10],['Season',data.season_window]] as const).map(([label,sample]) => <Window key={label} label={label} sample={sample} side={data.side} />)}</div>
    {!!data.games.length && <>
      <div role="group" aria-label="Recorded game sample" className="mb-3 flex flex-wrap gap-2">
        {(['l5', 'l10'] as const).map(value => <button key={value} type="button" aria-pressed={window === value} className={`button ${window === value ? 'border-blue-400 text-blue-500' : ''}`} onClick={() => setWindow(value)}>{value.toUpperCase()}</button>)}
      </div>
      <p role="status" className="mb-3 text-xs text-muted">Showing {games.length} recorded appearances · {games.filter(g => g.value != null).length} valid values. Chart and table show recent games only; the season summary can include more appearances.</p>
      <PlayerResearchChart games={[]} line={data.line} propType={data.market} exact={{...data, games}} />
      <div className="mt-4 max-h-80 overflow-auto rounded-lg border border-gray-100" tabIndex={0} role="region" aria-label="Scrollable recorded games">
        <table aria-label="Exact-line recorded games" className="w-full table-fixed text-left text-xs">
          <caption className="sr-only">Recorded game values and exact-line outcomes. Missing values are unavailable, not zero.</caption>
          <thead><tr className="border-b border-gray-100"><th scope="col" className="w-[29%] p-2">Date</th><th scope="col" className="w-[35%] p-2">Verified opponent</th><th scope="col" className="p-2 text-right">Value · Result</th></tr></thead>
          <tbody>{games.map(g => <tr key={g.game_id} className="border-b border-gray-100 align-top">
            <td className="break-words p-2">{g.game_date}</td><td className="break-words p-2 text-gray-500">{g.opponent_id ? `Opponent ID ${g.opponent_id}` : 'Opponent linkage unavailable'}</td>
            <td className="break-words p-2 text-right capitalize">{g.value ?? 'Unavailable'} · {g.outcome}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
    <div className="mt-4 border-t border-gray-100 pt-3">
      <h3 className="text-sm font-semibold text-gray-800">Verified opponent history</h3>
      {!data.current_opponent_id && <p className="my-1 text-xs text-muted">Current opponent linkage unavailable. Recorded source opponent IDs can be explored separately.</p>}
      <label className="text-xs text-muted">Recorded opponent<select aria-label="Verified opponent" value={opponentId} onChange={e => setOpponentId(e.target.value)} className="my-2 block w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm">
        <option value="">Choose a verified source ID</option>{data.current_opponent_id && !data.opponents.some(o => o.opponent_id === data.current_opponent_id) && <option value={data.current_opponent_id}>{data.current_opponent_id} · No recorded games</option>}
        {data.opponents.map(o => <option key={o.opponent_id} value={o.opponent_id}>{o.source} · {o.opponent_id} · {o.season_window.appearances} appearances</option>)}
      </select></label>
      {opponent ? <><Window label="Opponent season" sample={opponent.season_window} side={data.side} /><p className="mt-2 text-xs text-muted">Recorded values: {opponent.games.map(g => `${g.game_date}: ${g.value ?? 'unavailable'} (${g.outcome})`).join(' · ')}</p></>
        : <p className="text-xs text-muted">No selected verified opponent sample. Names alone do not establish opponent identity.</p>}
    </div>
    <p className="mt-4 text-xs text-muted">Source: {data.source ?? 'Unknown'} · Stats through {data.last_game_date ?? 'unknown'} · Source observed {formatObservation(data.source_observed_at)}</p>
    {data.limitations.map(note => <p key={note} className="mt-1 text-xs text-muted">{note}</p>)}
  </section>;
}
