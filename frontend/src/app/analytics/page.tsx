"use client";
import { useLiveRefresh } from "@/lib/useLiveRefresh";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import {
  BarChart2,
  AlertCircle,
  RefreshCw,
  Zap,
  TrendingUp,
  Calendar,
  Users,
  Cpu,
  Database,
} from "lucide-react";
import { api } from "@/lib/api";
import SportRiskIntelligence from "@/components/SportRiskIntelligence";
import type {
  InsightsData,
  FatigueEdge,
  LineMover,
  B2BPlayer,
  TrendingProp,
  ModelStatus,
  OddsIngestionStatus,
  OddsIngestionSource,
} from "@/lib/types";

// ── Leaderboard types and constants (same as Day 4) ──────────────────────────

interface LeaderboardEntry {
  player: {
    id:        string;
    name:      string;
    team:      string;
    team_abbr: string;
  };
  fatigue_score: number;
  fatigue_label: "Critical" | "High" | "Medium" | "Low";
  risk_flags:    string[];
  back_to_back:  boolean;
}

type RiskLabel = "Critical" | "High" | "Medium" | "Low";

const LABEL_STYLES: Record<RiskLabel, { badge: string; bar: string; section: string }> = {
  Critical: {
    badge: "bg-red-50 text-red-700 border border-red-200",
    bar: "bg-red-500",
    section: "text-red-600",
  },
  High: {
    badge: "bg-orange-50 text-orange-700 border border-orange-200",
    bar: "bg-orange-500",
    section: "text-orange-600",
  },
  Medium: {
    badge: "bg-amber-50 text-amber-700 border border-amber-200",
    bar: "bg-amber-500",
    section: "text-amber-600",
  },
  Low: {
    badge: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    bar: "bg-emerald-500",
    section: "text-emerald-600",
  },
};

const FLAG_LABELS: Record<string, string> = {
  "back-to-back":        "B2B",
  "heavy-workload":      "Heavy load",
  "busy-week":           "Busy week",
  "high-minutes":        "High mins",
  "minutes-trending-up": "Mins up",
  "high-volatility":     "Volatile",
};

const LABEL_ORDER: RiskLabel[] = ["Critical", "High", "Medium", "Low"];

// ── Scoring formula definition ────────────────────────────────────────────────
// Weights must match ranking_service.py WEIGHTS dict exactly.

const SCORING_FORMULA = [
  {
    label:  "User affinity",
    weight: 30,
    color:  "bg-blue-500",
    desc:   "Your sport and betting history",
  },
  {
    label:  "Player affinity",
    weight: 20,
    color:  "bg-violet-500",
    desc:   "Players you track or have bet on",
  },
  {
    label:  "Prop type preference",
    weight: 15,
    color:  "bg-teal-500",
    desc:   "Your favorite prop categories",
  },
  {
    label:  "Popularity",
    weight: 15,
    color:  "bg-amber-500",
    desc:   "Engagement across all users",
  },
  {
    label:  "Line movement",
    weight: 10,
    color:  "bg-orange-500",
    desc:   "Significant 24h line shifts",
  },
  {
    label:  "Fatigue edge",
    weight: 10,
    color:  "bg-red-500",
    desc:   "Player workload and fatigue risk",
  },
];

const UNKNOWN_INGESTION_STATUS: OddsIngestionStatus = {
  source:              "unknown",
  fallback_used:       true,
  live_games_found:    0,
  live_props_updated:  0,
  mock_props_updated:  0,
  total_props_updated: 0,
  last_updated:        null,
  message:             "Odds ingestion status is not available yet.",
  matchups:            [],
  status_available:    false,
};

const INGESTION_SOURCE_LABELS: Record<OddsIngestionSource, string> = {
  mock:              "Mock fallback",
  odds_api_matchups: "Live matchups",
  odds_api_props:    "Live player props",
  cached_live:       "Last known odds",
  mixed:             "Mixed live + mock",
  unknown:           "Status unknown",
};

const INGESTION_SOURCE_STYLES: Record<OddsIngestionSource, string> = {
  mock:              "bg-amber-50 text-amber-700 border border-amber-100",
  odds_api_matchups: "bg-blue-50 text-blue-700 border border-blue-100",
  odds_api_props:    "bg-emerald-50 text-emerald-700 border border-emerald-100",
  cached_live:       "bg-blue-50 text-blue-700 border border-blue-100",
  mixed:             "bg-teal-50 text-teal-700 border border-teal-100",
  unknown:           "bg-gray-50 text-gray-400 border border-gray-100",
};

const AVAILABILITY_LABELS = {
  live: "Live",
  last_known: "Last known",
  unavailable: "Unavailable",
  no_games: "No games",
};

// ── InsightCard internal component ───────────────────────────────────────────

interface InsightCardProps {
  title:    string;
  subtitle: string;
  icon:     ReactNode;
  // topStrip is a full Tailwind bg class: "bg-red-400", "bg-blue-400", etc.
  // All four variants appear as literals in this file so Tailwind includes them.
  topStrip: "bg-red-400" | "bg-blue-400" | "bg-orange-400" | "bg-amber-400";
  children: ReactNode;
}

function InsightCard({
  title,
  subtitle,
  icon,
  topStrip,
  children,
}: InsightCardProps) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
      {/* Colored top accent strip */}
      <div className={`h-1 ${topStrip}`} />
      <div className="p-4">
        <div className="flex items-center gap-2 mb-1">
          {icon}
          <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        </div>
        <p className="text-xs text-gray-400 mb-3">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}

// ── Main page component ───────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [leaderboard,  setLeaderboard]  = useState<LeaderboardEntry[]>([]);
  const [insights,     setInsights]     = useState<InsightsData | null>(null);
  const [modelStatus,  setModelStatus]  = useState<ModelStatus | null>(null);
  const [oddsStatus,   setOddsStatus]   = useState<OddsIngestionStatus | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);

    // Fetch leaderboard and insights in parallel.
    // If either fails the error state covers both.
    return Promise.all([
      api.getFatigueLeaderboard(),
      api.getInsights(),
      api.getModelStatus(),
      api.getIngestionStatus().catch(() => UNKNOWN_INGESTION_STATUS),
    ])
      .then(([lb, ins, ms, odds]) => {
        setLeaderboard(lb as LeaderboardEntry[]);
        setInsights(ins);
        setModelStatus(ms as ModelStatus);
        setOddsStatus(odds);
      })
      .catch((e: any) =>
        setError(e.message || "Failed to load risk data.")
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  useLiveRefresh(load, loading);

  // Group leaderboard entries by risk label for the grouped view.
  const grouped = LABEL_ORDER.reduce<Record<RiskLabel, LeaderboardEntry[]>>(
    (acc, label) => {
      acc[label] = leaderboard.filter((e) => e.fatigue_label === label);
      return acc;
    },
    { Critical: [], High: [], Medium: [], Low: [] }
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace">

        {/* ── Page header ── */}
        <div className="page-heading">
          <div>
            <p className="eyebrow">Beyond the box score</p><h1 className="page-title">
              Risk Intelligence
            </h1><p className="page-description mb-3">Explore recorded workload, schedule context, and market movement.</p>
            <p className="text-sm text-gray-400 mt-1">
              Player workload, schedule context, and market signals
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh legacy data
          </button>
        </div>

        {/* ── Error state ── */}
        <SportRiskIntelligence />

        <div className="mb-4 rounded-xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-gray-700">Legacy NBA demo and market signals</h2>
          <p className="mt-1 text-xs text-gray-500">The fatigue leaderboard and model below are an NBA demo. They do not provide calibrated predictions for other sports. Use the sport-specific coverage above for current workload assessments.</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-100 rounded-xl p-5 mb-5 flex flex-col items-center text-center">
            <AlertCircle size={20} className="text-red-400 mb-2" />
            <p className="text-sm font-medium text-red-700">
              Could not load legacy NBA and market data
            </p>
            <p className="text-xs text-red-400 mt-1 mb-3">{error}</p>
            <button
              onClick={load}
              className="flex items-center gap-1.5 text-xs text-red-600 border border-red-200 px-3 py-1.5 rounded-lg hover:text-red-800 transition-colors"
            >
              <RefreshCw size={12} />
              Try again
            </button>
          </div>
        )}

        {/* ── Loading skeleton ── */}
        {loading && !error && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[...Array(4)].map((_, i) => (
                <div
                  key={i}
                  className="bg-white rounded-2xl border border-gray-100 h-44 animate-pulse"
                />
              ))}
            </div>
            <div className="bg-white rounded-2xl border border-gray-100 h-52 animate-pulse" />
            <div className="bg-white rounded-2xl border border-gray-100 h-64 animate-pulse" />
          </div>
        )}

        {/* ── Main content (rendered only when not loading and no error) ── */}
        {!loading && !error && (
          <>
            {/* ============================================================ */}
            {/* SECTION 1: Insights grid                                      */}
            {/* Four cards in a 2x2 grid. Each card covers one data dimension */}
            {/* ============================================================ */}
            {insights && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-5">

                {/* Card 1: Fatigue edges */}
                <InsightCard
                  title="Fatigue edges tonight"
                  subtitle="Players flagged for elevated under risk"
                  icon={<Zap size={15} className="text-red-500 flex-shrink-0" />}
                  topStrip="bg-red-400"
                >
                  {insights.fatigue_edges.length === 0 ? (
                    <p className="text-xs text-gray-300 py-2">
                      No high-fatigue players tonight
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {insights.fatigue_edges.slice(0, 4).map((edge: FatigueEdge) => (
                        <div
                          key={edge.player.id}
                          className="flex items-center justify-between"
                        >
                          <div className="min-w-0 mr-2">
                            <Link
                              href={`/player/${edge.player.id}`}
                              className="text-xs font-medium text-gray-800 hover:text-blue-600 truncate block"
                            >
                              {edge.player.name}
                            </Link>
                            <p className="text-xs text-gray-400 capitalize">
                              {edge.prop.prop_type} / {edge.prop.line}
                            </p>
                          </div>
                          <div className="flex-shrink-0 text-right">
                            <span
                              className={`text-xs font-semibold px-1.5 py-0.5 rounded-full ${
                                edge.fatigue_label === "Critical"
                                  ? "bg-red-50 text-red-700"
                                  : "bg-orange-50 text-orange-700"
                              }`}
                            >
                              {Math.round(edge.fatigue_score * 100)}%
                            </span>
                            {edge.back_to_back && (
                              <p className="text-xs text-red-500 mt-0.5 leading-none">
                                B2B
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </InsightCard>

                {/* Card 2: Line movers */}
                <InsightCard
                  title="Biggest line movers"
                  subtitle="Significant 24h shifts"
                  icon={
                    <TrendingUp size={15} className="text-blue-500 flex-shrink-0" />
                  }
                  topStrip="bg-blue-400"
                >
                  {insights.line_movers.length === 0 ? (
                    <p className="text-xs text-gray-300 py-2">
                      No recorded line movement available.
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {insights.line_movers.slice(0, 4).map(
                        (mover: LineMover, i: number) => (
                          <div
                            key={i}
                            className="flex items-center justify-between"
                          >
                            <div className="min-w-0 mr-2">
                              <Link
                                href={`/player/${mover.player_id}`}
                                className="text-xs font-medium text-gray-800 hover:text-blue-600 truncate block"
                              >
                                {mover.player_name}
                              </Link>
                              <p className="text-xs text-gray-400 capitalize">
                                {mover.prop_type} / {mover.line}
                              </p>
                            </div>
                            <div className="flex-shrink-0 text-right">
                              <span
                                className={`text-xs font-semibold block ${
                                  mover.direction === "up"
                                    ? "text-red-600"
                                    : "text-emerald-600"
                                }`}
                              >
                                {mover.direction === "up" ? "+" : ""}
                                {mover.movement}
                              </span>
                              <span className="text-xs text-gray-400">
                                was {mover.line_24h_ago}
                              </span>
                            </div>
                          </div>
                        )
                      )}
                    </div>
                  )}
                </InsightCard>

                {/* Card 3: Back-to-back alert */}
                <InsightCard
                  title="Back-to-back alert"
                  subtitle="Playing on consecutive nights"
                  icon={
                    <Calendar
                      size={15}
                      className="text-orange-500 flex-shrink-0"
                    />
                  }
                  topStrip="bg-orange-400"
                >
                  {insights.back_to_back_tonight.length === 0 ? (
                    <p className="text-xs text-gray-300 py-2">
                      No back-to-back games detected tonight
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {insights.back_to_back_tonight
                        .slice(0, 4)
                        .map((entry: B2BPlayer) => (
                          <div
                            key={entry.player.id}
                            className="flex items-center justify-between"
                          >
                            <div className="min-w-0 mr-2">
                              <Link
                                href={`/player/${entry.player.id}`}
                                className="text-xs font-medium text-gray-800 hover:text-blue-600 truncate block"
                              >
                                {entry.player.name}
                              </Link>
                              <p className="text-xs text-gray-400">
                                {entry.games_in_7d} games in 7 days
                              </p>
                            </div>
                            <span className="text-xs font-semibold bg-orange-50 text-orange-700 px-1.5 py-0.5 rounded-full flex-shrink-0">
                              {Math.round(entry.fatigue_score * 100)}%
                            </span>
                          </div>
                        ))}
                    </div>
                  )}
                </InsightCard>

                {/* Card 4: Trending now */}
                <InsightCard
                  title="Trending now"
                  subtitle="Most popular props tonight"
                  icon={
                    <Users size={15} className="text-amber-500 flex-shrink-0" />
                  }
                  topStrip="bg-amber-400"
                >
                  {insights.trending.length === 0 ? (
                    <p className="text-xs text-gray-300 py-2">
                      No popularity data yet
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {insights.trending.slice(0, 4).map(
                        (entry: TrendingProp, i: number) => (
                          <div
                            key={i}
                            className="flex items-center justify-between"
                          >
                            <div className="min-w-0 mr-2">
                              <Link
                                href={`/player/${entry.player_id}`}
                                className="text-xs font-medium text-gray-800 hover:text-blue-600 truncate block"
                              >
                                {entry.player_name}
                              </Link>
                              <p className="text-xs text-gray-400 capitalize">
                                {entry.prop_type} / {entry.line}
                              </p>
                            </div>
                            <span className="text-xs text-gray-400 flex-shrink-0">
                              {entry.popularity_count} interactions
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  )}
                </InsightCard>

              </div>
            )}

            {/* ============================================================ */}
            {/* SECTION 1b: Odds Ingestion Status                             */}
            {/* Shows whether market data is live, mixed, or mock fallback.   */}
            {/* ============================================================ */}
            {oddsStatus && (
              <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden mb-5">
                <div className="h-1 bg-teal-400" />
                <div className="p-5">
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <Database size={15} className="text-teal-500 flex-shrink-0" />
                      <h2 className="text-sm font-semibold text-gray-800">
                        Odds Ingestion Status
                      </h2>
                    </div>
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${INGESTION_SOURCE_STYLES[oddsStatus.source]}`}
                    >
                      {INGESTION_SOURCE_LABELS[oddsStatus.source]}
                    </span>
                  </div>

                  <p className="text-xs text-gray-400 mb-4 leading-snug">
                    {oddsStatus.message}
                  </p>

                  <div className="grid grid-cols-3 gap-2 mb-4">
                    <div className="bg-gray-50 rounded-xl p-3 text-center">
                      <p className="text-lg font-bold text-gray-900">
                        {oddsStatus.live_games_found}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">Events found</p>
                    </div>
                    <div className="bg-gray-50 rounded-xl p-3 text-center">
                      <p className="text-lg font-bold text-gray-900">
                        {oddsStatus.live_props_updated}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">Live props</p>
                    </div>
                    <div className="bg-gray-50 rounded-xl p-3 text-center">
                      <p className="text-lg font-bold text-gray-900">
                        {oddsStatus.mock_props_updated}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">Mock shifts</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between gap-4 text-xs">
                      <span className="text-gray-400">Fallback active</span>
                      <span className="text-gray-700 font-medium">
                        {oddsStatus.fallback_used ? "Yes" : "No"}
                      </span>
                    </div>
                    {oddsStatus.quota_requests_remaining !== null &&
                      oddsStatus.quota_requests_remaining !== undefined && (
                        <div className="flex justify-between gap-4 text-xs">
                          <span className="text-gray-400">API requests remaining</span>
                          <span className="text-gray-700 font-medium">
                            {oddsStatus.quota_requests_remaining}
                          </span>
                        </div>
                      )}
                    <div className="flex justify-between gap-4 text-xs">
                      <span className="text-gray-400">Last updated</span>
                      <span className="text-gray-700 font-medium text-right">
                        {oddsStatus.last_updated
                          ? new Date(oddsStatus.last_updated).toLocaleString("en-US", {
                              month: "short",
                              day:   "numeric",
                              hour:  "numeric",
                              minute: "2-digit",
                            })
                          : "--"}
                      </span>
                    </div>
                    {oddsStatus.line_moved_up !== undefined &&
                      oddsStatus.line_moved_down !== undefined &&
                      oddsStatus.line_unchanged !== undefined && (
                        <div className="flex justify-between gap-4 text-xs">
                          <span className="text-gray-400">Line movement</span>
                          <span className="text-gray-700 font-medium text-right">
                            {oddsStatus.line_moved_up} up / {oddsStatus.line_moved_down} down / {oddsStatus.line_unchanged} flat
                          </span>
                        </div>
                      )}
                  </div>

                  {oddsStatus.sports && (
                    <div className="mt-4 border-t border-gray-100 pt-3">
                      <p className="mb-2 text-xs font-medium text-gray-500">Sport availability</p>
                      <div className="divide-y divide-gray-100">
                        {Object.entries(oddsStatus.sports).map(([sportKey, status]) => (
                          <div key={sportKey} className="flex items-start justify-between gap-3 py-2 text-xs">
                            <div>
                              <span className="font-medium text-gray-700">{status.sport}</span>
                              {status.provider_error_message && (
                                <p className="mt-0.5 max-w-md text-gray-400">
                                  {status.provider_error_code ? `${status.provider_error_code}: ` : ""}
                                  {status.provider_error_message}
                                </p>
                              )}
                            </div>
                            <div className="flex-shrink-0 text-right">
                              <span className="font-medium text-gray-600">
                                {AVAILABILITY_LABELS[status.availability]}
                              </span>
                              <p className="mt-0.5 text-gray-400">
                                {status.current_prop_count ?? (status.live_props_matched || status.cached_live_props)} props
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {oddsStatus.matchups.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-gray-50">
                      <p className="text-xs text-gray-400 mb-1.5">
                        Live matchup context
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {oddsStatus.matchups.slice(0, 6).map((matchup) => (
                          <span
                            key={matchup}
                            className="text-xs bg-blue-50 text-blue-700 border border-blue-100 px-1.5 py-0.5 rounded"
                          >
                            {matchup}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ============================================================ */}
            {/* SECTION 1c: ML Pipeline Status                                */}
            {/* Read-only panel showing model artifact metadata.              */}
            {/* ============================================================ */}
            {modelStatus && (
              <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden mb-5">
                <div className="h-1 bg-violet-400" />
                <div className="p-5">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Cpu size={15} className="text-violet-500" />
                      <h2 className="text-sm font-semibold text-gray-800">
                        Legacy NBA Model Status
                      </h2>
                    </div>
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        modelStatus.model_exists
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
                          : "bg-gray-50 text-gray-400 border border-gray-100"
                      }`}
                    >
                      {modelStatus.model_exists ? "Model loaded" : "Not trained"}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mb-4">
                    NBA-only demo model. Its metrics do not validate the multi-sport workload indicators above.
                  </p>

                  {modelStatus.meta_available ? (
                    <>
                      {/* Metric row */}
                      <div className="grid grid-cols-3 gap-2 mb-4">
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-lg font-bold text-gray-900">
                            {modelStatus.auc?.toFixed(3)}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">AUC</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-lg font-bold text-gray-900">
                            {modelStatus.accuracy !== null
                              ? `${Math.round(modelStatus.accuracy * 100)}%`
                              : "--"}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">Accuracy</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-lg font-bold text-gray-900">
                            {modelStatus.feature_count}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">Features</p>
                        </div>
                      </div>

                      {/* Training info */}
                      <div className="space-y-2 mb-4">
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Training rows</span>
                          <span className="text-gray-700 font-medium">
                            {modelStatus.n_train?.toLocaleString()} train / {modelStatus.n_test?.toLocaleString()} test
                          </span>
                        </div>
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Data source</span>
                          <span className="text-gray-700 font-medium capitalize">
                            {modelStatus.data_source === "mock"
                              ? "Mock game logs (synthetic)"
                              : "Live NBA game logs"}
                          </span>
                        </div>
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Last trained</span>
                          <span className="text-gray-700 font-medium">
                            {modelStatus.trained_at
                              ? new Date(modelStatus.trained_at).toLocaleDateString("en-US", {
                                  month: "short",
                                  day:   "numeric",
                                  year:  "numeric",
                                })
                              : "--"}
                          </span>
                        </div>
                        {modelStatus.calibration && (
                          <div className="flex justify-between text-xs">
                            <span className="text-gray-400">Calibration</span>
                            <span className="text-gray-700 font-medium">
                              Rested {Math.round((modelStatus.calibration.rested_score ?? 0) * 100)}% /
                              B2B {Math.round((modelStatus.calibration.b2b_score ?? 0) * 100)}%
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Feature chips */}
                      <div>
                        <p className="text-xs text-gray-400 mb-1.5">Features used</p>
                        <div className="flex flex-wrap gap-1">
                          {modelStatus.feature_cols.map((f) => (
                            <span
                              key={f}
                              className="text-xs bg-violet-50 text-violet-700 border border-violet-100 px-1.5 py-0.5 rounded font-mono"
                            >
                              {f}
                            </span>
                          ))}
                        </div>
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-gray-400 py-2">
                      No model metadata is available. Legacy model details will appear when supplied.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* ============================================================ */}
            {/* SECTION 2: How PropPulse ranks props                          */}
            {/* Visual breakdown of the scoring formula with weight bars.     */}
            {/* Weights match ranking_service.py WEIGHTS dict exactly.       */}
            {/* ============================================================ */}
            <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-5">
              <h2 className="font-semibold text-gray-800 mb-1">
                How PropPulse ranks props
              </h2>
              <p className="text-xs text-gray-400 mb-5">
                Every prop gets a composite score from six weighted signals.
                The feed re-ranks on each page load.
              </p>

              <div className="space-y-3.5">
                {SCORING_FORMULA.map(({ label, weight, color, desc }) => (
                  <div key={label}>
                    <div className="flex items-center gap-2 mb-0.5">
                      {/* Label column: w-36 = 144px, matches pl-36 indent on desc */}
                      <span className="text-xs text-gray-700 w-36 flex-shrink-0 font-medium leading-none">
                        {label}
                      </span>
                      {/* Weight bar: scaled so 30% fills ~99% of available space */}
                      <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${color}`}
                          style={{ width: `${weight * 3.3}%` }}
                        />
                      </div>
                      {/* Actual percentage shown on right */}
                      <span className="text-xs font-semibold text-gray-700 w-7 text-right flex-shrink-0">
                        {weight}%
                      </span>
                    </div>
                    {/* Description indented to align with bar start */}
                    <p className="text-xs text-gray-400 pl-36 leading-none">
                      {desc}
                    </p>
                  </div>
                ))}
              </div>

              <p className="text-xs text-gray-300 mt-4 pt-3 border-t border-gray-50">
                Personalization strengthens as you interact.
                New users see a popularity-weighted feed by default.
              </p>
            </div>

            {/* ============================================================ */}
            {/* SECTION 3: Fatigue leaderboard                                */}
            {/* Grouped by risk label. Same as Day 4, no changes.            */}
            {/* ============================================================ */}
            {leaderboard.length === 0 ? (
              <div className="empty-state text-gray-400">
                <BarChart2
                  size={40}
                  className="text-gray-200 mx-auto mb-3"
                />
                <p className="font-medium">No risk data available</p>
                <p className="text-sm mt-1 text-gray-300">
                  Legacy demo data is unavailable.
                </p>
              </div>
            ) : (
              <>
                {/* Summary counts row */}
                <div className="grid grid-cols-4 gap-2 mb-4">
                  {LABEL_ORDER.map((label) => {
                    const count = grouped[label].length;
                    const cfg   = LABEL_STYLES[label];
                    return (
                      <div
                        key={label}
                        className="bg-white border border-gray-100 rounded-xl p-3 text-center"
                      >
                        <p className="text-xl font-bold text-gray-900">
                          {count}
                        </p>
                        <p className={`text-xs font-medium mt-0.5 ${cfg.section}`}>
                          {label}
                        </p>
                      </div>
                    );
                  })}
                </div>

                {/* Grouped leaderboard entries */}
                <div className="space-y-5">
                  {LABEL_ORDER.map((label) => {
                    const entries = grouped[label];
                    if (entries.length === 0) return null;
                    const cfg = LABEL_STYLES[label];

                    return (
                      <div key={label}>
                        <h2
                          className={`text-xs font-semibold uppercase tracking-wider mb-2.5 ${cfg.section}`}
                        >
                          {label} risk / {entries.length} player
                          {entries.length !== 1 ? "s" : ""}
                        </h2>

                        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
                          {entries.map((entry, i) => {
                            const pct = Math.round(entry.fatigue_score * 100);
                            return (
                              <div
                                key={entry.player.id}
                                className="px-5 py-4 border-b border-gray-50 last:border-0"
                              >
                                {/* Player row: rank + name + badges */}
                                <div className="flex items-center justify-between mb-2.5">
                                  <div className="flex items-center gap-3">
                                    <span className="text-xs text-gray-300 w-4 flex-shrink-0">
                                      {i + 1}
                                    </span>
                                    <div>
                                      <Link
                                        href={`/player/${entry.player.id}`}
                                        className="text-sm font-semibold text-gray-900 hover:text-blue-600 transition-colors"
                                      >
                                        {entry.player.name}
                                      </Link>
                                      <p className="text-xs text-gray-400">
                                        {entry.player.team}
                                      </p>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2 flex-shrink-0">
                                    {entry.back_to_back && (
                                      <span className="text-xs bg-red-50 text-red-600 border border-red-100 px-2 py-0.5 rounded-full font-medium">
                                        B2B
                                      </span>
                                    )}
                                    <span
                                      className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${cfg.badge}`}
                                    >
                                      {pct}%
                                    </span>
                                  </div>
                                </div>

                                {/* Score bar + risk flag chips */}
                                <div className="flex items-center gap-3 pl-7">
                                  <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                                    <div
                                      className={`h-full rounded-full ${cfg.bar}`}
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                  <div className="flex gap-1 flex-shrink-0">
                                    {entry.risk_flags.slice(0, 3).map((flag) => (
                                      <span
                                        key={flag}
                                        className="text-xs text-gray-400 bg-gray-50 border border-gray-100 px-1.5 py-0.5 rounded"
                                      >
                                        {FLAG_LABELS[flag] || flag}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

          </>
        )}

      </div>
    </main>
  );
}
