"use client";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import type { GameLogEntry } from "@/lib/types";

interface Props { games: GameLogEntry[]; note?: string | null }

export function PlayerStatsChart({ games, note }: Props) {
  const data = games
    .filter((game) => typeof game.actual_points === "number" && Number.isFinite(game.actual_points))
    .map((game) => ({
      date: game.game_date.slice(0, 10),
      points: game.actual_points,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));

  if (!data.length) return (
    <div className="py-8 text-center">
      <p className="mb-1 text-sm font-medium text-gray-500">No observed points history available</p>
      <p className="text-xs text-gray-400">{note || "Player history will appear when the data provider supplies results."}</p>
    </div>
  );

  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-gray-700">Last {data.length} games with points data</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#223145" vertical={false} />
          <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
          <Tooltip cursor={{ fill: "rgba(94,224,189,0.06)" }} />
          <Bar name="Points" dataKey="points" fill="#5ee0bd" radius={[3, 3, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-2 text-xs text-gray-400">Observed points. Historical sportsbook lines are not available for this chart.</p>
      {note && <p className="mt-1 text-xs text-gray-400">{note}</p>}
    </div>
  );
}
