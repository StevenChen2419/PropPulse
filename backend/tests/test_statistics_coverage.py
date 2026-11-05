"""Coverage is derived from recorded season data, never price or import freshness."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Player, Prop, PropBook, PlayerGameLog, User, SavedProp, Slip, SlipItem
from app.services.statistics_coverage import coverage_from_summary, player_statistics_coverage
from app.services.sports_statistics import normalize_artifact, build_sport_summary
from app.routers.props import serialize_prop
from app.routers.users import get_saved, get_slip
from app.schemas import PropOut
from sports_statistics_fixture import fixture, PLAYER

NOW=datetime(2026,10,20,18,tzinfo=timezone.utc)


class CoverageTests(unittest.TestCase):
    def summary(self, **changes):
        return dict(season='2026',competition='Regular Season',source='nflverse',latest_appearance='2026-10-17',
            last_observed_at='2026-10-20T12:00:00+00:00',recorded_appearances=8,
            l5=dict(appearances=5,points=dict(average=10,valid_samples=4)),
            l10=dict(appearances=8,points=dict(average=10,valid_samples=7)),recorded_weeks=[1,2,3,4,5,6]) | changes

    def test_old_game_recent_observation_and_partial_week_coverage_remain_unknown(self):
        result=coverage_from_summary(self.summary(latest_appearance='2026-07-22'), 'NFL',now=NOW)
        self.assertEqual(result['last_game_date'],'2026-07-22')
        self.assertEqual(result['source_observed_at'],'2026-10-20T12:00:00+00:00')
        self.assertEqual(result['state'],'partial_current_season')
        self.assertEqual(result['recorded_weeks'],[1,2,3,4,5,6])
        self.assertEqual((result['l5_samples'],result['l10_samples']),(5,8))
        self.assertEqual(result['completeness'],'unknown')

    def test_large_current_sample_is_not_complete_and_historical_empty_are_distinct(self):
        summary=self.summary(recorded_appearances=30,l10=dict(appearances=10,points=dict(valid_samples=10)))
        current=coverage_from_summary(summary,'NFL',now=NOW)
        self.assertEqual(current['state'],'current_season')
        self.assertEqual(current['completeness'],'unknown')
        historical=coverage_from_summary(summary | dict(season='2025'),'NFL',now=NOW)
        self.assertEqual(historical['state'],'historical_season')
        empty=coverage_from_summary(dict(season='2026-27',recorded_appearances=0),'NBA',now=NOW)
        self.assertEqual(empty['state'],'no_recorded_games')
        self.assertEqual(empty['season_scope'],'current')
        self.assertIsNone(empty['source_observed_at'])
        self.assertIn('ingestion time is not substituted',empty['limitations'][1])

    def test_all_sports_use_existing_filtered_summaries(self):
        for sport in ['WNBA','NHL','NFL','MLB']:
            artifact,mappings=fixture(sport)
            rows=normalize_artifact(artifact,mappings,season=artifact['season'])['records']
            player=SimpleNamespace(id=PLAYER,sport=sport,position=None)
            summary=build_sport_summary(player,[SimpleNamespace(**r) for r in rows],season=artifact['season'],now=NOW)
            self.assertEqual(summary['coverage']['recorded_appearances'],1)
            self.assertEqual(summary['coverage']['season_scope'],'historical')
            self.assertEqual(summary['coverage']['source'],artifact['source'])
        player=SimpleNamespace(id=PLAYER,sport='NBA')
        coverage=player_statistics_coverage(player,[],now=NOW)
        self.assertEqual(coverage['state'],'no_recorded_games')
        self.assertEqual(coverage['l10_samples'],0)

    def test_saved_slip_and_feed_share_coverage_and_preserve_expired_selection(self):
        engine=create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine,tables=[m.__table__ for m in
            (Player,Prop,PropBook,PlayerGameLog,SavedProp,Slip,SlipItem)])
        artifact,mappings=fixture('WNBA')
        local_id='abc11111-1111-4111-8111-111111111111'
        mappings[0]['player_id']=local_id
        artifact['season']='2026'; artifact['observed_at']='2026-10-19T12:00:00+00:00'
        row=artifact['responses'][0]['payload'][0]
        row.update(season_id='22026',game_date='2026-07-22',game_id='1022600001')
        artifact['responses'][0]['schedule'][0]['game_id']='1022600001'
        records=normalize_artifact(artifact,mappings,season='2026')['records']
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(engine) as db:
            player=Player(id=local_id,name='Invented coverage player',sport='WNBA',team='Fixture',team_abbr='FIX')
            user=SimpleNamespace(id='abcdef22-2222-4222-8222-222222222222')
            db.add(player);db.flush()
            prop=Prop(player_id=local_id,prop_type='points',line=20.5,sportsbook='FanDuel',
                game_time=now+timedelta(days=1),odds_event_id='fixture-provider-event',is_active=True)
            db.add(prop);db.flush()
            db.add(PropBook(prop_id=prop.id,sportsbook='FanDuel',line=20.5,over_odds=-110,under_odds=120,
                provider_observed_at=now-timedelta(hours=7),ingested_at=now))
            db.add_all(PlayerGameLog(**r) for r in records)
            db.add(SavedProp(user_id=user.id,prop_id=prop.id))
            slip=Slip(user_id=user.id,status='open');db.add(slip);db.flush()
            item=SlipItem(slip_id=slip.id,prop_id=prop.id,sportsbook='FanDuel',line=20.5,side='under')
            db.add(item);db.commit()
            feed=serialize_prop(prop,{local_id:db.query(PlayerGameLog).all()})
            # Subject lookup's PostgreSQL ARRAY fatigue columns are unrelated
            # to coverage; exercise saved/slip row reads and real serialization.
            with patch('app.routers.users._selection_subjects', return_value=({prop.id:prop},{})):
                saved=get_saved(user,db)['saved'][0]
                selection=get_slip(user,db)['slip']['items'][0]
            self.assertEqual(feed['statistics_coverage'],saved['statistics_coverage'])
            self.assertEqual(feed['statistics_coverage'],selection['prop']['statistics_coverage'])
            self.assertEqual(saved['availability'],'expired')
            self.assertEqual(selection['selection']['availability'],'expired')
            self.assertIsNone(selection['selection']['odds'])
            self.assertEqual((item.side,item.sportsbook,item.line),('under','FanDuel',20.5))
            self.assertEqual(saved['statistics_coverage']['last_game_date'],'2026-07-22')
            self.assertEqual(PropOut.model_validate(saved).statistics_coverage.completeness,'unknown')
            db.rollback()


if __name__=='__main__':unittest.main()
