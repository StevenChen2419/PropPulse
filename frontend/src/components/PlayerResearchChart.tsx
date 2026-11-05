"use client";

import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ResearchHistory, TrendGame, ExactLineResearch } from "@/lib/types";
import { historyMessage } from "./ResearchHistorySummary";

interface Props {
  games:    TrendGame[];
  line:     number;
  propType: string;
  history?: ResearchHistory | null;
  exact?: ExactLineResearch;
}

interface ChartRow {
  label:    string;
  date:     string;
  opponent: string;
  value:    number | null;
  line:     number;
  result:   "hit" | "miss" | "push" | 'over' | 'under' | 'missing';
}

const RESULT_COLORS = {
  hit: "#10b981",
  miss: "#ef4444",
  push: "#f59e0b",
  over: '#10b981', under: '#818cf8', missing: '#9ca3af',
};

function formatPropType(value: string): string {
  const labels: Record<string, string> = {
    rbis: "RBIs",
    total_bases: "Total bases",
    home_runs: "Home runs",
    pra: "PRA",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}

function ResearchTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as ChartRow | undefined;
  if (!row) return null;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-gray-700">{row.date} vs {row.opponent}</p>
      <p className="mt-1 text-gray-500">
        Result <span className="font-semibold text-gray-800">{row.value ?? 'Unavailable'}</span>
        <span className="ml-1 text-gray-400">at {row.line}</span>
      </p>
      <p className="mt-0.5 capitalize" style={{ color: RESULT_COLORS[row.result] }}>
        {row.result}
      </p>
    </div>
  );
}

export function PlayerResearchChart({ games, line, propType, history, exact }: Props) {
  if ((exact?.games ?? games).length === 0) {
    return (
      <div className="py-10 text-center text-sm text-gray-400">
        {historyMessage(history)}
      </div>
    );
  }

  const data: ChartRow[] = exact ? [...exact.games].reverse().map(game => ({
    label: game.game_date.slice(5).replace('-', '/'), date: game.game_date,
    opponent: game.opponent_id ? `Source opponent ${game.opponent_id}` : 'Opponent linkage unavailable',
    value: game.value, line, result: game.outcome,
  })) : [...games].reverse().map((game) => ({
    label: game.game_date.slice(5).replace("-", "/"),
    date: game.game_date,
    opponent: game.opponent || "Opponent",
    value: game.value,
    line,
    result: game.result,
  }));

  return (
    <figure className="min-w-0" aria-label={`${formatPropType(propType)} recorded results at line ${line}`}>
      <figcaption className="sr-only">{data.length} recorded appearances at line {line}. Missing values appear as gaps. {exact ? 'Read the recorded games table below for dates, values and Over, Under or Push outcomes.' : data.map(row => `${row.date}: ${row.value ?? 'Unavailable'}, ${row.result}`).join('; ')}</figcaption>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold capitalize text-gray-700">
          Last {data.length} {formatPropType(propType)} results
        </h3>
        <span className="text-xs text-gray-400">Line {line}</span>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#223145" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={44} />
          <Tooltip content={<ResearchTooltip />} cursor={{ fill: "rgba(94,224,189,0.06)" }} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={30}>
            {data.map((row) => (
              <Cell key={`${row.date}-${row.opponent}`} fill={RESULT_COLORS[row.result]} fillOpacity={0.85} />
            ))}
          </Bar>
          {exact ? <ReferenceLine y={line} stroke="#9ca3af" strokeDasharray="5 3" ifOverflow="extendDomain" />
            : <Line type="monotone" dataKey="line" stroke="#6b7280" strokeWidth={1.5} strokeDasharray="5 3" dot={false} activeDot={false} />}
        </ComposedChart>
      </ResponsiveContainer>
      <div role="group" aria-label="Historical result legend" className="mt-2 flex flex-wrap items-center gap-4 text-xs text-gray-400">
        {(exact ? ['over', 'under', 'push', 'missing'] as const : ["hit", "miss", "push"] as const).map((result) => (
          <span key={result} className="flex items-center gap-1.5 capitalize">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: RESULT_COLORS[result] }} />
            {result}
          </span>
        ))}
        <span className="ml-auto">Dashed line: {line}</span>
      </div>
    </figure>
  );
}
