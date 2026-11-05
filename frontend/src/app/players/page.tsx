"use client";
import { useLiveRefresh } from "@/lib/useLiveRefresh";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Search, Star, TrendingDown, TrendingUp, Users } from "lucide-react";

import { SearchField } from "@/components/Workspace";
import { OddsStatus, StatisticsStatus } from '@/components/DataStatus';
import { useOfferClock } from "@/lib/useOfferClock";
import { isActionable, availabilityLabel } from "@/lib/propSides";
import { api } from "@/lib/api";
import type { PlayerSearchResult, User } from "@/lib/types";

const SPORTS = ["", "NBA", "WNBA", "MLB", "NFL", "NHL"];

function formatOdds(odds: number): string {
  return odds > 0 ? `+${odds}` : `${odds}`;
}

function formatPropType(value: string): string {
  const labels: Record<string, string> = {
    rbis: "RBIs",
    pra: "PRA",
    total_bases: "Total bases",
    home_runs: "Home runs",
    hits_allowed: "Hits allowed",
    earned_runs: "Earned runs",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}

function formatGameTime(value: string | null): string {
  if (!value) return "No current offers";
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  }).format(new Date(normalized));
}

function formatRate(value: number | null): string {
  return value == null ? "-" : `${Math.round(value * 100)}%`;
}

interface PlayerRowProps {
  scope: string;
  player: PlayerSearchResult;
  followed: boolean;
  busy: boolean;
  onFollow: (player: PlayerSearchResult) => void;
}

function PlayerRow({ player, followed, busy, onFollow, scope }: PlayerRowProps) {
  const movement = player.top_prop?.line_movement;
  const selectedScope = new URLSearchParams(scope);
  const selectedSeason = selectedScope.get("season");
  if (selectedSeason && !(["NBA", "NHL"].includes(player.sport) ? /^\d{4}-\d{2}$/ : /^\d{4}$/).test(selectedSeason)) selectedScope.delete("season");
  const href = `/player/${player.id}${selectedScope.size ? `?${selectedScope}` : ""}`;
  return (
    <article className="rounded-2xl border border-gray-100 shadow-panel bg-white px-4 py-4 ">
      <div className="flex items-start justify-between gap-3">
        <Link href={href} className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="min-w-0 font-semibold text-gray-900 hover:text-blue-600">{player.name}</h2>
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500">{player.sport}</span>
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-gray-400">
            {player.team}{player.position ? ` / ${player.position}` : ""} / {formatGameTime(player.next_game_time)}{player.next_game_time ? " ET" : ""}
          </p>
        </Link>
        <button
          type="button"
          onClick={() => onFollow(player)}
          disabled={busy}
          title={followed ? "Unfollow player" : "Follow player"}
          className={`flex flex-shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${followed ? "border-blue-200 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-blue-200 hover:text-blue-600"}`}
        >
          <Star size={13} fill={followed ? "currentColor" : "none"} />
          {followed ? "Following" : "Follow"}
        </button>
      </div>

      <StatisticsStatus coverage={player.statistics_coverage} />
      <OddsStatus offer={player} gameTime={player.next_game_time ?? undefined} />
      <Link href={href} className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-px overflow-hidden rounded-lg bg-gray-200">
        <div className="bg-gray-50 p-2.5"><p className="text-[10px] uppercase text-gray-400">{availabilityLabel(player, player.next_game_time ?? undefined)}</p><p className="mt-1 text-sm font-semibold text-gray-900">{player.live_prop_count}</p></div>
        <div className="bg-gray-50 p-2.5"><p className="text-[10px] uppercase text-gray-400">{formatPropType(player.top_prop?.prop_type ?? "Unavailable")}</p><p className="mt-1 text-sm font-semibold text-gray-900">{player.top_prop?.line ?? "—"}</p></div>
        <div className="bg-gray-50 p-2.5"><p className="text-[10px] uppercase text-gray-400">L5 / L10</p><p className="mt-1 text-sm font-semibold text-gray-900">{formatRate(player.top_prop?.l5_hit_rate ?? null)} / {formatRate(player.top_prop?.l10_hit_rate ?? null)}</p></div>
        <div className="bg-gray-50 p-2.5"><p className="text-[10px] uppercase text-gray-400">Movement</p><p className={`mt-1 flex items-center gap-1 text-sm font-semibold ${movement != null && movement > 0 ? "text-red-500" : movement != null && movement < 0 ? "text-emerald-600" : "text-gray-700"}`}>{movement != null && movement > 0 ? <TrendingUp size={13} /> : movement != null && movement < 0 ? <TrendingDown size={13} /> : null}{movement == null ? "-" : `${movement > 0 ? "+" : ""}${movement}`}</p></div>
      </Link>
      {isActionable(player, player.next_game_time ?? undefined) && player.top_prop?.best_over && (
        <p className="mt-2 text-xs text-gray-400">
          Best Over: <span className="font-medium text-emerald-600">{player.top_prop.best_over.sportsbook} {formatOdds(player.top_prop.best_over.odds)}</span> at {player.top_prop.best_over.line}
        </p>
      )}
    </article>
  );
}

function PlayersPageContent() {
  const searchParams = useSearchParams();
  const scope = new URLSearchParams();
  for (const key of ["season", "competition"]) {
    const value = searchParams.get(key);
    if (value) scope.set(key, value);
  }
  useOfferClock();
  const [mode, setMode] = useState<"search" | "watchlist">("search");
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("");
  const [players, setPlayers] = useState<PlayerSearchResult[]>([]);
  const [viewer, setViewer] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.searchPlayers({ q: query.trim(), sport: sport || undefined, limit: 30 });
      setPlayers(response.players);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not search players");
    } finally {
      setLoading(false);
    }
  }, [query, sport]);

  const loadWatchlist = useCallback(async () => {
    if (!viewer) {
      setPlayers([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setPlayers((await api.getPlayerWatchlist()).players);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not load My Players");
    } finally {
      setLoading(false);
    }
  }, [viewer]);

  useEffect(() => {
    api.getMe().then(setViewer).catch(() => setViewer(null));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (mode === "search") loadSearch();
      else loadWatchlist();
    }, mode === "search" ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [mode, loadSearch, loadWatchlist]);

  useLiveRefresh(() => mode === "search" ? loadSearch() : loadWatchlist(), loading);

  const toggleFollow = async (player: PlayerSearchResult) => {
    if (!viewer) {
      window.location.href = "/login";
      return;
    }
    const followed = viewer.fav_players.includes(player.id);
    setBusyId(player.id);
    try {
      if (followed) await api.unfollowPlayer(player.id);
      else await api.followPlayer(player.id);
      const nextFavorites = followed
        ? viewer.fav_players.filter((id) => id !== player.id)
        : [...viewer.fav_players, player.id];
      setViewer({ ...viewer, fav_players: nextFavorites });
      if (mode === "watchlist" && followed) {
        setPlayers((current) => current.filter((item) => item.id !== player.id));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update watchlist");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace">
        <header className="mb-5">
          <p className="eyebrow">Player directory</p><h1 className="page-title">Players</h1><p className="page-description mb-3">Find players, inspect their history, and build your watchlist.</p>
          <p className="mt-1 text-sm text-gray-400">Find live props and keep your research list close.</p>
        </header>

        <div className="mb-4 grid grid-cols-2 rounded-lg bg-gray-100 p-1">
          <button aria-pressed={mode === "search"} onClick={() => setMode("search")} className={`rounded-md px-3 py-2 text-sm font-medium ${mode === "search" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>Search</button>
          <button aria-pressed={mode === "watchlist"} onClick={() => setMode("watchlist")} className={`rounded-md px-3 py-2 text-sm font-medium ${mode === "watchlist" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>My Players{viewer?.fav_players.length ? ` (${viewer.fav_players.length})` : ""}</button>
        </div>

        {mode === "search" && (
          <div className="mb-4 space-y-3">
            <SearchField label="Search players" value={query} onChange={setQuery} placeholder="Search player, team, or abbreviation" />
            <div className="flex flex-wrap gap-2">
              {SPORTS.map((item) => <button key={item || "all"} aria-pressed={sport === item} onClick={() => setSport(item)} className={`rounded-full px-3 py-1 text-xs font-medium ${sport === item ? "bg-blue-600 text-[#ffffff]" : "bg-white text-gray-500 hover:bg-gray-100"}`}>{item || "All"}</button>)}
            </div>
          </div>
        )}

        {error && <div className="mb-4 border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">{error}</div>}
        {loading ? (
          <div className="space-y-2">{[1, 2, 3].map((item) => <div key={item} className="h-36 animate-pulse rounded-lg bg-white" />)}</div>
        ) : mode === "watchlist" && !viewer ? (
          <div className="empty-state"><Users size={28} className="mx-auto mb-3 text-gray-300" /><p className="font-medium text-gray-700">Sign in to build My Players</p><p className="mt-1 text-sm text-gray-400">Follow players to keep their live props and movement in one view.</p><Link href="/login" className="mt-4 inline-block text-sm font-medium text-blue-600">Sign in</Link></div>
        ) : players.length === 0 ? (
          <div className="empty-state"><Users size={28} className="mx-auto mb-3 text-gray-300" /><p className="font-medium text-gray-700">{mode === "watchlist" ? "No followed players with live props" : "No live players found"}</p><p className="mt-1 text-sm text-gray-400">{mode === "watchlist" ? "Use Search to follow a player." : "Try another name or sport."}</p></div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">{players.map((player) => <PlayerRow key={player.id} player={player} scope={scope.toString()} followed={viewer?.fav_players.includes(player.id) ?? false} busy={busyId === player.id} onFollow={toggleFollow} />)}</div>
        )}
      </div>
    </main>
  );
}

export default function PlayersPage() {
  return <Suspense fallback={<main className="p-6 text-gray-500">Loading players...</main>}><PlayersPageContent /></Suspense>;
}
