"use client";

const SPORTS: string[] = ["All", "NBA", "WNBA", "MLB", "NFL", "NHL"];

const PROP_TYPES_BY_SPORT: Record<string, { label: string; value: string }[]> = {
  NBA: [
    { label: "Points", value: "points" },
    { label: "Rebounds", value: "rebounds" },
    { label: "Assists", value: "assists" },
    { label: "Threes", value: "threes" },
    { label: "Blocks", value: "blocks" },
    { label: "Steals", value: "steals" },
    { label: "PRA", value: "pra" },
  ],
  WNBA: [
    { label: "Points", value: "points" },
    { label: "Rebounds", value: "rebounds" },
    { label: "Assists", value: "assists" },
    { label: "Threes", value: "threes" },
    { label: "Blocks", value: "blocks" },
    { label: "Steals", value: "steals" },
    { label: "PRA", value: "pra" },
  ],
  MLB: [
    { label: "Hits", value: "hits" },
    { label: "Runs", value: "runs" },
    { label: "RBIs", value: "rbis" },
    { label: "Total bases", value: "total_bases" },
    { label: "Strikeouts", value: "strikeouts" },
    { label: "Home runs", value: "home_runs" },
  ],
  NFL: [
    { label: "Passing yards", value: "pass_yds" },
    { label: "Rushing yards", value: "rush_yds" },
    { label: "Receiving yards", value: "reception_yds" },
    { label: "Receptions", value: "receptions" },
    { label: "Touchdowns", value: "anytime_td" },
  ],
  NHL: [
    { label: "Shots on goal", value: "shots_on_goal" },
    { label: "Points", value: "points" },
    { label: "Assists", value: "assists" },
    { label: "Saves", value: "saves" },
  ],
};

const ALL_PROP_TYPES = Object.values(PROP_TYPES_BY_SPORT)
  .flat()
  .filter(
    (option, index, all) =>
      all.findIndex((item) => item.value === option.value) === index
  );

interface Props {
  sport:      string;
  propType:   string;
  onSport:    (v: string) => void;
  onPropType: (v: string) => void;
  sports?:    string[];
  markets?: { label: string; value: string }[];
}

export function FeedFilters({ sport, propType, onSport, onPropType, sports, markets }: Props) {
  // Empty string means "no filter applied", which maps to the "All" button.
  const activeSport    = sport    === "" ? "All" : sport;
  const visibleSports = sports ? ["All", ...sports] : SPORTS;
  const visibleAllPropTypes = sports
    ? sports
        .flatMap((item) => PROP_TYPES_BY_SPORT[item] ?? [])
        .filter(
          (option, index, all) =>
            all.findIndex((item) => item.value === option.value) === index
        )
    : ALL_PROP_TYPES;
  const propTypes = markets ?? (sport ? PROP_TYPES_BY_SPORT[sport] ?? [] : visibleAllPropTypes);

  return (
    <div className="space-y-4">
      <p className="eyebrow">Refine your board</p>
      {/* Sport pills */}
      <div className="flex gap-1.5 flex-wrap">
        {visibleSports.map((s) => (
          <button
            key={s}
            aria-pressed={activeSport === s}
            onClick={() => onSport(s === "All" ? "" : s)}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              activeSport === s
                ? "bg-blue-600 text-[#ffffff]"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      <label className="block text-xs font-medium text-muted">Market
        <select aria-label="Prop market filter" value={propType} onChange={event => onPropType(event.target.value)} className="mt-2 block w-full rounded-xl border border-gray-200 bg-canvas px-3 py-2 text-sm sm:max-w-sm">
          <option value="">All markets</option>
          {propTypes.map(pt => <option key={pt.value} value={pt.value}>{pt.label}</option>)}
        </select>
      </label>
    </div>
  );
}
