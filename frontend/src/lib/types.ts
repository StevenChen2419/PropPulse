export interface Player {
  id:        string;
  name:      string;
  team:      string;
  team_abbr: string;
  position?: string;
  age?:      number;
  sport:     string;
}

export interface FatigueData {
  fatigue_score:          number;
  workload_score:         number;
  back_to_back:           boolean;
  games_in_7d:            number;
  rolling_minutes_7d:     number;
  minutes_trend:          number;
  performance_volatility: number;
  risk_flags:             string[];
  shap_reasons:           string[];
  fatigue_label:          "Low" | "Medium" | "High" | "Critical";
}

export interface SportRiskCoverage {
  sport: string;
  active_players: number;
  assessed_players: number;
  status: string;
  description: string;
}

export interface SportRiskPlayer {
  player: Pick<Player, "id" | "name" | "team_abbr" | "sport">;
  score: number | null;
  label: string;
  method: string;
  reasons: string[];
  missing_data: string[];
  games_in_7d: number | null;
  workload: { label: string; value: number | null; unit: string };
  next_game: string | null;
}

export interface SportRiskIntelligenceData {
  sports: SportRiskCoverage[];
  players: SportRiskPlayer[];
  generated_at: string;
}

export interface OfferAvailability {
  provider_observed_at?: string | null;
  ingested_at?: string | null;
  availability?: "available" | "last_known" | "expired" | "game_started" | "market_unavailable";
  actionable?: boolean;
  source?: "live" | "last_known" | "unavailable";
  refreshed_at?: string | null;
  observation_age_seconds?: number | null;
  expires_at?: string | null;
  evaluated_at?: string;
}

export interface BestLine {
  sportsbook: string;
  odds:       number;
  line:       number;
}

export interface ComparisonOffer extends OfferAvailability {
  sportsbook: string;
  line: number;
  odds: number | null;
  provider_bookmaker_key?: string | null;
  provider_title?: string | null;
}
export interface SportsbookComparison {
  prop_id: string;
  player_id: string;
  event_id: string | null;
  market: string | null;
  groups: { line: number; side: PropSide; offers: ComparisonOffer[]; best: ComparisonOffer | null; advantage_per_100: number | null }[];
}

export interface SportsbookOffer extends OfferAvailability {
  provider_bookmaker_key?: string | null;
  provider_title?: string | null;
  sportsbook: string;
  line:       number;
  over_odds:  number | null;
  under_odds: number | null;
}

export interface TrendWindow {
  games:      number;
  decisions:  number;
  hits:       number;
  pushes:     number;
  hit_rate:   number | null;
  seasons?: number[];
  season_scope?: "current_season" | "previous_seasons" | "mixed_seasons" | "empty";
}

export interface TrendGame {
  game_date: string;
  opponent?: string | null;
  is_home?:  boolean | null;
  value:     number;
  result:    "hit" | "miss" | "push";
}

export interface ExactLineTrends {
  line:          number;
  side:          "over";
  season:        number;
  l5:            TrendWindow;
  l10:           TrendWindow;
  season_window: TrendWindow;
  average:       number;
  median:        number;
  recent_games:  TrendGame[];
  recent_scope?: string;
  competition_scope?: string;
}

// Additive during the Phase 3E transition: older responses and persisted props
// may omit context. Only authoritative identities carry an Event UUID.
export interface GameIdentity {
  event_id?: string | null;
  game_key?: string | null;
  identity_source?: "authoritative" | "legacy" | "unresolved";
  sport?: string;
  home_team?: string | null;
  away_team?: string | null;
  scheduled_start_at?: string | null;
  provider?: string | null;
  provider_event_id?: string | null;
  sport_key?: string | null;
}

export interface Prop extends OfferAvailability, GameIdentity {
  statistics_coverage?: StatisticsCoverage | null;
  source?: "live" | "last_known" | "unavailable";
  refreshed_at?: string | null;
  odds_event_id?: string | null;
  id:               string;
  player:           Player;
  prop_type:        string;
  line:             number;
  line_24h_ago?:    number;
  over_odds:        number | null;
  under_odds:       number | null;
  sportsbook:       string;
  game_time?:       string;
  opponent?:        string;
  is_home:          boolean;
  popularity_count: number;
  fatigue?:         FatigueData;
  rank_score?:      number;
  reasons?:         string[];
  line_movement?:   number;
  best_over?:       BestLine | null;
  best_under?:      BestLine | null;
  sportsbook_count?: number;
  sportsbook_offers?: SportsbookOffer[];
  comparison?: SportsbookComparison | null;
  trends?:           ExactLineTrends | null;
  discover_score?:      number;
  discover_reasons?:    string[];
  discover_components?: Record<string, number>;
}

export interface FeedResponse {
  props:         Prop[];
  total:         number;
  refreshed_at?: string | null;
}

export interface DiscoverResponse extends FeedResponse {
  supported_sports: string[];
  limit?: number;
  offset?: number;
  has_more?: boolean;
  next_offset?: number | null;
  filter_options?: { sports: string[]; markets: string[]; sportsbooks: string[] };
}

export interface TodayGame extends GameIdentity {
  game_key:        string;
  sport:           string;
  away_team:       string;
  home_team:       string;
  game_time?:      string | null;
  prop_count:      number;
  has_eligible_props?: boolean;
  source:          "live" | "last_known" | "unavailable" | "cached" | "fallback";
}

export interface TodayGamesResponse {
  games:         TodayGame[];
  total:         number;
  refreshed_at?: string | null;
}

export interface GameDetail extends OfferAvailability, GameIdentity {
  source: "live" | "last_known" | "unavailable";
  game_key:         string;
  sport:            string;
  away_team:        string;
  home_team:        string;
  game_time:        string;
  total_props:      number;
  has_eligible_props?: boolean;
  sportsbook_count: number;
  props:             Prop[];
  refreshed_at?:    string | null;
}

export interface UserPreferences {
  fav_sports:     string[];
  fav_players:    string[];
  fav_prop_types: string[];
}

export interface User {
  id:             string;
  email:          string;
  username?:      string;
  fav_sports:     string[];
  fav_players:    string[];
  fav_prop_types: string[];
}

export type PropSide = "over" | "under";

export interface SelectedOffer extends OfferAvailability {
  sportsbook: string;
  line: number;
  odds: number | null;
  original_odds?: number | null;
  original_observed_at?: string | null;
  price_change?: "improved" | "worsened" | "unchanged" | null;
}

export interface SavedSelection {
  id: string;
  prop_id: string;
  side: PropSide;
  saved_at?: string;
  selection: SelectedOffer;
  prop: Prop;
}

export interface ParlayEstimate {
  decimal: number | null;
  american: number | null;
  independent_decimal: number | null;
  method: string;
  historical_pairs: number;
  assumed_pairs: number;
  min_shared_games: number | null;
  warnings: string[];
  reason: string | null;
}

export interface ParlayEstimateRequest {
  items: { prop_id: string; side: PropSide; sportsbook: string; line: number }[];
  assumed_correlation: number;
}

export type SlipSelection = Prop & { side: PropSide; selection?: SelectedOffer };

export interface SlipItem {
  id:      string;
  prop_id: string;
  side:    PropSide;
  prop?:   Prop;
  selection?: SelectedOffer;
}

export interface Slip {
  id:     string;
  status: string;
  items:  SlipItem[];
}

export interface PlayerProp extends OfferAvailability, GameIdentity {
  game_time?: string;
  id:         string;
  prop_type:  string;
  line:       number;
  over_odds:  number | null;
  under_odds: number | null;
  opponent?:  string;
}

export interface PlayerDetail extends Player {
  fatigue?: FatigueData;
  props:    PlayerProp[];
}

export interface PlayerSearchTopProp {
  prop_type:      string;
  line:           number;
  best_over:      BestLine | null;
  line_movement:  number | null;
  l5_hit_rate:    number | null;
  l10_hit_rate:   number | null;
}

export interface PlayerSearchResult extends OfferAvailability {
  statistics_coverage?: StatisticsCoverage | null;
  id:               string;
  name:             string;
  team:             string;
  team_abbr:        string;
  position?:        string | null;
  sport:            string;
  live_prop_count:  number;
  next_game_time:   string | null;
  top_prop:         PlayerSearchTopProp | null;
}

export interface PlayerSearchResponse {
  players: PlayerSearchResult[];
}

export type InteractionAction =
  | "like"
  | "dislike"
  | "save"
  | "add_to_slip"
  | "click"
  | "view";

// Insights types (Day 6)

export interface InsightProp {
  id:        string;
  prop_type: string;
  line:      number;
  over_odds: number;
}

export interface FatigueEdge {
  player: {
    id:        string;
    name:      string;
    team_abbr: string;
  };
  fatigue_score: number;
  fatigue_label: string;
  back_to_back:  boolean;
  top_flag:      string;
  prop:          InsightProp;
}

export interface LineMover {
  player_id:    string;
  player_name:  string;
  team_abbr:    string;
  prop_type:    string;
  line:         number;
  line_24h_ago: number;
  movement:     number;
  direction:    "up" | "down";
}

export interface B2BPlayer {
  player: {
    id:        string;
    name:      string;
    team_abbr: string;
  };
  fatigue_score: number;
  games_in_7d:   number;
}

export interface TrendingProp {
  player_id:        string;
  player_name:      string;
  team_abbr:        string;
  prop_type:        string;
  line:             number;
  popularity_count: number;
}

export interface InsightsData {
  fatigue_edges:        FatigueEdge[];
  line_movers:          LineMover[];
  back_to_back_tonight: B2BPlayer[];
  trending:             TrendingProp[];
}

// Game log types (Day 11)

export interface GameLogEntry {
  game_date:           string;
  game_number:         number;
  actual_points:       number | null;
  prop_line_points?:   number | null;
  actual_minutes:      number | null;
  back_to_back:        boolean;
  games_in_7d:         number;
  underperformed_line: boolean;
}

export interface PlayerGameLog {
  player_name: string;
  games:       GameLogEntry[];
  note?:       string | null;
}

// ── ML Model Status (Day 14) ──────────────────────────────────────────────────

export interface ModelCalibration {
  rested_score: number;
  b2b_score:    number;
  thresholds: {
    critical: number;
    high:     number;
    medium:   number;
  };
}

export interface ModelStatus {
  model_exists:   boolean;
  trained_at:     string | null;
  auc:            number | null;
  accuracy:       number | null;
  log_loss:       number | null;
  feature_count:  number | null;
  feature_cols:   string[];
  n_train:        number | null;
  n_test:         number | null;
  data_source:    string;
  artifact_path:  string;
  meta_available: boolean;
  calibration?:   ModelCalibration;
}

export interface PlayerResearchProp extends OfferAvailability, GameIdentity {
  id:                string;
  prop_type:         string;
  line:              number;
  over_odds:         number | null;
  under_odds:        number | null;
  sportsbook:        string;
  game_time?:        string | null;
  opponent?:         string | null;
  is_home:           boolean;
  best_over?:        BestLine | null;
  best_under?:       BestLine | null;
  sportsbook_count: number;
  sportsbook_offers?: SportsbookOffer[];
  comparison?: SportsbookComparison | null;
}

export interface PropLineMovement {
  sportsbook:         string;
  opening_line:       number;
  current_line:       number;
  line_change:        number;
  opening_over_odds:  number | null;
  opening_under_odds: number | null;
  current_over_odds:  number | null;
  current_under_odds: number | null;
  opened_at:          string;
  updated_at:         string;
  snapshot_count:     number;
}

export interface ResearchSplit extends TrendWindow {
  name?: string | null;
}

export interface ResearchHistory {
  status: "available" | "no_history" | "no_valid_market_statistics" | "excluded_history";
  stored_games: number;
  valid_market_games: number;
  eligible_games: number;
  current_season_games: number;
  previous_season_games: number;
  selected_season: number;
  excluded_counts: Record<string, number>;
  insufficient_l5: boolean;
  insufficient_l10: boolean;
  competition_scope: string;
  completion_scope?: string;
}

export interface SeasonStatistic {
  average: number | null;
  valid_samples: number;
}

export interface SeasonStatisticsWindow {
  appearances: number;
  points: SeasonStatistic;
  rebounds: SeasonStatistic;
  assists: SeasonStatistic;
  threes?: SeasonStatistic;
  minutes: SeasonStatistic;
}

export interface SportStatisticsWindow {
  appearances: number;
  [metric: string]: number | SeasonStatistic;
}

export interface StatisticsCoverage {
  state: 'current_season' | 'partial_current_season' | 'historical_season' | 'no_recorded_games' | 'source_unavailable';
  completeness: 'unknown';
  season_scope: 'current' | 'historical' | 'future';
  season: string;
  competition: string;
  source: string | null;
  last_game_date: string | null;
  source_observed_at: string | null;
  recorded_appearances: number;
  l5_samples: number;
  l10_samples: number;
  recorded_weeks?: number[];
  limitations: string[];
}

export interface PlayerSeasonSummary {
  coverage?: StatisticsCoverage;
  sport?: string;
  metrics?: { key: string; label: string }[];
  opponent_history?: { opponent_id: string; l5: SportStatisticsWindow; l10: SportStatisticsWindow }[];
  status: "available" | "unavailable";
  season: string;
  competition: string;
  source: string | null;
  coverage_start: string | null;
  coverage_end: string | null;
  last_observed_at: string | null;
  recorded_appearances: number;
  latest_appearance: string | null;
  date_precision: "eastern_date" | null;
  reference_date: string;
  calendar_day_gap: number | null;
  full_intervening_days: number | null;
  l5: SeasonStatisticsWindow | SportStatisticsWindow;
  l10: SeasonStatisticsWindow | SportStatisticsWindow;
  notes: string[];
}

export interface PlayerResearch {
  exact_line?: ExactLineResearch | null;
  player_id:       string;
  sport:           string;
  selection_source?: "default" | "legacy" | "prop_id";
  selection_available?: boolean;
  available_props: PlayerResearchProp[];
  selected_prop:   PlayerResearchProp | null;
  line_movement:   PropLineMovement | null;
  trends:          ExactLineTrends | null;
  splits: {
    home:     ResearchSplit;
    away:     ResearchSplit;
    opponent: ResearchSplit;
  } | null;
  games:   TrendGame[];
  message?: string | null;
  history?: ResearchHistory | null;
  rest_workload?: RestWorkloadResearch | null;
  season_summary?: PlayerSeasonSummary | null;
  matchup_context?: MatchupContext | null;
}

export interface ExactResearchWindow {
  appearances: number; valid_samples: number; missing_samples: number;
  over_hits: number; under_hits: number; pushes: number; hits: number; losses: number;
  raw_hit_rate: number | null; settled_decisions: number; settled_hit_rate: number | null;
}
export interface ExactResearchGame {
  game_id: string; game_date: string; value: number | null;
  outcome: 'over' | 'under' | 'push' | 'missing'; opponent_id: string | null;
  source: string; source_observed_at: string | null;
}
export interface ExactLineResearch {
  comparison?: SportsbookComparison | null;
  movement?: { status: "unavailable"; reason: string };
  status: 'available' | 'unsupported_market' | 'unsupported_role' | 'missing_metric' | 'no_recorded_games';
  player_id: string; sport: string; market: string; metrics: string[]; line: number;
  side: PropSide; season: string; competition: string; source: string | null;
  coverage: StatisticsCoverage | null; reference_at: string; last_game_date: string | null;
  source_observed_at: string | null; games: ExactResearchGame[];
  l5: ExactResearchWindow; l10: ExactResearchWindow; season_window: ExactResearchWindow;
  current_opponent_id: string | null; limitations: string[];
  selection: OfferAvailability & { sportsbook: string; line: number; side: PropSide; odds: number | null };
  offer_options: { sportsbook: string; line: number }[];
  opponents: { opponent_id: string; source: string; games: ExactResearchGame[];
    l5: ExactResearchWindow; l10: ExactResearchWindow; season_window: ExactResearchWindow }[];
}

export interface MatchupWindow extends SeasonStatisticsWindow {
  coverage_start: string | null;
  coverage_end: string | null;
}

export interface MatchupContext {
  status: "available" | "unavailable";
  reason: string | null;
  team_context: {
    team_id: string; team_name: string; opponent_id: string; opponent_name: string;
    event_id: string; prop_id: string; reference_date: string;
    last_recorded_game: { game_id: string; date: string; source: string; observed_at: string; date_precision: string } | null;
    calendar_day_gap: number | null;
    full_intervening_days: number | null;
    conditional_back_to_back: "yes" | "unknown";
    notes: string[];
  } | null;
  opponent_history: {
    status: "available" | "unavailable";
    opponent_id: string; opponent_name: string; season: string; competition: string;
    source: string | null; recorded_appearances: number;
    coverage_start: string | null; coverage_end: string | null;
    overall: MatchupWindow; l5: MatchupWindow; l10: MatchupWindow; notes: string[];
  } | null;
}

export type OddsIngestionSource =
  | "mock"
  | "odds_api_matchups"
  | "odds_api_props"
  | "cached_live"
  | "mixed"
  | "unknown";

export interface SportIngestionStatus {
  sport: string;
  current_prop_count?: number;
  availability: "live" | "last_known" | "unavailable" | "no_games";
  events_found: number;
  live_props_matched: number;
  cached_live_props: number;
  cache_age_minutes?: number | null;
  provider_http_status?: number | null;
  provider_error_code?: string | null;
  provider_error_message?: string | null;
  quota_requests_remaining?: string | number | null;
  warnings: string[];
  errors: string[];
}

export interface OddsIngestionStatus {
  current_offer_status?: OfferAvailability & { game_time?: string | null };
  current_prop_count?: number;
  source:                  OddsIngestionSource;
  fallback_used:           boolean;
  refreshed_at?:           string | null;
  api_key_loaded?:         boolean;
  basketball_nba_active?:  boolean;
  basketball_wnba_active?: boolean;
  events_found?:           number;
  markets_requested?:      string[];
  market_requests_made?:   number;
  live_props_matched?:     number;
  cached_live_props?:      number;
  cached_at?:              string | null;
  cache_age_minutes?:      number | null;
  cache_expires_at?:       string | null;
  cache_ttl_minutes?:      number;
  availability?:           "live" | "last_known" | "unavailable" | "no_games";
  quota_requests_used?:    string | number | null;
  quota_requests_remaining?: string | number | null;
  props_updated_live?:     number;
  props_updated_mock?:     number;
  warnings?:               string[];
  errors?:                 string[];
  live_games_found:        number;
  live_props_updated:      number;
  mock_props_updated:      number;
  total_props_updated:     number;
  last_updated:            string | null;
  message:                 string;
  matchups:                string[];
  line_moved_up?:          number | null;
  line_moved_down?:        number | null;
  line_unchanged?:         number | null;
  stale_props_inactivated?: number | null;
  sports?:                  Record<string, SportIngestionStatus>;
  status_available:        boolean;
}
export interface WorkloadWindow {
  games: number;
  observed_games: number;
  average_minutes: number | null;
  date_start: string | null;
  date_end: string | null;
  seasons: number[];
  insufficient_sample: boolean;
}

export interface VerifiedRestGame {
  status: "confirmed" | "partial";
  provider?: "espn" | "nba_com";
  sport?: "NBA";
  source?: string;
  observed_at?: string;
  participation_source?: string | null;
  participation_observed_at?: string | null;
  game_id: string;
  team_id: string;
  game_at: string;
  time_precision?: "instant" | "eastern_date";
  completed_at: string | null;
  gap_days: number;
  full_rest_days: number;
}

export interface VerifiedRestContext {
  status: "confirmed" | "partial" | "unknown";
  reference_at: string;
  provenance: string[];
  context_team_id: string | null;
  evidence_counts: { games: number; participation: number; membership: number; coverage: number; excluded_conflicts: number; excluded_invalid: number };
  last_confirmed_appearance: VerifiedRestGame | null;
  last_completed_team_game: VerifiedRestGame | null;
  team_back_to_back: boolean | null;
  confirmed_missed_games: number | null;
  partial_missed_games_lower_bound: number | null;
  dnp_games: number;
  inactive_games: number;
  unknown_participation_games: number;
  uncovered_games: number;
  schedule_complete: boolean;
  notes: string[];
}

export interface RestWorkloadResearch {
  status: "available" | "no_history" | "unsupported_sport";
  player_id: string;
  sport: string;
  classification: "observed_and_derived";
  verified?: VerifiedRestContext | null;
  evaluated_at: string;
  reference: { at: string; source: "event" | "as_of"; event_id: string | null; prop_id: string | null };
  coverage: {
    stored_games: number; eligible_games: number; excluded_counts: Record<string, number>;
    date_start: string | null; date_end: string | null; sources: string[];
    schedule_complete: boolean; notes: string[];
  };
  rest: {
    days_since_last_game: number | null; back_to_back: boolean | null;
    category: "back_to_back" | "short_rest" | "extended_rest" | null;
    games_in_7d: number | null; games_in_14d: number | null; schedule_density: number | null;
    classification: "derived"; explanation: string;
  };
  workload: {
    l5: WorkloadWindow; l10: WorkloadWindow; season: WorkloadWindow;
    l5_vs_season: number | null; minutes_trend: number | null; variability: number | null;
    missing_minutes: number; explanation: string;
  };
  rest_splits: {
    category: string; games: number; minutes_games: number; average_minutes: number | null;
    points_games: number; average_points: number | null; date_start: string | null; date_end: string | null;
  }[];
  interpretation: { classification: "heuristic"; label: string; explanation: string; experimental_model_used: false };
}
