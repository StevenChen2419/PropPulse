from pydantic import BaseModel, EmailStr, Field, model_validator, field_validator
from uuid import UUID
from typing import Annotated, Optional, List, Literal
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(max_length=72)
    username: Optional[str] = Field(default=None, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if len(value) < 8 or len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at least 8 characters and at most 72 UTF-8 bytes")
        return value

class UserLogin(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value

class UserPreferences(BaseModel):
    fav_sports: Optional[List[Annotated[str, Field(max_length=80)]]] = Field(default=None, max_length=100)
    fav_players: Optional[List[Annotated[str, Field(max_length=80)]]] = Field(default=None, max_length=100)
    fav_prop_types: Optional[List[Annotated[str, Field(max_length=80)]]] = Field(default=None, max_length=100)

class AuthResponse(BaseModel):
    ok: Literal[True] = True

class PlayerOut(BaseModel):
    id: str
    name: str
    team: str
    team_abbr: str
    position: Optional[str]
    age: Optional[int]
    sport: str

    class Config:
        from_attributes = True


class WorkloadWindowOut(BaseModel):
    games: int
    observed_games: int
    average_minutes: Optional[float]
    date_start: Optional[str]
    date_end: Optional[str]
    seasons: List[int]
    insufficient_sample: bool


class RestReferenceOut(BaseModel):
    at: str
    source: Literal["event", "as_of"]
    event_id: Optional[str]
    prop_id: Optional[str]


class RestCoverageOut(BaseModel):
    stored_games: int
    eligible_games: int
    excluded_counts: dict[str, int]
    date_start: Optional[str]
    date_end: Optional[str]
    sources: List[str]
    schedule_complete: Literal[False]
    notes: List[str]


class RestIndicatorsOut(BaseModel):
    days_since_last_game: Optional[int]
    back_to_back: Optional[bool]
    category: Optional[Literal["back_to_back", "short_rest", "extended_rest"]]
    games_in_7d: Optional[int]
    games_in_14d: Optional[int]
    schedule_density: Optional[float]
    classification: Literal["derived"]
    explanation: str


class WorkloadIndicatorsOut(BaseModel):
    l5: WorkloadWindowOut
    l10: WorkloadWindowOut
    season: WorkloadWindowOut
    l5_vs_season: Optional[float]
    minutes_trend: Optional[float]
    variability: Optional[float]
    missing_minutes: int
    explanation: str


class RestSplitOut(BaseModel):
    category: str
    games: int
    minutes_games: int
    average_minutes: Optional[float]
    points_games: int
    average_points: Optional[float]
    date_start: Optional[str]
    date_end: Optional[str]


class RestInterpretationOut(BaseModel):
    classification: Literal["heuristic"]
    label: str
    explanation: str
    experimental_model_used: Literal[False]


class VerifiedRestGameOut(BaseModel):
    game_id: str
    team_id: str
    game_at: str
    completed_at: Optional[str]
    gap_days: int
    full_rest_days: int
    status: Literal["confirmed", "partial"]
    provider: Literal["espn", "nba_com"]
    time_precision: Literal["instant", "eastern_date"] = "instant"
    sport: Literal["NBA"]
    source: str
    observed_at: str
    participation_source: Optional[str]
    participation_observed_at: Optional[str]


class VerifiedRestOut(BaseModel):
    status: Literal["confirmed", "partial", "unknown"]
    reference_at: str
    context_team_id: Optional[str]
    provenance: List[str]
    last_confirmed_appearance: Optional[VerifiedRestGameOut]
    last_completed_team_game: Optional[VerifiedRestGameOut]
    team_back_to_back: Optional[bool]
    confirmed_missed_games: Optional[int]
    partial_missed_games_lower_bound: Optional[int]
    dnp_games: int
    inactive_games: int
    unknown_participation_games: int
    uncovered_games: int
    schedule_complete: bool
    evidence_counts: dict[str, int]
    notes: List[str]


class RestWorkloadOut(BaseModel):
    status: Literal["available", "no_history", "unsupported_sport"]
    player_id: str
    sport: str
    classification: Literal["observed_and_derived"]
    evaluated_at: str
    reference: RestReferenceOut
    coverage: RestCoverageOut
    rest: RestIndicatorsOut
    workload: WorkloadIndicatorsOut
    rest_splits: List[RestSplitOut]
    interpretation: RestInterpretationOut
    verified: VerifiedRestOut

class FatigueOut(BaseModel):
    fatigue_score: float
    workload_score: float
    back_to_back: bool
    games_in_7d: int
    rolling_minutes_7d: float
    minutes_trend: float
    performance_volatility: float
    risk_flags: List[str]
    shap_reasons: List[str]
    fatigue_label: str   # "Low" | "Medium" | "High" | "Critical"


class OfferAvailabilityOut(BaseModel):
    provider_observed_at: Optional[str] = None
    ingested_at: Optional[str] = None
    availability: Literal["available", "last_known", "expired", "game_started", "market_unavailable"]
    actionable: bool
    source: Literal["live", "last_known", "unavailable"]
    refreshed_at: Optional[str] = None
    observation_age_seconds: Optional[float] = None
    expires_at: Optional[str] = None
    evaluated_at: Optional[str] = None


class BestLineOut(BaseModel):
    sportsbook: str
    odds: int
    line: float


class SportsbookOfferOut(OfferAvailabilityOut):
    provider_bookmaker_key: Optional[str] = None
    provider_title: Optional[str] = None
    sportsbook: str
    line: float
    over_odds: Optional[int] = None
    under_odds: Optional[int] = None


class ComparisonOfferOut(OfferAvailabilityOut):
    sportsbook: str
    line: float
    odds: Optional[int] = None
    provider_bookmaker_key: Optional[str] = None
    provider_title: Optional[str] = None


class ComparisonGroupOut(BaseModel):
    line: float
    side: Literal['over', 'under']
    offers: List[ComparisonOfferOut]
    best: Optional[ComparisonOfferOut] = None
    advantage_per_100: Optional[float] = None


class SportsbookComparisonOut(BaseModel):
    prop_id: str
    player_id: str
    event_id: Optional[str] = None
    market: Optional[str] = None
    groups: List[ComparisonGroupOut]


class TrendWindowOut(BaseModel):
    games: int
    decisions: int
    hits: int
    pushes: int
    hit_rate: Optional[float] = None
    seasons: List[int] = Field(default_factory=list)
    season_scope: Optional[str] = None


class TrendGameOut(BaseModel):
    game_date: str
    opponent: Optional[str] = None
    is_home: Optional[bool] = None
    value: float
    result: str
    season: Optional[int] = None


class ExactLineTrendsOut(BaseModel):
    line: float
    side: str
    season: int
    l5: TrendWindowOut
    l10: TrendWindowOut
    season_window: TrendWindowOut
    average: float
    median: float
    recent_games: List[TrendGameOut] = Field(default_factory=list)
    recent_scope: Optional[str] = None
    competition_scope: Optional[str] = None


class GameIdentityOut(BaseModel):
    event_id: Optional[UUID] = None
    game_key: Optional[str] = None
    identity_source: Literal["authoritative", "legacy", "unresolved"] = "unresolved"
    sport: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    scheduled_start_at: Optional[datetime] = None
    provider: Optional[str] = None
    provider_event_id: Optional[str] = None
    sport_key: Optional[str] = None


class GameOut(GameIdentityOut):
    game_time: Optional[datetime] = None
    has_eligible_props: bool
    prop_count: int


class StatisticsCoverageOut(BaseModel):
    state: Literal['current_season', 'partial_current_season', 'historical_season', 'no_recorded_games', 'source_unavailable']
    completeness: Literal['unknown'] = 'unknown'
    season_scope: Literal['current', 'historical', 'future']
    season: str
    competition: str
    source: Optional[str] = None
    last_game_date: Optional[str] = None
    source_observed_at: Optional[str] = None
    recorded_appearances: int
    l5_samples: int
    l10_samples: int
    recorded_weeks: List[int] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class PropOut(OfferAvailabilityOut, GameIdentityOut):
    comparison: Optional[SportsbookComparisonOut] = None
    statistics_coverage: Optional[StatisticsCoverageOut] = None
    id: str
    odds_event_id: Optional[str] = None
    player: PlayerOut
    prop_type: str
    line: float
    line_24h_ago: Optional[float]
    over_odds: Optional[int]
    under_odds: Optional[int]
    sportsbook: str
    game_time: Optional[datetime]
    opponent: Optional[str]
    is_home: bool
    popularity_count: int
    fatigue: Optional[FatigueOut]
    rank_score: Optional[float]
    reasons: Optional[List[str]]
    line_movement: Optional[float]
    best_over: Optional[BestLineOut] = None
    best_under: Optional[BestLineOut] = None
    sportsbook_count: int = 0
    sportsbook_offers: List[SportsbookOfferOut] = Field(default_factory=list)
    trends: Optional[ExactLineTrendsOut] = None
    discover_score: Optional[float] = None
    discover_reasons: Optional[List[str]] = None
    discover_components: Optional[dict] = None

    class Config:
        from_attributes = True

class FeedResponse(BaseModel):
    props: List[PropOut]
    total: int

class InteractionCreate(BaseModel):
    action: str   # like|dislike|save|add_to_slip|click|view
    side: Literal["over", "under"] = "over"
    sportsbook: Optional[str] = Field(default=None, min_length=1)
    line: Optional[float] = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_complete_offer(self):
        if (self.sportsbook is None) != (self.line is None):
            raise ValueError("sportsbook and line must be supplied together")
        return self


class SlipSelectionOut(OfferAvailabilityOut):
    sportsbook: Optional[str]
    line: Optional[float]
    odds: Optional[float]
    original_odds: Optional[float] = None
    original_observed_at: Optional[datetime] = None
    price_change: Optional[Literal["improved", "worsened", "unchanged"]] = None


class ExactSelectionCreate(BaseModel):
    sportsbook: str = Field(min_length=1, max_length=100)
    line: float = Field(allow_inf_nan=False)
    side: Literal["over", "under"]


class SlipEstimateItem(BaseModel):
    prop_id: str
    side: Literal["over", "under"]
    sportsbook: str = Field(min_length=1)
    line: float = Field(allow_inf_nan=False)

    @field_validator("prop_id")
    @classmethod
    def valid_prop_id(cls, value: str) -> str:
        return str(UUID(value))


class SlipEstimateCreate(BaseModel):
    items: List[SlipEstimateItem] = Field(min_length=2, max_length=12)
    assumed_correlation: float = Field(default=0.15, ge=0, le=0.6, allow_inf_nan=False)

class SlipItemOut(BaseModel):
    id: str
    prop_id: str
    side: str
    selection: SlipSelectionOut
    prop: Optional[PropOut]

class SlipOut(BaseModel):
    id: str
    status: str
    items: List[SlipItemOut]

class UserOut(BaseModel):
    id: str
    email: str
    username: Optional[str]
    fav_sports: List[str]
    fav_players: List[str]
    fav_prop_types: List[str]

    class Config:
        from_attributes = True

class OddsIngestionStatus(BaseModel):
    source: str
    fallback_used: bool
    live_games_found: int
    live_props_updated: int
    mock_props_updated: int
    total_props_updated: int
    last_updated: Optional[datetime]
    message: str
    matchups: List[str] = Field(default_factory=list)
    line_moved_up: Optional[int] = None
    line_moved_down: Optional[int] = None
    line_unchanged: Optional[int] = None
    stale_props_inactivated: Optional[int] = None
    status_available: bool = True
