import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, Integer,
    DateTime, ForeignKey, Text, JSON, ARRAY, Index, UniqueConstraint, CheckConstraint, event, inspect
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates, attributes
from app.database import Base
from app.services.event_identity import identity_value, team_value, event_time

def gen_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    username = Column(String, nullable=True)
    fav_sports = Column(ARRAY(String), default=list)
    fav_players = Column(ARRAY(String), default=list)       # player UUIDs
    fav_prop_types = Column(ARRAY(String), default=list)    # "points","assists",...
    created_at = Column(DateTime, default=datetime.utcnow)

    interactions = relationship("Interaction", back_populates="user")
    saved_props = relationship("SavedProp", back_populates="user")
    slips = relationship("Slip", back_populates="user")


class Player(Base):
    __tablename__ = "players"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, index=True)
    team = Column(String, nullable=False)
    team_abbr = Column(String, nullable=False)
    sport = Column(String, nullable=False, default="NBA")
    position = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    jersey_number = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    props = relationship("Prop", back_populates="player")
    fatigue_scores = relationship("FatigueScore", back_populates="player")
    game_logs = relationship("PlayerGameLog", back_populates="player")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("provider", "sport_key", "provider_event_id", name="uq_events_provider_sport_event"),
        Index("ix_events_sport_start", "sport_key", "scheduled_start_at"),
        CheckConstraint("length(trim(provider)) > 0 AND length(trim(sport_key)) > 0 AND length(trim(provider_event_id)) > 0", name="ck_events_nonempty_identity"),
        CheckConstraint("length(trim(home_team)) > 0 AND length(trim(away_team)) > 0", name="ck_events_nonempty_teams"),
        CheckConstraint("lower(trim(home_team)) != lower(trim(away_team))", name="ck_events_distinct_teams"),
    )
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    provider = Column(String, nullable=False)
    provider_event_id = Column(String, nullable=False)
    sport_key = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    scheduled_start_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Never null out linked props to make an Event deletion succeed.
    props = relationship("Prop", back_populates="event", passive_deletes="all")

    @validates("provider", "provider_event_id", "sport_key")
    def validate_identity(self, key, value):
        value = identity_value(key, value)
        state = inspect(self)
        if state.persistent and getattr(self, key) != value:
            raise ValueError("Persisted provider event identity cannot be changed")
        return value

    @validates("home_team", "away_team")
    def validate_team(self, key, value):
        value = team_value(value)
        other = getattr(self, "away_team" if key == "home_team" else "home_team", None)
        if other and value.casefold() == other.casefold():
            raise ValueError("Home and away teams must be distinct")
        return value

    @validates("scheduled_start_at", "updated_at")
    def validate_time(self, key, value):
        return event_time(value)


class Prop(Base):
    __tablename__ = "props"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    player_id = Column(UUID(as_uuid=False), ForeignKey("players.id"), nullable=False)
    event_id = Column(UUID(as_uuid=False), ForeignKey("events.id", name="fk_props_event_id_events", ondelete="RESTRICT"), nullable=True, index=True)
    prop_type = Column(String, nullable=False)      # "points","assists","rebounds","threes"
    line = Column(Float, nullable=False)
    line_24h_ago = Column(Float, nullable=True)     # for line movement signal
    over_odds = Column(Integer, default=-110)
    under_odds = Column(Integer, default=-110)
    sportsbook = Column(String, default="FanDuel")
    odds_event_id = Column(String, nullable=True, index=True)
    odds_sport_key = Column(String, nullable=True, index=True)
    odds_last_seen_at = Column(DateTime, nullable=True, index=True)
    game_time = Column(DateTime, nullable=True)
    opponent = Column(String, nullable=True)
    is_home = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    popularity_count = Column(Integer, default=0)   # interaction count cache
    created_at = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="props")
    event = relationship("Event", back_populates="props")
    interactions = relationship("Interaction", back_populates="prop")
    saved_by = relationship("SavedProp", back_populates="prop")
    book_offers = relationship(
        "PropBook",
        back_populates="prop",
        cascade="all, delete-orphan",
    )
    book_snapshots = relationship(
        "PropBookSnapshot",
        back_populates="prop",
        cascade="all, delete-orphan",
    )
    fatigue_score = relationship("FatigueScore", uselist=False,
        primaryjoin="Prop.player_id == foreign(FatigueScore.player_id)",
        viewonly=True)


@event.listens_for(Prop.event_id, "set", retval=True, active_history=True)
def preserve_prop_event_id(target, value, oldvalue, initiator):
    if oldvalue not in (None, attributes.NO_VALUE, attributes.NEVER_SET) and value != oldvalue:
        raise ValueError("Known prop event identity cannot be reassigned or cleared")
    return value


@event.listens_for(Prop.event, "set", retval=True, active_history=True)
def preserve_prop_event_relationship(target, value, oldvalue, initiator):
    if target.event_id is not None and (value is None or value.id != target.event_id):
        raise ValueError("Known prop event identity cannot be reassigned or cleared")
    if oldvalue not in (None, attributes.NO_VALUE, attributes.NEVER_SET) and value is not oldvalue:
        if value is None or oldvalue.id != value.id:
            raise ValueError("Known prop event identity cannot be reassigned or cleared")
    return value


class PropBook(Base):
    __tablename__ = "prop_books"
    __table_args__ = (
        UniqueConstraint("prop_id", "sportsbook", name="uq_prop_books_prop_sportsbook"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    prop_id = Column(UUID(as_uuid=False), ForeignKey("props.id", ondelete="CASCADE"), nullable=False, index=True)
    sportsbook = Column(String, nullable=False)
    line = Column(Float, nullable=False)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)
    # updated_at remains the legacy local write timestamp. Never an observation.
    provider_bookmaker_key = Column(String, nullable=True)
    provider_title = Column(String, nullable=True)
    provider_observed_at = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    prop = relationship("Prop", back_populates="book_offers")


class PropBookSnapshot(Base):
    __tablename__ = "prop_book_snapshots"
    __table_args__ = (
        Index(
            "ix_prop_book_snapshots_prop_book_time",
            "prop_id",
            "sportsbook",
            "captured_at",
        ),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    prop_id = Column(
        UUID(as_uuid=False),
        ForeignKey("props.id", ondelete="CASCADE"),
        nullable=False,
    )
    sportsbook = Column(String, nullable=False)
    line = Column(Float, nullable=False)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    prop = relationship("Prop", back_populates="book_snapshots")


class PlayerGameLog(Base):
    __tablename__ = "player_game_logs"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "external_game_id",
            name="uq_player_game_logs_player_game",
        ),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    player_id = Column(
        UUID(as_uuid=False),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sport = Column(String, nullable=False, index=True)
    external_game_id = Column(String, nullable=False, index=True)
    game_date = Column(DateTime, nullable=False, index=True)
    opponent = Column(String, nullable=True)
    is_home = Column(Boolean, nullable=True)
    stats = Column(JSON, nullable=False, default=dict)
    source = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    player = relationship("Player", back_populates="game_logs")


class FatigueScore(Base):
    __tablename__ = "fatigue_scores"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    player_id = Column(UUID(as_uuid=False), ForeignKey("players.id"), nullable=False, unique=True)
    fatigue_score = Column(Float, default=0.0)      # 0–1, higher = more fatigued
    workload_score = Column(Float, default=0.0)
    back_to_back = Column(Boolean, default=False)
    games_in_7d = Column(Integer, default=0)
    rolling_minutes_7d = Column(Float, default=0.0)
    minutes_trend = Column(Float, default=0.0)      # positive = trending up
    performance_volatility = Column(Float, default=0.0)
    risk_flags = Column(ARRAY(String), default=list)
    shap_reasons = Column(ARRAY(String), default=list)   # human-readable
    scored_at = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="fatigue_scores")


class Ranking(Base):
    __tablename__ = "rankings"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    prop_id = Column(UUID(as_uuid=False), ForeignKey("props.id"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)  # null = global
    final_score = Column(Float, default=0.0)
    user_affinity = Column(Float, default=0.0)
    player_affinity = Column(Float, default=0.0)
    prop_type_affinity = Column(Float, default=0.0)
    popularity = Column(Float, default=0.0)
    line_movement = Column(Float, default=0.0)
    fatigue_edge = Column(Float, default=0.0)
    reasons = Column(ARRAY(String), default=list)
    ranked_at = Column(DateTime, default=datetime.utcnow)


class Interaction(Base):
    __tablename__ = "interactions"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    prop_id = Column(UUID(as_uuid=False), ForeignKey("props.id"), nullable=False)
    action = Column(String, nullable=False)  # like|dislike|save|add_to_slip|click|view
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="interactions")
    prop = relationship("Prop", back_populates="interactions")


class SavedProp(Base):
    __tablename__ = "saved_props"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    prop_id = Column(UUID(as_uuid=False), ForeignKey("props.id"), nullable=False)
    saved_at = Column(DateTime, default=datetime.utcnow)
    # NULL selection fields identify legacy/generic bookmarks.
    sportsbook = Column(String, nullable=True)
    line = Column(Float, nullable=True)
    side = Column(String, nullable=True)
    original_odds = Column(Float, nullable=True)
    original_observed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="saved_props")
    prop = relationship("Prop", back_populates="saved_by")


class Slip(Base):
    __tablename__ = "slips"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status = Column(String, default="open")   # open|submitted|settled
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="slips")
    items = relationship("SlipItem", back_populates="slip")


class SlipItem(Base):
    __tablename__ = "slip_items"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    slip_id = Column(UUID(as_uuid=False), ForeignKey("slips.id"), nullable=False)
    prop_id = Column(UUID(as_uuid=False), ForeignKey("props.id"), nullable=False)
    side = Column(String, default="over")   # over|under
    sportsbook = Column(String, nullable=True)
    line = Column(Float, nullable=True)
    original_odds = Column(Float, nullable=True)
    original_observed_at = Column(DateTime, nullable=True)

    slip = relationship("Slip", back_populates="items")


class NBAEvidenceRecord(Base):
    """Append-only normalized evidence; no inferred Event or game-log linkage."""
    __tablename__ = "nba_evidence_records"
    __table_args__ = (
        UniqueConstraint("provider", "sport", "kind", "identity", "fingerprint", name="uq_nba_evidence_identity_fingerprint"),
        Index("ix_nba_evidence_namespace_identity", "provider", "sport", "kind", "identity"),
        CheckConstraint("provider IN ('espn', 'nba_com') AND sport = 'NBA'", name="ck_nba_evidence_namespace"),
        CheckConstraint("kind IN ('game', 'participation', 'athlete', 'team', 'membership', 'coverage')", name="ck_nba_evidence_kind"),
        CheckConstraint("length(trim(identity)) > 0 AND length(trim(source)) > 0", name="ck_nba_evidence_nonempty"),
        CheckConstraint("(team_id IS NULL OR length(trim(team_id)) > 0) AND (game_id IS NULL OR length(trim(game_id)) > 0)", name="ck_nba_evidence_optional_identity"),
        CheckConstraint("length(fingerprint) = 64 AND lower(fingerprint) = fingerprint", name="ck_nba_evidence_fingerprint"),
    )
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    provider = Column(String, nullable=False, default="espn")
    sport = Column(String, nullable=False, default="NBA")
    kind = Column(String, nullable=False)
    identity = Column(String, nullable=False)
    player_id = Column(UUID(as_uuid=False), ForeignKey("players.id", name="fk_nba_evidence_player_id_players", ondelete="RESTRICT"), nullable=True, index=True)
    team_id = Column(String, nullable=True, index=True)
    game_id = Column(String, nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    source = Column(String, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    fingerprint = Column(String(64), nullable=False)

    @validates("observed_at", "ingested_at")
    def validate_evidence_time(self, key, value):
        return event_time(value)


@event.listens_for(NBAEvidenceRecord, "before_update")
@event.listens_for(NBAEvidenceRecord, "before_delete")
def preserve_nba_evidence(mapper, connection, target):
    raise ValueError("NBA evidence is append-only; append a new observation instead")
