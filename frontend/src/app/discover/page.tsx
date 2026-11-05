"use client";
import { Suspense, useCallback, useEffect, useState, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { useLiveRefresh } from '@/lib/useLiveRefresh';
import { gameIdentityValue, gameQuery, formatGameContext, errorMessage } from '@/lib/gameNavigation';
import { createRequestGate } from '@/lib/requestGate';
import { SearchField, EmptyState } from '@/components/Workspace';
import { FeedFilters } from '@/components/FeedFilters';
import { PropCard } from '@/components/PropCard';
import { api } from '@/lib/api';
import { DISCOVER_PAGE_SIZE, DISCOVER_SORTS, DISCOVER_SPORTS, discoverURL, readDiscoverFilters } from '@/lib/discoverFilters';
import type { DiscoverFilters } from '@/lib/discoverFilters';
import type { DiscoverResponse, TodayGame } from '@/lib/types';

function DiscoverContent() {
  const router = useRouter();
  const params = useSearchParams();
  const filters = readDiscoverFilters(params);
  const { sport, market, search, sportsbook, game_date, availability, sort, page, game } = filters;
  const [draft, setDraft] = useState(search);
  const [result, setResult] = useState<DiscoverResponse | null>(null);
  const [games, setGames] = useState<TodayGame[]>([]);
  const [gamesError, setGamesError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestGate = useRef(createRequestGate());
  const gamesGate = useRef(createRequestGate());
  const url = discoverURL(filters);

  const change = useCallback((updates: Partial<DiscoverFilters>) => {
    requestGate.current.cancel();
    // A filter change must carry pending text, even before the search debounce.
    router.push(discoverURL({ ...readDiscoverFilters(new URLSearchParams(url.split('?')[1])), page: 1,
      search: draft.replace(/\s+/g, ' ').trim().slice(0, 120), ...updates }), { scroll: false });
  }, [router, url, draft]);
  useEffect(() => setDraft(search), [search]);
  useEffect(() => {
    if (draft.replace(/\s+/g, ' ').trim().slice(0, 120) === search) return;
    const timer = setTimeout(() => change({ search: draft.replace(/\s+/g, ' ').trim().slice(0, 120) }), 350);
    return () => clearTimeout(timer);
  }, [draft, search, change]);

  const loadDiscover = useCallback(async () => {
    const request = requestGate.current.start();
    setLoading(true); setError(null);
    try {
      const response = await api.getDiscover({ browse: true, sport: sport || undefined,
        prop_type: market || undefined, search: search || undefined, sportsbook: sportsbook || undefined,
        game_date: game_date || undefined, availability: availability || undefined, sort,
        ...gameQuery(game), limit: DISCOVER_PAGE_SIZE, offset: (page - 1) * DISCOVER_PAGE_SIZE }, request.signal);
      if (request.isCurrent()) setResult(response);
    } catch (err: unknown) {
      if (request.isCurrent()) { setError(errorMessage(err, 'Discover filters')); setResult(null); }
    } finally { if (request.isCurrent()) setLoading(false); }
  }, [sport, market, search, sportsbook, game_date, availability, sort, page, game]);
  useEffect(() => { loadDiscover(); return () => requestGate.current.cancel(); }, [loadDiscover]);
  const loadGames = useCallback(async () => {
    const request = gamesGate.current.start();
    try {
      const rows = await api.getGames({ sport: sport || undefined, limit: 100 }, request.signal);
      if (request.isCurrent()) setGamesError(false);
      if (request.isCurrent()) setGames(previous => {
        const selected = previous.find(row => gameIdentityValue(row) === game);
        return selected && !rows.some(row => gameIdentityValue(row) === game)
          ? [...rows, { ...selected, has_eligible_props: false, prop_count: 0, source: 'unavailable' }]
          : rows;
      });
    } catch { if (request.isCurrent()) setGamesError(true); }
  }, [sport, game]);
  useEffect(() => { loadGames(); return () => gamesGate.current.cancel(); }, [loadGames]);
  useLiveRefresh(async () => { await Promise.all([loadDiscover(), loadGames()]); }, loading);
  const options = result?.filter_options;
  const markets = options?.markets ?? [];
  const books = options?.sportsbooks ?? [];
  const active = [sport && `Sport: ${sport}`, market && `Market: ${market.replace(/_/g, ' ')}`,
    search && `Search: ${search}`, sportsbook && `Book: ${sportsbook}`, game_date && `Date: ${game_date} ET`,
    availability && `Odds: ${availability.replace(/_/g, ' ')}`,
    game && `Game: ${games.find(row => gameIdentityValue(row) === game) ? formatGameContext(games.find(row => gameIdentityValue(row) === game)!) : 'Selected matchup'}`].filter(Boolean);
  const total = result?.total ?? 0;
  const props = result?.props ?? [];
  const hasMore = result?.has_more ?? (page * DISCOVER_PAGE_SIZE < total);
  const control = 'mt-1 block w-full min-w-0 rounded-xl border border-gray-200 bg-canvas px-3 py-2 text-sm';
  const reset = () => { setDraft(''); requestGate.current.cancel(); router.push('/discover', { scroll: false }); };
  return <main className="min-h-screen bg-gray-50"><div className="workspace">
    <header className="page-heading"><div>
      <p className="eyebrow">Find your next research angle</p><h1 className="page-title">Discover</h1>
      <p className="page-description">Search stored sportsbook props across all five sports. Statistics and price freshness are shown separately.</p>
    </div><button type="button" onClick={loadDiscover} disabled={loading} className="button flex items-center gap-2"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Refresh</button></header>
    <SearchField label="Search Discover props" value={draft} onChange={value => setDraft(value.slice(0, 120))} placeholder="Player, team, sport, market or matchup" />
    <div className="filter-panel mt-4">
      <FeedFilters sport={sport} propType={market} sports={options?.sports ?? DISCOVER_SPORTS}
        markets={[...new Set([...markets, ...(market ? [market] : [])])].map(value => ({ value, label: value.replace(/_/g, ' ') }))}
        onSport={value => change({ sport: value, market: '', game: '' })} onPropType={value => change({ market: value })} />
      <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="min-w-0 text-xs text-muted">Sportsbook<select aria-label="Sportsbook filter" value={sportsbook} onChange={e => change({ sportsbook: e.target.value })} className={control}>
          <option value="">All sportsbooks</option>{[...new Set([...books, ...(sportsbook ? [sportsbook] : [])])].map(book => <option key={book}>{book}</option>)}
        </select></label>
        <label className="min-w-0 text-xs text-muted">Game date (Eastern)<input aria-label="Game date (Eastern)" type="date" value={game_date} onChange={e => change({ game_date: e.target.value })} className={control} /></label>
        <label className="min-w-0 text-xs text-muted">Matching offer age<select aria-label="Odds availability filter" value={availability} onChange={e => change({ availability: e.target.value })} className={control}>
          <option value="">Available + Last known</option><option value="available">Available · within 30m</option><option value="last_known">Last known · 30m–6h</option>
        </select></label>
        <label className="min-w-0 text-xs text-muted">Sort<select aria-label="Sort Discover" value={sort} onChange={e => change({ sort: e.target.value })} className={control}>{DISCOVER_SORTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      </div>
      <label className="mt-3 block min-w-0 text-xs text-muted">Game<select aria-label="Discover game" value={game} onChange={e => change({ game: e.target.value })} className={control}>
        <option value="">All games</option>{game && !games.some(row => gameIdentityValue(row) === game) && <option value={game}>Selected game · outside current game list</option>}
        {games.map(row => <option key={gameIdentityValue(row)} value={gameIdentityValue(row)}>{formatGameContext(row)}{row.identity_source !== 'authoritative' ? ' · Legacy / unverified' : ''}{row.has_eligible_props === false ? ' · Odds unavailable' : ''}</option>)}
      </select></label>
      {gamesError && <p role="status" className="mt-2 text-xs text-amber-800">Game filters could not be updated. Your filters are kept. <button type="button" className="underline" onClick={loadGames}>Retry games</button></p>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted"><p>{active.length ? `Filters: ${active.join(' · ')}` : 'All eligible props'} · {sort.replace(/_/g, ' ')}</p><button type="button" className="button" onClick={reset}>Reset Filters</button></div>
      <p className="mt-2 text-xs text-muted">Filters match an eligible offer on the listed line. Cards retain their selected sportsbook; other books may differ. Expired and started-game prices are excluded.</p>
    </div>
    {error && <div role="alert" className="empty-state"><AlertCircle className="mx-auto mb-2" size={20} /><p>{error}</p><button type="button" className="button mt-3" onClick={loadDiscover}>Try again</button></div>}
    <p role="status" aria-live="polite" className="mb-4 text-xs text-muted">{loading ? 'Searching stored props…' : error ? 'Search unavailable. Retry to load matching props.' : `${total} matching props · Page ${page}${props.length ? ` · Showing ${(page - 1) * DISCOVER_PAGE_SIZE + 1}–${(page - 1) * DISCOVER_PAGE_SIZE + props.length}` : ''}`}</p>
    {loading && !error && <div className="h-64 animate-pulse rounded-2xl bg-white" aria-hidden="true" />}
    {!loading && !error && !props.length && <EmptyState title="No matching props" description={total ? 'This page is beyond the matching results. Return to the first page.' : 'Try fewer filters. Only stored props with eligible sportsbook offers are shown; missing statistics do not hide a valid offer.'} action={<button type="button" className="button" onClick={total ? () => change({ page: 1 }) : reset}>{total ? 'First page' : 'Reset Filters'}</button>} />}
    {!loading && !error && !!props.length && <div className="prop-grid">{props.map(prop => <PropCard key={prop.id} prop={prop} />)}</div>}
    {!loading && !error && (page > 1 || hasMore) && <nav aria-label="Discover pages" className="my-6 flex items-center justify-center gap-4">
      <button type="button" className="button" disabled={page === 1} onClick={() => change({ page: page - 1 })}>Previous</button><span className="text-sm text-muted">Page {page}</span><button type="button" className="button" disabled={!hasMore} onClick={() => change({ page: page + 1 })}>Next</button>
    </nav>}
  </div></main>;
}

export default function DiscoverPage() {
  return <Suspense fallback={<main className="workspace"><p role="status">Loading Discover…</p></main>}><DiscoverContent /></Suspense>;
}
