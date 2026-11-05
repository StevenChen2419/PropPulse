import type { FatigueData } from "@/lib/types";

interface Props {
  fatigue?: FatigueData;
}

export function FatigueBar({ fatigue }: Props) {
  if (!fatigue) return null;

  const pct = Math.round(fatigue.fatigue_score * 100);

  const barColor =
    pct < 35 ? "bg-emerald-500" :
    pct < 55 ? "bg-amber-500"   :
    pct < 75 ? "bg-orange-500"  :
               "bg-red-500";

  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-gray-400">Fatigue index</span>
        <span className="text-xs font-medium text-gray-500">{pct}%</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}