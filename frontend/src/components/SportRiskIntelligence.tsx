"use client";
import { useLiveRefresh } from "@/lib/useLiveRefresh";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { SportRiskIntelligenceData } from "@/lib/types";

const SPORTS = ["All", "NBA", "WNBA", "MLB", "NFL", "NHL"];

function readable(value: string) {
  return value.replace(/[_-]/g, " ");
}

export default function SportRiskIntelligence() {
  const [sport, setSport] = useState("All");
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<SportRiskIntelligenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useLiveRefresh(() => setRevision((value) => value + 1), loading);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    api.getRiskIntelligence(sport === "All" ? undefined : sport, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Risk intelligence is unavailable.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sport, revision]);

  return (
    <section aria-labelledby="sport-risk-title" className="mb-6 overflow-hidden rounded-2xl border border-blue-100 bg-white">
      <div className="h-1 bg-blue-500" />
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="sport-risk-title" className="font-semibold text-gray-900">Workload across sports</h2>
            <p className="mt-1 text-xs leading-relaxed text-gray-500">
              Sport-specific workload and schedule signals for upcoming player props.
              Scores are relative indicators out of 100, not injury or betting outcome probabilities.
            </p>
          </div>
          <button type="button" onClick={() => setRevision((value) => value + 1)} disabled={loading}
            aria-label="Refresh sport risk intelligence"
            className="rounded-lg border border-gray-200 p-2 text-gray-500 hover:text-blue-600 disabled:opacity-40">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        <div role="group" aria-label="Filter risk intelligence by sport" className="my-4 flex flex-wrap gap-2">
          {SPORTS.map((name) => (
            <button key={name} type="button" aria-pressed={sport === name} onClick={() => setSport(name)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium ${sport === name ? "border-blue-600 bg-blue-600 text-[#ffffff]" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
              {name}
            </button>
          ))}
        </div>

        {loading && <p role="status" className="py-5 text-sm text-gray-500">Loading {sport === "All" ? "all sports" : sport} risk intelligence...</p>}
        {error && (
          <div role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">
            <p>Could not load sport risk intelligence.</p>
            <p className="mt-1 text-xs">{error}</p>
            <button type="button" onClick={() => setRevision((value) => value + 1)} className="mt-3 rounded border border-red-200 px-3 py-1 text-xs">Try again</button>
          </div>
        )}

        {data && !loading && !error && (
          <>
            <div className="mb-4 grid gap-2 sm:grid-cols-2">
              {data.sports.map((coverage) => (
                <div key={coverage.sport} className="rounded-xl bg-gray-50 p-3 text-xs">
                  <div className="flex justify-between gap-2">
                    <span className="font-semibold text-gray-800">{coverage.sport}</span>
                    <span className="capitalize text-gray-500">{readable(coverage.status)}</span>
                  </div>
                  <p className="mt-1 text-gray-600">{coverage.assessed_players} of {coverage.active_players} players with upcoming props assessed</p>
                  <p className="mt-1 leading-relaxed text-gray-500">{coverage.description}</p>
                </div>
              ))}
            </div>
            {data.players.length === 0 && (
              <p className="rounded-xl bg-gray-50 p-4 text-sm text-gray-500">No players with upcoming props are available for this selection. Coverage will update when schedules, props, and recent history are available.</p>
            )}
            <div className="space-y-3">
              {data.players.map((entry) => (
                <article key={entry.player.id} className="rounded-xl border border-gray-100 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <Link href={`/player/${entry.player.id}`} className="text-sm font-semibold text-gray-800 hover:text-blue-600">{entry.player.name}</Link>
                      <p className="mt-0.5 text-xs text-gray-500">{entry.player.sport} · {entry.player.team_abbr}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold text-gray-900">{entry.score === null ? "Not assessed" : `${Math.round(entry.score * 100)}/100`}</p>
                      <p className="text-xs text-gray-500">{entry.label}</p>
                    </div>
                  </div>
                  <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                    <div><dt className="text-gray-500">{entry.workload.label}</dt><dd className="mt-0.5 text-gray-800">{entry.workload.value === null ? "Unavailable" : `${entry.workload.value} ${entry.workload.unit}`}</dd></div>
                    <div><dt className="text-gray-500">Games in the past 7 days</dt><dd className="mt-0.5 text-gray-800">{entry.games_in_7d ?? "Unavailable"}</dd></div>
                  </dl>
                  <p className="mt-2 text-xs text-gray-500">Next game: {entry.next_game ? new Date(entry.next_game).toLocaleString() : "Schedule unavailable"}</p>
                  {entry.reasons.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-gray-600">{entry.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
                  {entry.missing_data.length > 0 && (
                    <div className="mt-3 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
                      <p className="font-medium">Data limitations</p>
                      <ul className="mt-1 list-disc space-y-1 pl-4">{entry.missing_data.map((reason, index) => <li key={index}>{readable(reason)}</li>)}</ul>
                    </div>
                  )}
                  <p className="mt-2 text-xs text-gray-400">Method: {readable(entry.method)}</p>
                </article>
              ))}
            </div>
            <p className="mt-4 text-xs text-gray-400">Updated {new Date(data.generated_at).toLocaleString()}. Missing history is not a low-risk signal.</p>
          </>
        )}
      </div>
    </section>
  );
}
