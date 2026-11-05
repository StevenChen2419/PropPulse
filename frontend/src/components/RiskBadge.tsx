import type { FatigueData } from "@/lib/types";

type RiskLabel = "Low" | "Medium" | "High" | "Critical";

const STYLES: Record<RiskLabel, { wrapper: string; dot: string }> = {
  Low: {
    wrapper: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    dot: "bg-emerald-500",
  },
  Medium: {
    wrapper: "bg-amber-50 text-amber-700 border border-amber-200",
    dot: "bg-amber-500",
  },
  High: {
    wrapper: "bg-orange-50 text-orange-700 border border-orange-200",
    dot: "bg-orange-500",
  },
  Critical: {
    wrapper: "bg-red-50 text-red-700 border border-red-200",
    dot: "bg-red-500",
  },
};

interface Props {
  fatigue?: FatigueData;
}

export function RiskBadge({ fatigue }: Props) {
  if (!fatigue) return null;

  const label = fatigue.fatigue_label as RiskLabel;
  const style = STYLES[label];

  if (!style) return null;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${style.wrapper}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${style.dot}`} />
      {label} Risk
    </span>
  );
}