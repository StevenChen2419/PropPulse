"use client";
import { useOfferClock } from "@/lib/useOfferClock";
import { availabilityLabel } from "@/lib/propSides";
import { useLiveRefresh } from "@/lib/useLiveRefresh";

import { useEffect, useMemo, useState, useRef } from "react";
import { gameQuery, decodeGameSegment, formatGameContext, errorMessage } from "@/lib/gameNavigation";
import { createRequestGate } from "@/lib/requestGate";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertCircle, ArrowLeft } from "lucide-react";

import { PropCard } from "@/components/PropCard";
import { api } from "@/lib/api";
import type { GameDetail, Player, Prop } from "@/lib/types";

interface PlayerGroup {
  player: Player;
  props: Prop[];
}

export default function GameDetailPage() {
  useOfferClock();
  const params = useParams<{ gameKey: string | string[] }>();
  const rawGameKey = Array.isArray(params.gameKey) ? params.gameKey[0] : params.gameKey;
  const gameKey = decodeGameSegment(rawGameKey || "");

  const [game, setGame] = useState<GameDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestGate = useRef(createRequestGate());

  const [revision, setRevision] = useState(0);
  useLiveRefresh(() => setRevision((value) => value + 1), loading);

  useEffect(() => {
    const request = requestGate.current.start();
    setLoading(true);
    setError(null);
    setGame(null);

    Promise.resolve().then(() => api.getGame(gameQuery(gameKey), request.signal))
      .then((data) => {
        if (request.isCurrent()) setGame(data);
      })
      .catch((err: unknown) => {
        if (!request.isCurrent()) return;
        setError(errorMessage(err, "game"));
      })
      .finally(() => {
        if (request.isCurrent()) setLoading(false);
      });

    return () => requestGate.current.cancel();
  }, [gameKey, revision]);

  const playerGroups = useMemo<PlayerGroup[]>(() => {
    if (!game) return [];
    const grouped = new Map<string, PlayerGroup>();
    for (const prop of game.props) {
      const group = grouped.get(prop.player.id);
      if (group) {
        group.props.push(prop);
      } else {
        grouped.set(prop.player.id, { player: prop.player, props: [prop] });
      }
    }

    return Array.from(grouped.values())
      .map((group) => ({
        ...group,
        props: group.props.sort((a, b) =>
          a.prop_type.localeCompare(b.prop_type) || a.line - b.line
        ),
      }))
      .sort((a, b) => a.player.name.localeCompare(b.player.name));
  }, [game]);

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace">
        <Link
          href="/"
          className="mb-5 inline-flex items-center gap-1.5 text-sm text-gray-500 transition-colors hover:text-gray-900"
        >
          <ArrowLeft size={15} />
          Today&apos;s Board
        </Link>

        {loading && (
          <div className="space-y-3">
            <p role="status" className="text-sm text-muted">Loading game and stored offers…</p>
            <div className="h-24 animate-pulse rounded-lg bg-gray-100" />
            {[...Array(4)].map((_, index) => (
              <div key={index} className="h-52 animate-pulse rounded-2xl bg-white" />
            ))}
          </div>
        )}

        {!loading && error && (
          <div role="alert" className="border border-red-100 bg-red-50 p-5 text-center">
            <AlertCircle size={20} className="mx-auto mb-2 text-red-400" />
            <p className="text-sm font-medium text-red-700">Could not load game</p>
            <p className="mt-1 text-xs text-red-500">{error}</p>
            <button type="button" onClick={() => setRevision((value) => value + 1)} className="mt-3 text-sm font-medium text-blue-600 hover:text-blue-800">Retry game</button>
          </div>
        )}

        {!loading && !error && game && (
          <>
            <header className="mb-6 border-b border-gray-200 pb-5">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-500">{game.sport}</span>
                <span className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600">
                  {availabilityLabel(game, game.game_time)}
                </span>
              </div>
              <h1 className="page-title">
                {game.away_team} @ {game.home_team}
              </h1>
              <p className="mt-1 text-sm text-gray-500">{formatGameContext(game)}{game.identity_source !== "authoritative" ? " · Legacy / unverified" : ""}</p>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
                <span>{game.total_props} props</span>
                <span>{game.sportsbook_count} sportsbooks with eligible offers</span>
                <span>{playerGroups.length} players</span>
              </div>
            </header>

            {game.props.length === 0 && (
              <div className="mb-6 rounded-xl border border-amber-100 bg-amber-50 px-4 py-4 text-sm text-amber-800">
                Odds unavailable for this game. Game details remain available; check back for eligible offers.
              </div>
            )}

            <div className="space-y-7">
              {playerGroups.map((group) => (
                <section key={group.player.id}>
                  <div className="mb-2 flex items-end justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold text-gray-900">
                        {group.player.name}
                      </h2>
                      <p className="text-xs text-gray-400">
                        {group.player.team_abbr}
                        {group.player.position ? ` / ${group.player.position}` : ""}
                      </p>
                    </div>
                    <span className="text-xs text-gray-400">
                      {group.props.length} {group.props.length === 1 ? "prop" : "props"}
                    </span>
                  </div>
                  <div className="prop-grid">
                    {group.props.map((prop) => (
                      <PropCard key={prop.id} prop={prop} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
