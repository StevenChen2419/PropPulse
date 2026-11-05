"""Pure validation and isolated ORM tests; no providers or application database."""
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Player, Prop
from app.services.event_identity import validate_event_metadata, link_prop_to_event


def metadata(**overrides):
    return {**dict(provider="the_odds_api", provider_event_id="Opaque:Case/42",
                   sport_key="basketball_nba", home_team="Home Team", away_team="Away Team",
                   scheduled_start_at=datetime(2026, 10, 20, 15, tzinfo=timezone(timedelta(hours=-4)))),
            **overrides}


class EventValidationTests(unittest.TestCase):
    def test_canonical_keys_opaque_provider_id_and_utc(self):
        values = validate_event_metadata(**metadata(provider=" THE_ODDS_API ", sport_key=" BASKETBALL_NBA "))
        self.assertEqual(values["provider"], "the_odds_api")
        self.assertEqual(values["sport_key"], "basketball_nba")
        self.assertEqual(values["provider_event_id"], "Opaque:Case/42")
        self.assertEqual(values["scheduled_start_at"], datetime(2026, 10, 20, 19))
        opaque = " Case/Sensitive: 42 "
        self.assertEqual(validate_event_metadata(**metadata(provider_event_id=opaque))["provider_event_id"], opaque)

    def test_missing_unknown_and_invalid_identity_is_rejected(self):
        for field, values in (("provider", [None, "", " ", "bad provider"]),
                              ("provider_event_id", [None, "", " ", "bad\nidentity"]),
                              ("sport_key", [None, "", "unknown_sport"])):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_event_metadata(**metadata(**{field: value}))

    def test_team_names_must_be_known_and_distinct(self):
        for field in ("home_team", "away_team"):
            for value in (None, "", " ", "UNK", "unknown", "TBD"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_event_metadata(**metadata(**{field: value}))
        with self.assertRaises(ValueError):
            validate_event_metadata(**metadata(away_team=" home   TEAM "))

    def test_external_timestamp_requires_offset_and_internal_utc_is_explicit(self):
        for value in (None, True, "not-a-time", "2026-10-20T19:00:00", datetime(2026, 10, 20)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_event_metadata(**metadata(scheduled_start_at=value))
        self.assertEqual(validate_event_metadata(**metadata(scheduled_start_at="2026-10-20T19:00:00Z"))["scheduled_start_at"],
                         datetime(2026, 10, 20, 19))
        self.assertEqual(Event(**metadata()).scheduled_start_at, datetime(2026, 10, 20, 19))
        self.assertEqual(Event(**metadata(scheduled_start_at=datetime(2026, 10, 20, 19))).scheduled_start_at,
                         datetime(2026, 10, 20, 19))


class EventRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        @event.listens_for(self.engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine, tables=[m.__table__ for m in (Event, Player, Prop)])
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.player = Player(name="Test Player", team="Home Team", team_abbr="HOM", sport="NBA")
        self.first = Event(**metadata())
        self.second = Event(**metadata(provider_event_id="second"))
        self.prop = Prop(player=self.player, prop_type="points", line=20.5,
                         odds_event_id="Opaque:Case/42", odds_sport_key="basketball_nba")
        self.db.add_all([self.player, self.first, self.second, self.prop])
        self.db.commit()

    def test_nullable_relationship_preserves_legacy_identity(self):
        self.assertIsNone(self.prop.event_id)
        self.assertIsNone(self.prop.event)
        self.assertEqual(self.prop.odds_event_id, "Opaque:Case/42")
        self.assertEqual(self.db.query(Event).count(), 2)

    def test_explicit_link_and_both_orm_reassignment_paths_are_guarded(self):
        prop_id = self.prop.id
        link_prop_to_event(self.prop, self.first)
        self.db.commit()
        self.assertEqual(self.first.props[0].id, prop_id)
        self.assertEqual(self.prop.event_id, self.first.id)
        link_prop_to_event(self.prop, self.first)  # Idempotent known identity.
        for name, value in (("event_id", self.second.id), ("event_id", None),
                            ("event", self.second), ("event", None)):
            with self.subTest(attribute=name), self.assertRaises(ValueError):
                setattr(self.prop, name, value)
        with self.assertRaises(ValueError):
            link_prop_to_event(self.prop, self.second)
        self.db.rollback()
        self.assertEqual(self.prop.id, prop_id)
        self.assertEqual(self.prop.event_id, self.first.id)

    def test_legacy_identity_conflicts_never_attach(self):
        with self.assertRaisesRegex(ValueError, "provider event"):
            link_prop_to_event(self.prop, self.second)
        self.prop.odds_sport_key = "baseball_mlb"
        with self.assertRaisesRegex(ValueError, "sport"):
            link_prop_to_event(self.prop, self.first)
        self.assertIsNone(self.prop.event_id)

    def test_persisted_identity_immutable_but_schedule_correction_allowed(self):
        for field, value in (("provider", "another_provider"), ("sport_key", "baseball_mlb"),
                             ("provider_event_id", "changed")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                setattr(self.first, field, value)
        self.first.scheduled_start_at = datetime(2026, 10, 21, 18, tzinfo=timezone(timedelta(hours=2)))
        self.db.commit()
        self.assertEqual(self.first.scheduled_start_at, datetime(2026, 10, 21, 16))

    def test_loaded_relationship_does_not_null_link_on_event_deletion(self):
        link_prop_to_event(self.prop, self.first)
        self.db.commit()
        prop_id, event_id = self.prop.id, self.first.id
        self.assertEqual(len(self.first.props), 1)
        self.db.delete(self.first)
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()
        self.assertEqual(self.db.get(Prop, prop_id).event_id, event_id)
        self.assertIsNotNone(self.db.get(Event, event_id))

    def test_model_rejects_duplicate_team_identity(self):
        with self.assertRaises(ValueError):
            Event(**metadata(home_team="Away Team"))
