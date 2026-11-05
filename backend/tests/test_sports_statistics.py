from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from app.services.sports_statistics import normalize_artifact, build_sport_summary, reviewed_mappings, innings_outs, season_name
from scripts.refresh_sports_odds import plan_refresh, plan_digest, execute
from scripts.refresh_sports_statistics import main, load_artifact
from sports_statistics_fixture import fixture, PLAYER

NOW = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)


class SportsStatisticsTests(unittest.TestCase):
    def test_reviewed_nhl_season_overrides_calendar_boundary_in_line_history(self):
        from app.services.trend_service import build_history_research
        data,mappings=fixture('NHL')
        record=self.normalize('NHL',data,mappings)['records'][0]
        record['game_date']=datetime(2025,9,29,4,tzinfo=timezone.utc)
        row=SimpleNamespace(**record)
        result=build_history_research('NHL','goals',0.5,2026,[row],now=NOW)
        self.assertEqual(result['history']['current_season_games'],1)
        self.assertEqual(result['results'][0]['season'],2026)

    def test_october_19_current_seasons_are_isolated_from_historical_rows(self):
        as_of = datetime(2026, 10, 19, 23, tzinfo=timezone.utc)
        for sport in ('NBA', 'WNBA', 'NHL', 'NFL', 'MLB'):
            expected = '2026-27' if sport in {'NBA', 'NHL'} else '2026'
            with self.subTest(sport=sport):
                self.assertEqual(season_name(sport, as_of), expected)
                if sport == 'NBA':
                    continue  # Existing NBA summary/refresh tests own its provider contract.
                artifact, mappings = fixture(sport)
                logs = [SimpleNamespace(**row) for row in self.normalize(sport)['records']]
                player = SimpleNamespace(id=PLAYER, sport=sport, position=None)
                summary = build_sport_summary(player, logs, season=expected, now=as_of)
                self.assertEqual(summary['recorded_appearances'], 0)
                self.assertEqual(summary['status'], 'unavailable')
                with self.assertRaises(ValueError):
                    normalize_artifact(artifact, mappings, season=expected)

    def test_current_regular_season_formats_keep_actual_short_samples(self):
        as_of = datetime(2026, 10, 19, 23, tzinfo=timezone.utc)
        for sport, role in [('WNBA', 'player'), ('NHL', 'skater'), ('NHL', 'goalie'),
                            ('NFL', 'player'), ('MLB', 'batter'), ('MLB', 'pitcher')]:
            with self.subTest(sport=sport, role=role):
                artifact, mappings = fixture(sport, role)
                # Invented contract fixtures, not collected 2026 coverage.
                encoded = json.dumps(artifact).replace('2025-26', '2026-27').replace('20252026', '20262027')
                encoded = encoded.replace('2025', '2026').replace('1022500001', '1022600001')
                artifact = json.loads(encoded)
                artifact['observed_at'] = as_of.isoformat()
                season = '2026-27' if sport == 'NHL' else '2026'
                records = normalize_artifact(artifact, mappings, season=season)['records']
                self.assertEqual(len(records), 1)
                summary = build_sport_summary(SimpleNamespace(id=PLAYER, sport=sport, position=None),
                    [SimpleNamespace(**row) for row in records], season=season, now=as_of)
                self.assertEqual(summary['status'], 'available')
                self.assertEqual(summary['l5']['appearances'], 1)
                self.assertEqual(summary['l10']['appearances'], 1)
                self.assertEqual(summary['competition'], 'Regular Season')
                for metric in summary['metrics']:
                    self.assertIn(summary['l5'][metric['key']]['valid_samples'], (0, 1))

    def normalize(self, sport, artifact=None, mappings=None, role=None):
        original, crosswalk = fixture(sport, role)
        return normalize_artifact(artifact or original, mappings or crosswalk, season=original['season'])

    def test_all_adapters_preserve_exact_identity_and_observation(self):
        for sport in ('WNBA', 'NHL', 'NFL', 'MLB'):
            with self.subTest(sport=sport):
                batch = self.normalize(sport)
                self.assertEqual(len(batch['records']), 1)
                row = batch['records'][0]
                self.assertEqual(row['player_id'], PLAYER)
                self.assertTrue(row['external_game_id'].startswith(row['source'] + ':'))
                self.assertTrue(row['stats']['_research']['appearance'])
                self.assertEqual(row['stats']['_research']['observed_at'], '2026-06-20T12:00:00+00:00')

    def test_missing_is_not_zero_and_true_zero_survives(self):
        row = self.normalize('WNBA')['records'][0]
        self.assertEqual(row['stats']['points'], 0)
        self.assertIsNone(row['stats']['threes'])
        self.assertEqual(row['stats']['minutes'], 24.5)
        self.assertEqual(row['opponent'], '2')

    def test_nhl_role_metrics_do_not_leak(self):
        goalie = self.normalize('NHL', role='goalie')['records'][0]
        skater = self.normalize('NHL')['records'][0]
        self.assertEqual(goalie['stats']['saves'], 26)
        self.assertNotIn('goals', goalie['stats'])
        self.assertNotIn('saves', skater['stats'])
        data, mappings = fixture('NHL', 'goalie')
        del data['responses'][0]['payload']['gameLog'][0]['saves']
        row = self.normalize('NHL', data, mappings)['records'][0]
        self.assertIsNone(row['stats']['saves'])

    def test_mlb_innings_and_roles(self):
        for value, expected in [('5.2',17), ('0.1',1), ('6.0',18), ('4.3',None), ('bad',None)]:
            self.assertEqual(innings_outs(value),expected)
        pitcher = self.normalize('MLB', role='pitcher')['records'][0]
        batter = self.normalize('MLB')['records'][0]
        self.assertEqual(pitcher['stats']['outs_recorded'],17)
        self.assertNotIn('hits',pitcher['stats'])
        self.assertNotIn('strikeouts',batter['stats'])

    def test_mlb_postponed_final_alias_is_not_a_completed_appearance(self):
        data, mappings = fixture('MLB')
        played = data['responses'][0]['games'][0]
        played['status'].update(codedGameState='F', detailedState='Final')
        postponed = deepcopy(played)
        postponed['status'].update(codedGameState='D', detailedState='Postponed')
        data['responses'][0]['games'].insert(0, postponed)
        self.assertEqual(len(self.normalize('MLB', data, mappings)['records']), 1)
        data['responses'][0]['games'] = [postponed]
        with self.assertRaises(ValueError):
            self.normalize('MLB', data, mappings)
        data['responses'][0]['games'] = [played, deepcopy(played)]
        with self.assertRaises(ValueError):
            self.normalize('MLB', data, mappings)

    def test_nhl_missing_ice_time_with_recorded_statistics_still_appeared(self):
        data,mappings=fixture('NHL')
        del data['responses'][0]['payload']['gameLog'][0]['toi']
        row=self.normalize('NHL',data,mappings)['records'][0]
        self.assertIsNone(row['stats']['time_on_ice'])
        self.assertEqual(row['stats']['shots_on_goal'],5)

    def test_two_way_mlb_combines_roles_without_duplicate_game(self):
        data,mappings=fixture('MLB')
        mappings[0]['roles']=['batter','pitcher']
        pitching,_=fixture('MLB','pitcher')
        data['responses'].extend(pitching['responses'])
        rows=self.normalize('MLB',data,mappings)['records']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['stats']['_research']['role'],'two_way')
        self.assertEqual(rows[0]['stats']['hits'],2)
        self.assertEqual(rows[0]['stats']['outs_recorded'],17)

    def test_nfl_week_needs_unique_final_schedule_game(self):
        for mutation in ('missing', 'duplicate', 'uncompleted', 'aggregate', 'identity'):
            data,mappings=fixture('NFL')
            response=data['responses'][0]
            if mutation=='missing': response['schedule']=[]
            if mutation=='duplicate': response['schedule']*=2
            if mutation=='uncompleted': response['schedule'][0]['home_score']=None
            if mutation=='aggregate': response['summary_level']='reg'
            if mutation=='identity': response['payload'][0]['game_id']='wrong'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.normalize('NFL',data,mappings)
        self.assertEqual(self.normalize('NFL')['records'][0]['stats']['rush_yds'],-2)

    def test_conflicting_duplicate_rejected_identical_deduplicated(self):
        for sport in ('WNBA','NHL','NFL','MLB'):
            data,mappings=fixture(sport)
            data['responses']*=2
            self.assertEqual(len(self.normalize(sport,data,mappings)['records']),1)
        data,mappings=fixture('WNBA')
        data['responses'].append(deepcopy(data['responses'][0]))
        data['responses'][1]['payload'][0]['pts']=999
        with self.assertRaises(ValueError): self.normalize('WNBA',data,mappings)

    def test_crosswalk_conflicts_and_unreviewed_players_fail_closed(self):
        data,mappings=fixture('WNBA')
        with self.assertRaises(ValueError): reviewed_mappings(mappings*2)
        mappings[0]['verified']=False
        with self.assertRaises(ValueError): self.normalize('WNBA',data,mappings)
        _,mappings=fixture('WNBA')
        mappings[0]['athlete_id']='999'
        batch=self.normalize('WNBA',data,mappings)
        self.assertEqual(batch['records'],[])
        self.assertEqual(batch['rejected'][0]['reason'],'unresolved_mapping')

    def test_identity_season_and_competition_mismatch(self):
        for sport in ('WNBA','NHL','NFL','MLB'):
            data,mappings=fixture(sport)
            data['competition']='Playoffs'
            with self.assertRaises(ValueError): self.normalize(sport,data,mappings)
        data,mappings=fixture('WNBA')
        data['responses'][0]['payload'][0]['player_id']=555
        with self.assertRaises(ValueError): self.normalize('WNBA',data,mappings)

    def test_prior_completed_appearances_only(self):
        data,mappings=fixture('WNBA')
        data['responses'][0]['payload'][0]['wl']=None
        self.assertEqual(self.normalize('WNBA',data,mappings)['records'],[])
        data,mappings=fixture('WNBA')
        data['observed_at']='2025-06-10T12:00:00+00:00'
        self.assertEqual(self.normalize('WNBA',data,mappings)['records'],[])

    def test_l5_l10_independent_metric_denominators_and_order(self):
        record=self.normalize('WNBA')['records'][0]
        rows=[]
        for index in range(12):
            row=deepcopy(record)
            row['external_game_id']+=str(index)
            row['game_date']+=timedelta(days=index)
            row['stats']['points']=None if index==11 else index
            rows.append(SimpleNamespace(**row))
        summary=build_sport_summary(SimpleNamespace(id=PLAYER,sport='WNBA'),list(reversed(rows))+rows[:1],season='2025',now=NOW)
        self.assertEqual(summary['recorded_appearances'],12)
        self.assertEqual(summary['l5']['points'],dict(average=8.5,valid_samples=4))
        self.assertEqual(summary['l10']['points'],dict(average=6,valid_samples=9))
        self.assertEqual(summary['l5']['threes'],dict(average=None,valid_samples=0))
        self.assertEqual(summary['opponent_history'][0]['l10']['appearances'],10)

    def test_scope_separation_and_missing_week_is_not_dnp(self):
        record=self.normalize('NFL')['records'][0]
        player=SimpleNamespace(id=PLAYER,sport='NFL')
        for season,competition,expected in [('2025','Regular Season',1),('2026','Regular Season',0),('2025','Playoffs',0)]:
            result=build_sport_summary(player,[SimpleNamespace(**record)],season=season,competition=competition,now=NOW)
            self.assertEqual(result['recorded_appearances'],expected)
        wrong=deepcopy(record); wrong['sport']='MLB'
        result=build_sport_summary(player,[SimpleNamespace(**wrong)],season='2025',now=NOW)
        self.assertEqual(result['status'],'unavailable')

    def test_malformed_legacy_json_is_unavailable_without_breaking_summary(self):
        record=self.normalize('NHL')['records'][0]
        for stats in (None, [], {'_research':None}, {'_research':[]}, {'_research':{}}):
            row=SimpleNamespace(**{**record,'stats':stats})
            data=build_sport_summary(SimpleNamespace(id=PLAYER,sport='NHL'),[row],season='2025-26',now=NOW)
            self.assertEqual(data['status'],'unavailable')

    def test_goalie_pitcher_summary_configuration(self):
        for sport,role,metric,absent in [('NHL','goalie','saves','goals'),('MLB','pitcher','outs_recorded','hits')]:
            record=self.normalize(sport,role=role)['records'][0]
            data=build_sport_summary(SimpleNamespace(id=PLAYER,sport=sport),[SimpleNamespace(**record)],season=record['stats']['_research']['season'],now=NOW)
            self.assertIn(metric,data['l5']); self.assertNotIn(absent,data['l5'])

    def test_cli_offline_artifact_and_wrong_approval_never_connect(self):
        data,mappings=fixture('WNBA')
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for name,value in [('artifact',data),('mapping',mappings),('approval',{})]:
                (folder/(name+'.json')).write_text(json.dumps(value))
            args=['--sports','wnba','--season','2025','--artifact',str(folder/'artifact.json'),'--mapping',str(folder/'mapping.json')]
            with patch('sqlalchemy.engine.Engine.connect',side_effect=AssertionError('DB forbidden')), patch('httpx.Client.get',side_effect=AssertionError('HTTP forbidden')), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args),0)
                self.assertEqual(json.loads(output.getvalue())['database_writes'],0)
                self.assertEqual(main(args+['--import-approved',str(folder/'approval.json')]),1)

    def test_published_csv_loads_only_selected_athlete_and_competition(self):
        data,mappings=fixture('WNBA')
        response=data['responses'][0]
        row=response.pop('payload')[0]
        response['payload_file']='release.csv'
        import csv
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            with (folder/'release.csv').open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row)); writer.writeheader()
                writer.writerows([row,{**row,'player_id':None},{**row,'player_id':555},{**row,'season_id':'42025'}])
            (folder/'artifact.json').write_text(json.dumps(data))
            loaded=load_artifact(folder/'artifact.json')
            self.assertEqual(loaded['responses'][0]['asset_rows'],4)
            self.assertEqual(loaded['responses'][0]['selected_rows'],1)
            self.assertEqual(len(self.normalize('WNBA',loaded,mappings)['records']),1)


class UnifiedOddsTests(unittest.TestCase):
    def test_explicit_event_selection_preserves_future_events_beyond_default_horizon(self):
        from scripts import fetch_odds as importer
        event=dict(id='approved',home_team='Home',away_team='Away',commence_time=(datetime.now(timezone.utc)+timedelta(days=5)).isoformat())
        started={**event,'id':'started','commence_time':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}
        with patch.object(importer,'get',return_value=(200,[event,started],{})), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(importer.fetch_events(None,'basketball_wnba',importer.make_sport_status('basketball_wnba')),[])
            self.assertEqual(importer.fetch_events(None,'basketball_wnba',importer.make_sport_status('basketball_wnba'),approved_event_ids={'approved','started'}),[event])

    def coverage(self):
        return {'sports':{'basketball_wnba':dict(access='accessible', evidence='retained successful market response fixture',
            markets=['player_points','player_assists'],events=[dict(id='abcdef',home_team='Home',away_team='Away',commence_time='2026-10-21T19:00:00Z')]),
            'icehockey_nhl':dict(access='unsupported',markets=['player_goals'],events=[])}}

    def test_dry_run_exact_cost_and_tier_boundaries(self):
        plan=plan_refresh(self.coverage(),['basketball_wnba','icehockey_nhl'],max_credits=2)
        self.assertEqual(plan['estimated_max_credits'],2)
        self.assertEqual(plan['planned_max_requests'],3)
        self.assertEqual(plan['sports']['icehockey_nhl']['events'],[])
        self.assertEqual(plan['retries'],0)
        self.assertEqual(len(plan_digest(plan)),64)

    def test_credit_request_limit_and_unconfigured_market_rejected(self):
        with self.assertRaises(ValueError): plan_refresh(self.coverage(),['basketball_wnba'],max_credits=1)
        with self.assertRaises(ValueError): plan_refresh(self.coverage(),['basketball_wnba'],max_credits=2,max_requests=2)
        data=self.coverage(); data['sports']['basketball_wnba']['markets']=['invented']
        with self.assertRaises(ValueError): plan_refresh(data,['basketball_wnba'],max_credits=100)

    def test_unknown_tier_never_requests_player_odds(self):
        plan=plan_refresh({},['icehockey_nhl'],max_credits=0)
        self.assertEqual(plan['sports']['icehockey_nhl']['access'],'unknown')
        self.assertEqual(plan['estimated_max_credits'],0)
        with self.assertRaises(ValueError): execute(plan,'wrong digest')

    def test_explicit_probe_has_exact_cost_without_claiming_entitlement(self):
        data=self.coverage()
        entry=data['sports']['basketball_wnba']
        entry.update(access='probe',discovery_evidence='retained event listing')
        entry.pop('evidence')
        plan=plan_refresh(data,['basketball_wnba'],max_credits=2)
        self.assertEqual(plan['estimated_max_credits'],2)
        self.assertEqual(plan['sports']['basketball_wnba']['access'],'probe')
        self.assertIsNone(plan['sports']['basketball_wnba']['evidence'])
        entry.pop('discovery_evidence')
        with self.assertRaises(ValueError): plan_refresh(data,['basketball_wnba'],max_credits=2)

    def test_partial_provider_failure_continues_other_sports_without_roster_http(self):
        from scripts import fetch_odds as importer
        data=self.coverage()
        data['database_target']='testhost:5432/proppulse_test_phase8'
        data['sports']['icehockey_nhl']=deepcopy(data['sports']['basketball_wnba'])
        data['sports']['icehockey_nhl']['markets']=['player_goals']
        plan=plan_refresh(data,['basketball_wnba','icehockey_nhl'],max_credits=3)
        attempted=[]
        def verify(client,statuses):
            for status in statuses.values(): status['active']=True
            importer.ACTIVE_BUDGET.remaining=100
            return True
        def events(client,key,status,**kwargs):
            attempted.append(key)
            if key=='basketball_wnba': raise ValueError('fixture sport failure')
            return plan['sports'][key]['events']
        with patch.object(importer,'engine',SimpleNamespace(url='postgresql://phase8@testhost:5432/proppulse_test_phase8')), \
                patch('scripts.refresh_sports_odds.odds_ingestion_lock',return_value=contextlib.nullcontext(True)), \
                patch.object(importer,'verify_key_and_sports',side_effect=verify), \
                patch.object(importer,'fetch_events',side_effect=events), \
                patch.object(importer,'fetch_player_props',return_value=[]), \
                patch.object(importer,'load_team_directory',side_effect=AssertionError('Roster HTTP forbidden')), \
                patch.object(importer,'persist_sports') as persist, \
                patch.object(importer,'finalize_sport_status'), patch.object(importer,'aggregate_status',return_value={}), \
                patch.object(importer,'write_status'):
            report=execute(plan,plan_digest(plan))
        self.assertEqual(attempted,['basketball_wnba','icehockey_nhl'])
        self.assertEqual(report['sports']['basketball_wnba']['coverage'],'failed')
        self.assertEqual(report['sports']['icehockey_nhl']['coverage'],'no_offers')
        persist.assert_called_once()

    def test_rejected_market_stops_repeated_event_requests(self):
        from scripts import fetch_odds as importer
        status=importer.make_sport_status('icehockey_nhl')
        event=self.coverage()['sports']['basketball_wnba']['events'][0]
        with patch.object(importer,'get',return_value=(422,{'error_code':'INVALID_MARKET'},{})) as request, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(importer.fetch_player_props(None,'icehockey_nhl',[event,event],status),[])
        self.assertEqual(request.call_count,1)


import test_event_migration_postgres as pg_fixture


@unittest.skipUnless(pg_fixture.TEST_URL, 'Requires explicit disposable PostgreSQL URL')
class SportsStatisticsPostgresTests(unittest.TestCase):
    setUpClass = classmethod(pg_fixture.EventMigrationPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        from app.database import Base
        Base.metadata.create_all(self.engine)

    def test_idempotent_import_updates_and_rollback_preserve_all_sports(self):
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        from app.models import Player, PlayerGameLog
        from app.services.sports_statistics import import_records
        from uuid import uuid4
        for sport in ('WNBA','NHL','NFL','MLB'):
            data,mappings=fixture(sport)
            mappings[0]['player_id']=str(uuid4())
            rows=normalize_artifact(data,mappings,season=data['season'])['records']
            with Session(self.engine) as db, db.begin():
                db.add(Player(id=mappings[0]['player_id'],name='Invented contract player',team='Fixture',team_abbr='FIX',sport=sport))
            with Session(self.engine) as db, db.begin():
                from sqlalchemy import text
                db.execute(text('SET TRANSACTION READ ONLY'))
                self.assertEqual(import_records(db,rows,write=False)['new'],1)
                self.assertFalse(db.new or db.dirty or db.deleted)
            with Session(self.engine) as db, db.begin():
                self.assertEqual(import_records(db,rows)['new'],1)
                self.assertEqual(import_records(db,rows)['unchanged'],1)
                updated=deepcopy(rows); updated[0]['stats']['fixture_correction']=1
                self.assertEqual(import_records(db,updated)['updated'],1)
            bad=deepcopy(rows); bad[0]['stats']['_research']['athlete_id']='wrong'
            with Session(self.engine) as db, db.begin(), self.assertRaises(ValueError):
                import_records(db,bad)
            with Session(self.engine) as db:
                stored=db.scalar(select(PlayerGameLog).where(PlayerGameLog.player_id==mappings[0]['player_id']))
                self.assertEqual(stored.stats['fixture_correction'],1)

    def test_batch_rolls_back_prior_insert_on_identity_conflict(self):
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        from app.models import Player, PlayerGameLog
        from app.services.sports_statistics import import_records
        data,mappings=fixture('WNBA')
        rows=normalize_artifact(data,mappings,season='2025')['records']
        with Session(self.engine) as db, db.begin():
            db.add(Player(id=PLAYER,name='Invented fixture',team='Fixture',team_abbr='FIX',sport='WNBA'))
        bad=deepcopy(rows[0]); bad['external_game_id']+='second'; bad['player_id']='22222222-2222-4222-8222-222222222222'
        with Session(self.engine) as db, db.begin(), self.assertRaises(ValueError):
            import_records(db,rows+[bad])
        with Session(self.engine) as db:
            self.assertEqual(list(db.scalars(select(PlayerGameLog))),[])

    def test_research_and_search_work_without_sportsbook_offers(self):
        from sqlalchemy.orm import Session
        from app.models import Player
        from app.services.sports_statistics import import_records
        from app.database import get_db
        from app.routers.players import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from uuid import uuid4
        app=FastAPI(); app.include_router(router,prefix='/players')
        def isolated_db():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db]=isolated_db
        with TestClient(app) as client:
            for sport in ('WNBA','NHL','NFL','MLB'):
                data,mappings=fixture(sport)
                player_id=str(uuid4()); mappings[0]['player_id']=player_id
                rows=normalize_artifact(data,mappings,season=data['season'])['records']
                with Session(self.engine) as db,db.begin():
                    db.add(Player(id=player_id,name='Invented '+sport,team='Fixture',team_abbr='FIX',sport=sport))
                with Session(self.engine) as db,db.begin(): import_records(db,rows)
                response=client.get(f'/players/{player_id}/research',params={'season':data['season']})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['season_summary']['recorded_appearances'],1)
                self.assertIsNone(response.json()['selected_prop'])
                search=client.get('/players/search',params={'sport':sport}).json()
                self.assertEqual(search['players'][0]['id'],player_id)
                self.assertEqual(search['players'][0]['live_prop_count'],0)
                wrong='2025' if sport=='NHL' else '2025-26'
                self.assertEqual(client.get(f'/players/{player_id}/research',params={'season':wrong}).status_code,422)

    def test_legacy_mlb_collision_is_preserved_without_creating_duplicate(self):
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        from app.models import Player, PlayerGameLog
        from app.services.sports_statistics import import_records
        data,mappings=fixture('MLB')
        rows=normalize_artifact(data,mappings,season='2025')['records']
        with Session(self.engine) as db,db.begin():
            db.add(Player(id=PLAYER,name='Invented legacy fixture',team='Fixture',team_abbr='FIX',sport='MLB'))
        with Session(self.engine) as db,db.begin():
            db.add(PlayerGameLog(player_id=PLAYER,sport='MLB',external_game_id='1234',source='mlb_stats_api',
                game_date=datetime(2025,6,10),stats={'hits':99}))
        with Session(self.engine) as db,db.begin(),self.assertRaises(ValueError): import_records(db,rows)
        with Session(self.engine) as db:
            stored=list(db.scalars(select(PlayerGameLog)))
            self.assertEqual(len(stored),1)
            self.assertEqual(stored[0].stats,{'hits':99})
