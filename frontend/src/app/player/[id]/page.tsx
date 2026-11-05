"use client";
import { useLiveRefresh } from "@/lib/useLiveRefresh";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowRight, Minus, RefreshCw, Star, TrendingDown, TrendingUp } from "lucide-react";

import { RestWorkloadSection } from "@/components/RestWorkloadSection";
import { MatchupContextSection } from "@/components/MatchupContextSection";
import { PlayerSeasonSummary } from "@/components/PlayerSeasonSummary";
import { ExactLinePanel } from '@/components/ExactLinePanel';
import { OddsStatus } from '@/components/DataStatus';
import { PlayerResearchChart } from "@/components/PlayerResearchChart";
import { HistoricalTrendSummary, ResearchHistorySummary } from "@/components/ResearchHistorySummary";
import { PlayerStatsChart } from "@/components/PlayerStatsChart";
import { useOfferClock } from "@/lib/useOfferClock";
import { availabilityLabel, isActionable } from "@/lib/propSides";
import { api } from "@/lib/api";
import { errorMessage, formatGameContext, gameIdentityValue, propResearchHref } from "@/lib/gameNavigation";
import { createRequestGate } from "@/lib/requestGate";
import type {
  PlayerDetail,
  PlayerGameLog,
  PlayerResearch,
  PlayerResearchProp,
  ResearchSplit,
  TrendWindow,
  User,
} from "@/lib/types";

function formatOdds(odds: number | null): string {
  if (odds == null) return "—";
  return odds > 0 ? `+${odds}` : `${odds}`;
}

function formatPropType(value: string): string {
  const labels: Record<string, string> = {
    rbis: "RBIs",
    pra: "PRA",
    total_bases: "Total bases",
    home_runs: "Home runs",
    strikeouts: "Strikeouts",
    three_pointers_made: "Threes",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function formatSnapshotTime(value: string): string {
  const utcValue = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(new Date(utcValue));
}

function gameLabel(prop: PlayerResearchProp): string {
  const provenance = prop.identity_source === "authoritative" ? "Verified Event" : "Legacy / unverified";
  return `${formatGameContext(prop)} · ${provenance}`;
}

function hitRate(window: TrendWindow): string {
  return window.hit_rate == null ? "-" : `${Math.round(window.hit_rate * 100)}%`;
}

function SplitRow({ label, split }: { label: string; split: ResearchSplit }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 text-sm">
      <span className="text-gray-600">{label}</span>
      <span className="font-semibold text-gray-900">
        {hitRate(split)}
        <span className="ml-2 font-normal text-gray-400">
          {split.hits}/{split.decisions}
        </span>
      </span>
    </div>
  );
}

function PlayerPageContent() {
  useOfferClock();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropId = searchParams.get("prop_id");
  const requestedSeason = searchParams.get("season") || undefined;
  const requestedCompetition = searchParams.get("competition") || undefined;
  const requestedBook = searchParams.get('sportsbook') ?? undefined;
  const requestedOfferLine = searchParams.get('offer_line');
  const requestedSide = searchParams.get('side') ?? 'over';
  const scopeQuery = new URLSearchParams();
  if (requestedSeason) scopeQuery.set("season", requestedSeason);
  if (requestedCompetition) scopeQuery.set("competition", requestedCompetition);
  const playersHref = `/players${scopeQuery.size ? `?${scopeQuery}` : ""}`;
  const researchScope = `${requestedSeason ?? ""}:${requestedCompetition ?? ""}${requestedBook !== undefined || requestedOfferLine !== null || searchParams.get('side') ? `:${requestedBook ?? ''}:${requestedOfferLine ?? ''}:${requestedSide}` : ''}`;
  const researchHref = (propId: string) => {
    const href = propResearchHref(id, propId);
    const query = new URLSearchParams();
    if (requestedSeason) query.set("season", requestedSeason);
    if (requestedCompetition) query.set("competition", requestedCompetition);
    return query.size ? `${href}&${query}` : href;
  };
  const requestGate = useRef(createRequestGate());
  const selectedId = useRef<string | null>(requestedPropId);
  const routeIdentity = useRef(`${id}:${requestedPropId ?? ""}:${researchScope}`);
  const identity = `${id}:${requestedPropId ?? ""}:${researchScope}`;
  if (routeIdentity.current !== identity) {
    requestGate.current.cancel();
    routeIdentity.current = identity;
    selectedId.current = requestedPropId;
  }
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [gameLog, setGameLog] = useState<PlayerGameLog | null>(null);
  const [researchResponse, setResearchResponse] = useState<{ scope: string; data: PlayerResearch } | null>(null);
  const research = researchResponse?.scope === researchScope ? researchResponse.data : null;
  const [viewer, setViewer] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [researchLoading, setResearchLoading] = useState(false);
  const [followLoading, setFollowLoading] = useState(false);
  const [followError, setFollowError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const request = requestGate.current.start();
    const propId = selectedId.current;
    const route = routeIdentity.current;
    const current = () => request.isCurrent() && routeIdentity.current === route && selectedId.current === propId;
    setResearchLoading(true);
    setError(null);
    try {
      const [detail, currentViewer] = await Promise.all([
        api.getPlayer(id, request.signal),
        api.getMe(request.signal).catch(() => null),
      ]);
      if (!current()) return;
      if (["NBA", "WNBA", "MLB", "NFL", "NHL"].includes(detail.sport)) {
        const params = {
          ...(propId ? { prop_id: propId } : {}),
          ...(requestedSeason ? { season: requestedSeason } : {}),
          ...(requestedCompetition ? { competition: requestedCompetition } : {}),
          ...(requestedBook !== undefined ? { sportsbook: requestedBook } : {}),
          ...(requestedOfferLine !== null ? { offer_line: Number(requestedOfferLine) } : {}),
          ...(searchParams.get('side') ? { side: requestedSide } : {}),
        };
        const result = await api.getPlayerResearch(id, Object.keys(params).length ? params : undefined, request.signal);
        if (!current()) return;
        setResearchResponse({ scope: researchScope, data: result });
        setGameLog(null);
        if (!propId && result.selected_prop) {
          // Pin the backend's deterministic default before any subsequent refresh.
          selectedId.current = result.selected_prop.id;
          router.replace(researchHref(result.selected_prop.id), { scroll: false });
        }
      } else {
        const logs = await api.getPlayerGameLog(id, request.signal).catch(() => null);
        if (!current()) return;
        setGameLog(logs);
        setResearchResponse(null);
      }
      setPlayer(detail);
      setViewer(currentViewer);
    } catch (err: unknown) {
      if (!current() || request.signal.aborted) return;
      setError(errorMessage(err, "player research"));
    } finally {
      if (request.isCurrent() && routeIdentity.current === route) {
        setLoading(false);
        setResearchLoading(false);
      }
    }
  }, [id, requestedPropId, requestedSeason, requestedCompetition, requestedBook, requestedOfferLine, requestedSide, router]);

  useEffect(() => {
    void load();
    return () => requestGate.current.cancel();
  }, [load]);

  useLiveRefresh(load, loading || researchLoading || followLoading);

  const propChoices = useMemo(() => {
    const props = [...(research?.available_props ?? [])];
    const retained = research?.selected_prop;
    if (retained && !props.some((prop) => prop.id === retained.id)) props.push(retained);
    return props;
  }, [research]);
  const gameChoices = useMemo(() => {
    const groups = new Map<string, PlayerResearchProp[]>();
    for (const prop of propChoices) {
      // Unresolved contexts stay separate instead of inventing a matchup.
      const key = gameIdentityValue(prop) || `unresolved:${prop.id}`;
      groups.set(key, [...(groups.get(key) ?? []), prop]);
    }
    return [...groups.entries()];
  }, [propChoices]);

  const selectProp = (prop: PlayerResearchProp) => {
    requestGate.current.cancel();
    selectedId.current = prop.id;
    setResearchLoading(true);
    setError(null);
    router.push(researchHref(prop.id), { scroll: false });
  };

  const toggleFollow = async () => {
    if (!viewer) {
      router.push("/login");
      return;
    }
    const followed = viewer.fav_players.includes(id);
    setFollowLoading(true);
    setFollowError(null);
    try {
      if (followed) await api.unfollowPlayer(id);
      else await api.followPlayer(id);
      setViewer({
        ...viewer,
        fav_players: followed
          ? viewer.fav_players.filter((playerId) => playerId !== id)
          : [...viewer.fav_players, id],
      });
    } catch (err: unknown) {
      setFollowError(err instanceof Error ? err.message : "Could not update My Players");
    } finally {
      setFollowLoading(false);
    }
  };

  if (loading || (player !== null && player.id !== id && !error)) {
    return (
      <main className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-2xl space-y-4 px-4 py-6">
          <p role="status" className="text-sm text-muted">Loading player research…</p>
          {[28, 44, 40, 48].map((height) => (
            <div
              key={height}
              className="animate-pulse rounded-lg border border-gray-100 bg-white"
              style={{ height: height * 4 }}
            />
          ))}
        </div>
      </main>
    );
  }

  if (!player || player.id !== id) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="text-center">
          <AlertCircle size={32} className="mx-auto mb-3 text-red-300" />
          <p className="font-medium text-gray-700">Player research unavailable</p>
          <p className="mb-4 mt-1 text-xs text-gray-400">{error}</p>
          <div className="flex justify-center gap-3">
            <button onClick={() => router.back()} className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-500 hover:text-gray-800">
              <ArrowLeft size={14} /> Back
            </button>
            <button onClick={load} className="flex items-center gap-1.5 rounded-lg border border-blue-200 px-3 py-1.5 text-sm text-blue-600 hover:text-blue-800">
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        </div>
      </main>
    );
  }

  const fatigue = player.fatigue;
  const isHistoricalResearchSport = ["NBA", "WNBA", "MLB", "NFL", "NHL"].includes(player.sport);
  const selected = research?.selected_prop && (!requestedPropId || research.selected_prop.id.toLowerCase() === requestedPropId.toLowerCase())
    ? research.selected_prop : null;
  const seasonSummary = !requestedPropId || selected ? research?.season_summary : null;
  const selectedGame = selected ? gameIdentityValue(selected) || `unresolved:${selected.id}` : null;
  const marketChoices = gameChoices.find(([key]) => key === selectedGame)?.[1] ?? [];
  const trends = research?.trends;
  const movement = research?.line_movement;
  const followed = viewer?.fav_players.includes(id) ?? false;

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace research-workspace">
        <button onClick={() => router.back()} className="mb-4 flex items-center gap-1.5 text-sm text-gray-400 transition-colors hover:text-gray-700">
          <ArrowLeft size={15} /> Back
        </button>

        <section className="player-identity mb-4 rounded-2xl border border-gray-100 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="eyebrow">{player.sport} / Player research</p>
              <h1 className="page-title">{player.name}</h1>
              <p className="mt-0.5 text-sm text-gray-400">
                {[player.team, player.position, player.age ? `Age ${player.age}` : null]
                  .filter(Boolean)
                  .join(" / ")}
              </p>
              <p className="mt-0.5 text-xs uppercase text-gray-300">{player.sport}</p>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={toggleFollow}
                disabled={followLoading}
                title={followed ? "Remove from My Players" : "Add to My Players"}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${followed ? "border-blue-200 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-blue-200 hover:text-blue-600"}`}
              >
                <Star size={13} fill={followed ? "currentColor" : "none"} />
                {followed ? "Following" : "Follow"}
              </button>
            </div>
          </div>
          {followError && <p role="alert" className="mt-3 text-xs text-red-500">{followError}</p>}
        </section>

        {error && <p role="alert" className="mb-4 rounded-lg border border-red-100 bg-white p-3 text-sm text-red-600">{error}</p>}

        {isHistoricalResearchSport ? (
          <>
            <section className="research-controls mb-4 rounded-2xl border border-gray-100 bg-white p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-gray-800">Player Research</h2>
                  <p className="mt-0.5 text-xs text-gray-400">Historical results against the displayed line</p>
                </div>
                {researchLoading && <span role="status" className="flex items-center gap-2 text-xs text-muted"><RefreshCw size={15} className="animate-spin text-blue-500" />Updating research…</span>}
              </div>
              {isHistoricalResearchSport && <div className="mb-4">
                <label className="block text-xs font-medium text-gray-500">{player.sport} statistics season
                  <select aria-label={`${player.sport} statistics season`} value={requestedSeason ?? ""}
                    className="mt-1 block w-full rounded-lg border border-gray-200 bg-white p-2 text-sm text-gray-700"
                    onChange={(event) => {
                      const query = new URLSearchParams(searchParams.toString());
                      if (event.target.value) query.set("season", event.target.value); else query.delete("season");
                      requestGate.current.cancel();
                      setResearchLoading(true);
                      router.push(`/player/${encodeURIComponent(id)}${query.size ? `?${query}` : ""}`, { scroll: false });
                    }}>
                    <option value="">Current season (automatic)</option>
                    {[...new Set([...(player.sport === "NBA" || player.sport === "NHL" ? ["2026-27", "2025-26"] : ["2026", "2025"]), ...(requestedSeason ? [requestedSeason] : [])])].map(season => <option key={season} value={season}>{season}</option>)}
                  </select>
                </label>
                <p className="mt-1 text-xs text-gray-500">{requestedCompetition ?? "Regular Season"} · Applies to verified exact-line statistics and opponent history; legacy history is independently scoped.</p>
                <Link href={playersHref} className="mt-2 inline-block text-xs text-blue-600">Research another player with this season scope</Link>
              </div>}
              {propChoices.length > 0 ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block text-xs font-medium text-gray-500">Game
                    <select aria-label="Research game" className="mt-1 block w-full rounded-lg border border-gray-200 bg-white p-2 text-sm text-gray-700"
                      value={selectedGame ?? ""} onChange={(event) => {
                        const first = gameChoices.find(([key]) => key === event.target.value)?.[1][0];
                        if (first) selectProp(first);
                      }}>
                      {!selectedGame && <option value="">Select a game</option>}
                      {gameChoices.map(([key, props]) => <option key={key} value={key}>{gameLabel(props[0])}</option>)}
                    </select>
                  </label>
                  <label className="block text-xs font-medium text-gray-500">Market
                    <select aria-label="Research market" className="mt-1 block w-full rounded-lg border border-gray-200 bg-white p-2 text-sm text-gray-700"
                      value={selected?.id ?? ""} onChange={(event) => {
                        const prop = propChoices.find((choice) => choice.id === event.target.value);
                        if (prop) selectProp(prop);
                      }}>
                      {!selected && <option value="">Select a market</option>}
                      {marketChoices.map((prop) => <option key={prop.id} value={prop.id}>{formatPropType(prop.prop_type)} · {prop.line} · {prop.sportsbook}{!isActionable(prop, prop.game_time ?? undefined) ? " · Unavailable" : ""}</option>)}
                    </select>
                  </label>
                </div>
              ) : (
                <div className="py-6 text-center"><p className="text-sm font-medium text-gray-600">No current sportsbook-backed props for this player</p><p className="mt-1 text-xs text-gray-400">Check back closer to game time.</p></div>
              )}
            </section>

            {!selected && <>
              <PlayerSeasonSummary data={seasonSummary} />
              <MatchupContextSection data={!requestedPropId ? research?.matchup_context : null} />
            </>}

            {selected && (
              <>
                {research?.exact_line && <ExactLinePanel key={`${selected.id}:${researchScope}`} data={research.exact_line}
                  gameTime={selected.game_time ?? undefined} onSelection={(sportsbook, line, side) => {
                    requestGate.current.cancel(); setResearchLoading(true);
                    const href = propResearchHref(id, selected.id, { sportsbook, line, side });
                    router.push(`${href}${scopeQuery.size ? `&${scopeQuery}` : ''}`, { scroll: false });
                  }} />}
                <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5">
                  <div className="mb-4 flex items-start justify-between gap-4">
                    <div><p className="mb-1 text-xs text-gray-500">Stored primary offer / legacy line context</p><p className="text-xs font-medium uppercase text-gray-400">{formatPropType(selected.prop_type)}</p><p className="mt-1 text-3xl font-bold text-gray-900">{selected.line}</p><p className="mt-1 text-xs text-gray-400">{gameLabel(selected)}</p></div>
                    <div className="text-right text-xs">
                      <p className="text-gray-400">{selected.sportsbook} · {availabilityLabel(selected, selected.game_time ?? undefined)}</p>
                      <OddsStatus offer={selected} gameTime={selected.game_time ?? undefined} />
                      <p className="mt-1 text-emerald-600">Over {formatOdds(isActionable(selected, selected.game_time ?? undefined) ? selected.over_odds : null)}</p>
                      <p className="mt-1 text-blue-600">Under {formatOdds(isActionable(selected, selected.game_time ?? undefined) ? selected.under_odds : null)}</p>
                      <p className="mt-2 text-gray-400">Best exact-line odds</p>
                      {(["over", "under"] as const).map((side) => {
                        const best = selected[`best_${side}`];
                        const offer = selected.sportsbook_offers?.find((item) => item.sportsbook === best?.sportsbook && item.line === selected.line);
                        const available = offer && isActionable(offer, selected.game_time ?? undefined);
                        return <p key={side} className="mt-1 capitalize text-gray-600">{side} {best && available ? `${best.sportsbook} ${formatOdds(best.odds)}` : "--"}</p>;
                      })}
                      <p className="mt-1 text-gray-400">{selected.sportsbook_count} books</p>
                    </div>
                  </div>
                  {(selected.sportsbook_offers?.length ?? 0) > 0 && (
                    <div className="mb-4 border-t border-gray-100 pt-3">
                      <p className="mb-2 text-xs font-medium text-gray-500">Sportsbook offers / explicit lines</p>
                      <div className="space-y-1 text-xs text-gray-600">
                        {selected.sportsbook_offers?.map((offer) => {
                          const available = isActionable(offer, selected.game_time ?? undefined);
                          return <p key={`${offer.sportsbook}:${offer.line}`}>{offer.sportsbook} / {offer.line} / Over {formatOdds(available ? offer.over_odds : null)} / Under {formatOdds(available ? offer.under_odds : null)} / {availabilityLabel(offer, selected.game_time ?? undefined)}</p>;
                        })}
                      </div>
                    </div>
                  )}
                </section>
                <PlayerSeasonSummary data={seasonSummary} />
                <MatchupContextSection data={!requestedPropId || selected ? research?.matchup_context : null} />



                <details open={!research?.exact_line} className="mb-4">
                  <summary className="cursor-pointer p-2 text-xs font-medium text-gray-500">Legacy exact-line history · independent season/competition scope · primary line {selected.line}</summary>

                <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5">
                  {player.sport === "NBA" && seasonSummary && (
                    <p className="mb-3 text-xs text-gray-600">Season summary above: {seasonSummary.season} · {seasonSummary.competition}. Line-based charts and splits below use separate ESPN history with their own displayed season and competition scope; the summary filters do not apply.</p>
                  )}
                  {trends && <>
                    <div className="grid grid-cols-3 gap-px overflow-hidden rounded-lg bg-gray-200"><HistoricalTrendSummary label="Last 5" window={trends.l5} /><HistoricalTrendSummary label="Last 10" window={trends.l10} /><HistoricalTrendSummary label={research?.history ? `${research.history.selected_season} season` : "Season"} window={trends.season_window} /></div>
                    <div className="mt-3 flex flex-wrap justify-center gap-x-6 gap-y-1 text-xs text-gray-500"><span>Eligible history average <strong className="text-gray-800">{trends.average}</strong></span><span>Eligible history median <strong className="text-gray-800">{trends.median}</strong></span></div>
                  </>}
                  <ResearchHistorySummary history={research?.history} />
                </section>

                {movement && (
                  <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div>
                        <h2 className="font-semibold text-gray-800">Line Movement</h2>
                        <p className="mt-0.5 text-xs text-gray-400">{movement.sportsbook} / {movement.snapshot_count} snapshots</p>
                      </div>
                      <span className={`flex items-center gap-1 text-sm font-semibold ${movement.line_change > 0 ? "text-red-500" : movement.line_change < 0 ? "text-emerald-600" : "text-gray-500"}`}>
                        {movement.line_change > 0 ? <TrendingUp size={16} /> : movement.line_change < 0 ? <TrendingDown size={16} /> : <Minus size={16} />}
                        {movement.line_change > 0 ? "+" : ""}{movement.line_change}
                      </span>
                    </div>
                    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                      <div className="bg-gray-50 p-3">
                        <p className="text-xs font-medium text-gray-400">Opening</p>
                        <p className="mt-1 text-2xl font-bold text-gray-900">{movement.opening_line}</p>
                        <p className="mt-1 text-xs text-gray-400">{formatSnapshotTime(movement.opened_at)}</p>
                        <p className="mt-1 text-xs text-gray-500">O {movement.opening_over_odds == null ? "-" : formatOdds(movement.opening_over_odds)} / U {movement.opening_under_odds == null ? "-" : formatOdds(movement.opening_under_odds)}</p>
                      </div>
                      <ArrowRight size={18} className="text-gray-300" />
                      <div className="bg-blue-50 p-3 text-right">
                        <p className="text-xs font-medium text-blue-500">Current</p>
                        <p className="mt-1 text-2xl font-bold text-gray-900">{movement.current_line}</p>
                        <p className="mt-1 text-xs text-gray-400">{formatSnapshotTime(movement.updated_at)}</p>
                        <p className="mt-1 text-xs text-gray-500">O {movement.current_over_odds == null ? "-" : formatOdds(selected && isActionable(selected, selected.game_time ?? undefined) ? movement.current_over_odds : null)} / U {movement.current_under_odds == null ? "-" : formatOdds(selected && isActionable(selected, selected.game_time ?? undefined) ? movement.current_under_odds : null)}</p>
                      </div>
                    </div>
                  </section>
                )}

                <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5"><PlayerResearchChart games={research?.games ?? []} line={selected.line} propType={selected.prop_type} history={research?.history} /></section>

                {research?.splits && (
                  <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5"><h2 className="mb-2 font-semibold text-gray-800">Splits</h2><div className="divide-y divide-gray-100"><SplitRow label="Home" split={research.splits.home} /><SplitRow label="Away" split={research.splits.away} /><SplitRow label={`vs ${research.splits.opponent.name || "opponent unavailable"}`} split={research.splits.opponent} /></div></section>
                )}

                {(research?.games.length ?? 0) > 0 && <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5"><h2 className="mb-3 font-semibold text-gray-800">Game Log</h2><div className="divide-y divide-gray-100">{research!.games.map((game) => <div key={`${game.game_date}-${game.opponent}`} className="grid grid-cols-[5rem_1fr_auto] items-center gap-3 py-2.5 text-sm"><span className="text-gray-400">{formatDate(game.game_date)}</span><span className="truncate text-gray-600">{game.is_home ? "vs" : "@"} {game.opponent || "Opponent"}</span><span className={`font-semibold ${game.result === "hit" ? "text-emerald-600" : game.result === "miss" ? "text-red-500" : "text-amber-600"}`}>{game.value} <span className="ml-1 text-xs font-normal capitalize">{game.result}</span></span></div>)}</div></section>}
                </details>
              </>
            )}
          </>
        ) : (
          <section className="mb-4 rounded-lg border border-gray-100 bg-white p-5"><PlayerStatsChart games={gameLog?.games ?? []} note={gameLog?.note ?? undefined} /></section>
        )}

        {seasonSummary ? (
          <details className="mb-4 rounded-lg border border-gray-100 bg-white p-4">
            <summary className="cursor-pointer text-xs font-medium text-gray-600">Advanced participation &amp; workload research</summary>
            <div className="mt-3"><RestWorkloadSection data={research?.rest_workload && (!requestedPropId || research.rest_workload.reference.prop_id?.toLowerCase() === requestedPropId.toLowerCase()) ? research.rest_workload : null} /></div>
          </details>
        ) : <RestWorkloadSection data={research?.rest_workload && (!requestedPropId || research.rest_workload.reference.prop_id?.toLowerCase() === requestedPropId.toLowerCase()) ? research.rest_workload : null} />}

        {fatigue && (
          <details className="mb-4 rounded-lg border border-gray-100 bg-white p-5 text-xs text-gray-500">
            <summary className="cursor-pointer font-medium text-gray-700">Experimental fatigue estimate</summary>
            <p className="mt-3">Legacy score: {fatigue.fatigue_score.toFixed(3)} on a 0–1 scale. This experimental estimate has not been independently validated on observed outcomes. Its method and training provenance are not available in this response.</p>
            <p className="mt-2">This estimate is separate from the recorded rest and workload research above. It is not an injury-risk assessment, a calibrated probability, or evidence of a betting edge.</p>
          </details>
        )}


        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-3 font-semibold text-gray-800">Active Props <span className="ml-2 text-xs font-normal text-gray-400">({player.props.length})</span></h2>
          {player.props.length === 0 ? <p className="py-4 text-center text-sm text-gray-400">No active props for this player</p> : (
            <div className="divide-y divide-gray-50">{player.props.map((prop) => (
              <Link key={prop.id} href={researchHref(prop.id)} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div><span className="text-sm font-medium capitalize text-gray-800">{formatPropType(prop.prop_type)}</span>
                  <p className="mt-1 text-xs text-gray-400">{prop.event_id ? formatGameContext(prop) : `${prop.opponent ? `vs ${prop.opponent} / ` : ""}Legacy / unverified`}</p>
                </div>
                <div className="text-right"><p className="text-sm font-bold text-gray-900">{prop.line}</p>
                  <p className="text-xs text-gray-400">{formatOdds(isActionable(prop, prop.game_time) ? prop.over_odds : null)} / {formatOdds(isActionable(prop, prop.game_time) ? prop.under_odds : null)}</p>
                </div>
              </Link>
            ))}</div>
          )}
        </section>
      </div>
    </main>
  );
}

export default function PlayerPage() {
  return <Suspense fallback={<main className="min-h-screen bg-gray-50 p-6 text-gray-500"><p role="status">Loading player research...</p></main>}><PlayerPageContent /></Suspense>;
}
