"use client";
import { useOfferClock } from "@/lib/useOfferClock";
import { availabilityLabel, isActionable } from "@/lib/propSides";
import { useLiveRefresh } from "@/lib/useLiveRefresh";
import { useState, useEffect, useCallback, useRef } from "react";
import { gameHref, gameIdentityValue, formatGameContext, errorMessage } from "@/lib/gameNavigation";
import { createRequestGate } from "@/lib/requestGate";
import Link from "next/link";
import { AlertCircle, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { useAuth } from "@/store/auth";
import { api }         from "@/lib/api";
import type { OddsIngestionStatus, Prop, TodayGame } from "@/lib/types";
import { PropCard }    from "@/components/PropCard";
import { FeedFilters } from "@/components/FeedFilters";

// Three steps shown to unauthenticated users as a compact demo prompt.
// The prompt disappears when the user is logged in.
const DEMO_STEPS = [
  {
    step: "1",
    text: "Sign in to tailor the board to your sports and markets",
  },
  {
    step: "2",
    text: "Bookmark props and add to slip - persists after page refresh",
  },
  {
    step: "3",
    text: "Explore Insights for recorded workload and schedule context",
  },
];

const NOT_REFRESHED_STATUS: OddsIngestionStatus = {
  source:              "not_refreshed" as OddsIngestionStatus["source"],
  fallback_used:       true,
  live_games_found:    0,
  live_props_updated:  0,
  mock_props_updated:  0,
  total_props_updated: 0,
  last_updated:        null,
  refreshed_at:        null,
  message:             "Run python scripts/fetch_odds.py",
  matchups:            [],
  status_available:    false,
};

function formatStatusTime(value?: string | null): string | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  const time = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  }).format(date);
  return `${time} ET`;
}

function formatCacheAge(minutes?: number | null): string | null {
  if (minutes === null || minutes === undefined) return null;
  if (minutes < 1) return "less than a minute";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function getStatusLabel(status: OddsIngestionStatus | null): string {
  if (status?.current_offer_status) return availabilityLabel(status.current_offer_status, status.current_offer_status.game_time ?? undefined);
  if (status?.availability === "live") return "Live odds";
  if (status?.availability === "last_known") return "Last known odds";
  return "Odds unavailable";
}

function getStatusClasses(status: OddsIngestionStatus | null): string {
  if (status?.current_offer_status && !isActionable(status.current_offer_status, status.current_offer_status.game_time ?? undefined)) return "bg-amber-50 text-amber-700 border-amber-100";
  if (status?.availability === "live") return "bg-emerald-50 text-emerald-700 border-emerald-100";
  if (status?.availability === "last_known") return "bg-blue-50 text-blue-700 border-blue-100";
  return "bg-amber-50 text-amber-700 border-amber-100";
}

function getEmptyTitle(sport: string): string {
  if (sport) return `No ${sport} props available right now`;
  return "No props available right now";
}

function getGameSourceLabel(game: TodayGame): string {
  if (game.source === "live") return "Live";
  if (game.source === "cached" || game.source === "last_known") return "Last known";
  return "Unavailable";
}

export default function FeedPage() {
  useOfferClock();
  const [props,      setProps]      = useState<Prop[]>([]);
  const [games,      setGames]      = useState<TodayGame[]>([]);
  const [total,      setTotal]      = useState(0);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [sport,      setSport]      = useState("");
  const [propType,   setPropType]   = useState("");
  const isLoggedIn = useAuth(s => s.status === "authenticated");
  const [updatedAt,  setUpdatedAt]  = useState<string | null>(null);
  const [oddsStatus, setOddsStatus] = useState<OddsIngestionStatus | null>(null);
  const requestGate = useRef(createRequestGate());

  // Controls whether the demo tips panel is expanded.
  // Defaults to true (open) so first-time visitors see it.
  const [tipsOpen, setTipsOpen] = useState(true);

  const loadFeed = useCallback(async () => {
    const request = requestGate.current.start();
    setLoading(true);
    setError(null);
    try {
      const feedParams = {
        sport:     sport     || undefined,
        prop_type: propType  || undefined,
        limit:     20,
      };
      const [firstPage, gamesData] = await Promise.all([
        api.getFeed(feedParams, request.signal),
        api.getGames({
          sport: sport || undefined,
          limit: 8,
        }, request.signal),
      ]);
      if (!request.isCurrent()) return;

      setProps(firstPage.props);
      setGames(gamesData);
      setTotal(firstPage.total);

      setUpdatedAt(
        formatStatusTime(firstPage.refreshed_at)
      );

      api
        .getIngestionStatus()
        .then((status) => { if (request.isCurrent()) setOddsStatus(status); })
        .catch(() => { if (request.isCurrent()) setOddsStatus(NOT_REFRESHED_STATUS); });
    } catch (e: unknown) {
      if (!request.isCurrent()) return;
      setError(errorMessage(e, "feed"));
      setGames([]);
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [sport, propType]);

  useEffect(() => {
    loadFeed();
    return () => requestGate.current.cancel();
  }, [loadFeed]);

  useLiveRefresh(loadFeed, loading);

  const handleSportChange = (nextSport: string) => {
    requestGate.current.cancel();
    setSport(nextSport);
    setPropType("");
  };

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace">

        {/* Board header */}
        <div className="page-heading">
          <div>
            <p className="eyebrow">Your daily workspace</p><h1 className="page-title">Today's Board</h1><p className="page-description mb-3">Follow the schedule, compare offers, and keep your research moving.</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-gray-400">
                {total} active props
              </span>
              {updatedAt && (
                <>
                  <span className="text-gray-200 select-none">|</span>
                  <span className="text-sm text-gray-400">
                    Updated {updatedAt}
                  </span>
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <span
                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getStatusClasses(oddsStatus)}`}
              >
                {getStatusLabel(oddsStatus)}
              </span>
              <span className="text-xs text-gray-400">
                {oddsStatus?.current_prop_count ?? 0} available props
              </span>
              {oddsStatus?.availability === "last_known" && formatCacheAge(oddsStatus.cache_age_minutes) && (
                <span className="text-xs text-gray-400">Oldest eligible observation {formatCacheAge(oddsStatus.cache_age_minutes)} old</span>
              )}
              {formatStatusTime(oddsStatus?.last_updated) && (
                <span className="text-xs text-gray-400">Last ingestion {formatStatusTime(oddsStatus?.last_updated)}</span>
              )}
              {String(oddsStatus?.source) === "not_refreshed" && (
                <span className="text-xs text-gray-400">
                  No ingestion observation available
                </span>
              )}
            </div>
          </div>

          <button
            onClick={loadFeed}
            disabled={loading}
            title="Refresh feed"
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-300 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40 mt-1"
          >
            <RefreshCw
              size={12}
              className={loading ? "animate-spin" : ""}
            />
            Refresh
          </button>
        </div>

        {/* Personalization banner */}
        {isLoggedIn ? (
          <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 mb-4">
            <span className="text-sm font-medium text-blue-800">
              Personalized for you
            </span>
            <span className="text-sm text-blue-500 ml-2">
              / ranked by your preferences and history
            </span>
          </div>
        ) : (
          /* Unauthenticated: sign-in prompt + collapsible demo tips */
          <div className="mb-4">
            <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Trending props /{"  "}
                <Link
                  href="/login"
                  className="text-blue-600 font-medium hover:underline"
                >
                  Sign in for a personalized feed
                </Link>
              </p>
              <button
                onClick={() => setTipsOpen((o) => !o)}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 ml-3 flex-shrink-0"
                title={tipsOpen ? "Hide demo tips" : "Show demo tips"}
              >
                {tipsOpen ? (
                  <ChevronUp size={14} />
                ) : (
                  <ChevronDown size={14} />
                )}
                <span className="hidden sm:inline">
                  {tipsOpen ? "Hide tips" : "Demo tips"}
                </span>
              </button>
            </div>

            {/* Collapsible demo steps panel */}
            {tipsOpen && (
              <div className="bg-gray-50 border border-gray-100 border-t-0 rounded-b-xl px-4 py-3">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                  Build your research routine
                </p>
                <div className="space-y-1.5">
                  {DEMO_STEPS.map(({ step, text }) => (
                    <div key={step} className="flex items-start gap-2.5">
                      <span className="w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                        {step}
                      </span>
                      <p className="text-xs text-gray-500 leading-snug">
                        {text}
                      </p>
                    </div>
                  ))}
                </div>
                <Link
                  href="/login"
                  className="inline-flex items-center gap-1 mt-3 text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors"
                >
                  Sign in to start
                </Link>
              </div>
            )}
          </div>
        )}

        {/* Filters */}
        <div className="filter-panel">
          <FeedFilters
            sport={sport}
            propType={propType}
            onSport={handleSportChange}
            onPropType={(value) => { requestGate.current.cancel(); setPropType(value); }}
          />
        </div>

        {/* Today's games */}
        {!error && !loading && (
          <section className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-gray-700">
                Upcoming Games
              </h2>
              <span className="text-xs text-gray-400">
                {sport || "All sports"}
              </span>
            </div>
            {games.length > 0 ? (
              <div className="bg-white border border-gray-100 rounded-xl divide-y divide-gray-100">
                {games.map((game) => (
                  <Link
                    key={gameIdentityValue(game)}
                    href={gameHref(game)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">
                        {game.away_team} @ {game.home_team}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {formatGameContext(game)}{game.identity_source !== "authoritative" ? " · Legacy / unverified" : ""}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className="text-sm font-semibold text-gray-800">
                        {game.prop_count} props
                      </p>
                      <p className="text-xs text-gray-400">
                        {getGameSourceLabel(game)}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="bg-white border border-gray-100 rounded-xl px-4 py-4 text-sm text-gray-400">
                No games with props available right now.
              </div>
            )}
          </section>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-100 rounded-xl p-5 mb-5 flex flex-col items-center text-center">
            <AlertCircle size={20} className="text-red-400 mb-2" />
            <p className="text-sm font-medium text-red-700">
              Could not load feed
            </p>
            <p className="text-xs text-red-400 mt-1 mb-3">{error}</p>
            <button
              onClick={loadFeed}
              className="flex items-center gap-1.5 text-xs text-red-600 hover:text-red-800 border border-red-200 px-3 py-1.5 rounded-lg transition-colors"
            >
              <RefreshCw size={12} />
              Try again
            </button>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !error && (
          <div className="space-y-3">
            {[...Array(4)].map((_, i) => (
              <div
                key={i}
                className="bg-white rounded-2xl border border-gray-100 h-52 animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Empty */}
        {!loading && !error && props.length === 0 && (
          <div className="empty-state text-gray-400">
            <p className="text-4xl mb-3 font-bold text-gray-200">
              {sport || "Props"}
            </p>
            <p className="font-medium">
              {getEmptyTitle(sport)}
            </p>
            <p className="text-sm mt-1">
              Current sportsbook coverage is unavailable. Check back closer to game time.
            </p>
            <button
              onClick={loadFeed}
              className="mt-4 text-xs text-blue-600 hover:underline"
            >
              Reload feed
            </button>
          </div>
        )}

        {/* Cards */}
        {!loading && !error && props.length > 0 && (
          <div className="prop-grid">
            {props.map((prop) => (
              <PropCard key={prop.id} prop={prop} />
            ))}
          </div>
        )}

      </div>
    </main>
  );
}
