"""Bounded executor checks: disposable PostgreSQL only, never application DB."""
from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from alembic import command
from alembic.config import Config

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Event, NBAEvidenceRecord, Player, Prop, PropBook, PlayerGameLog
from app.services import verified_event_linkage as executor
from app.services import verified_linkage_scope as scope
from app.services.event_identity import validate_event_metadata
from app.services.ingestion_control import odds_ingestion_lock
import test_ingestion_postgres as pg_fixture
from test_verified_linkage_scope import fixture


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL URL unset")
class VerifiedLinkagePostgresTests(unittest.TestCase):
    setUpClass = classmethod(pg_fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.IngestionPostgresTests.setUp(self)
        # The reviewed executor is revision-02-only. The shared fixture includes
        # newer additive storage, which does not belong to this historical DB.
        NBAEvidenceRecord.__table__.drop(self.engine)
        executor.revision02_metadata().create_all(self.engine)
        self.upgrade_fixture("20261014_02")
        self.manifest, self.evidence = fixture()
        self.reviewed = {"manifest": self.manifest, "evidence": self.evidence,
            "manifest_path": str(scope.MANIFEST_PATH), "evidence_path": str(scope.EVIDENCE_PATH),
            "manifest_file_sha256": scope.MANIFEST_FILE_SHA256,
            "evidence_file_sha256": scope.EVIDENCE_FILE_SHA256}
        self.loader = patch.object(scope, "load_reviewed_files", return_value=deepcopy(self.reviewed))
        self.mock_loader = self.loader.start()
        self.addCleanup(self.loader.stop)
        guard = patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("provider forbidden"))
        self.http = guard.start()
        self.addCleanup(guard.stop)
        with self.Session.begin() as session:
            first = self.manifest["candidates"][0]["expected"]["player"]
            session.add(Player(id=first["player_id"], name=first["player_name"], team=first["team"],
                               team_abbr=first["team_abbr"], sport=first["sport"]))
            session.flush()
            for item in self.manifest["candidates"]:
                v = item["expected"]
                session.add(Prop(id=item["prop_id"], player_id=v["player"]["player_id"],
                    prop_type=v["prop_type"], line=v["line"], odds_event_id=v["odds_event_id"],
                    odds_sport_key=v["odds_sport_key"], game_time=datetime(2026,10,20,19),
                    opponent=v["opponent"], is_home=v["is_home"]))
        self.unrelated = pg_fixture.IngestionPostgresTests.seed_selection(self)
        with self.Session.begin() as session:
            session.add(PlayerGameLog(player_id=self.unrelated["player"], sport="MLB",
                external_game_id="test-log", game_date=datetime(2026,10,1),
                stats={"hits": 1}, source="isolated"))

    def run_operation(self, execute=True, **kwargs):
        return executor.run_isolated_linkage(self.engine, execute=execute,
            approval=scope.APPROVAL_PHRASE if execute else None, **kwargs)

    def upgrade_fixture(self, target):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, target)

    def assert_untouched(self):
        with self.Session() as session:
            self.assertEqual(session.query(Event).count(), 0)
            self.assertEqual(session.query(Prop).filter(Prop.event_id.is_not(None)).count(), 0)
            self.assertEqual(session.query(Prop).count(), 11)
        self.http.assert_not_called()
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory'")).scalar(),0)

    def test_success_atomic_preserves_all_unrelated_fields_and_real_guards(self):
        result = self.run_operation()
        self.assertEqual(result["status"], "completed", result.get("rejections"))
        self.assertEqual(result["transaction_outcome"], "committed")
        self.assertEqual(result["committed"], {"events_created":1,"links_created":10})
        self.assertEqual(result["candidate_prop_ids"], sorted(scope.PROP_IDS))
        self.assertEqual(result["post_commit_verification"], "passed")
        self.assertTrue(result["lock_released"])
        self.assertEqual(result["advisory_locks_remaining"],0)
        for table in result["before"]:
            if table not in {"props","events"}:
                self.assertEqual(result["before"][table], result["post_commit"][table])
        self.assertEqual(result["before"]["props"]["without_event_id"],result["post_commit"]["props"]["without_event_id"])
        with self.Session() as session:
            event = session.query(Event).one()
            self.assertEqual(event.id,result["event_id"])
            self.assertEqual({p.id for p in event.props},scope.PROP_IDS)
            self.assertIsNone(session.get(Prop,self.unrelated["prop"]).event_id)
        # Actual migration trigger protects links even from direct SQL.
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(text("UPDATE props SET event_id=NULL WHERE id=:id"),{"id":next(iter(scope.PROP_IDS))})
        self.http.assert_not_called()

    def test_dry_run_has_only_readonly_transactions_and_no_dml(self):
        from sqlalchemy import event
        observed=[]
        @event.listens_for(self.engine,"before_cursor_execute")
        def check(connection,cursor,statement,parameters,context,many):
            verb=statement.strip().split()[0].upper()
            self.assertNotIn(verb,{"INSERT","UPDATE","DELETE","LOCK"})
            if verb=="SELECT":
                cursor.execute("SHOW transaction_read_only")
                observed.append(cursor.fetchone()[0])
        self.addCleanup(event.remove,self.engine,"before_cursor_execute",check)
        result=self.run_operation(execute=False)
        self.assertEqual(result["status"],"completed",result.get("rejections"))
        self.assertEqual(result["transaction_outcome"],"read_only_rolled_back")
        self.assertEqual(result["planned"],{"events_created":1,"links_created":10})
        self.assertEqual(result["before"],result["after"])
        self.assertTrue(observed and all(value=="on" for value in observed))
        # Remove observation hook before fixture verification opens normal sessions.
        event.remove(self.engine,"before_cursor_execute",check)
        self._cleanups.pop()
        self.assert_untouched()

    def test_repeat_requires_reviewed_uuid_and_then_is_idempotent(self):
        first=self.run_operation()
        second=self.run_operation()
        self.assertEqual(second["status"],"rejected")
        repeat=self.run_operation(expected_existing_event_id=first["event_id"])
        self.assertEqual(repeat["status"],"completed",repeat.get("rejections"))
        self.assertEqual(repeat["committed"],{"events_created":0,"links_created":0})
        self.assertEqual(repeat["existing_links_reused"],10)
        self.assertEqual(repeat["before"],repeat["after"])

    def test_missing_operator_approval_never_connects(self):
        with patch.object(self.engine,"connect") as connect:
            result=executor.run_isolated_linkage(self.engine,execute=True)
        self.assertEqual(result["rejections"],["operator_approval_required"])
        connect.assert_not_called()
        self.assert_untouched()

    def test_wrong_revision_rejects_before_writes(self):
        with self.engine.begin() as c:c.execute(text("UPDATE alembic_version SET version_num='wrong'"))
        result=self.run_operation()
        self.assertIn("revision_mismatch",result["rejections"])
        self.assert_untouched()

    def test_revision03_rejected_without_dml_or_expanding_approval(self):
        from sqlalchemy import event
        self.upgrade_fixture("20261017_03")
        writes = []
        def observe(connection, cursor, statement, *args):
            if statement.strip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}:
                writes.append(statement)
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            result = self.run_operation()
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertEqual(result["rejections"], ["revision_mismatch"])
        self.assertEqual(writes, [])
        self.assertEqual(executor.REVISION, "20261014_02")
        self.assert_untouched()

    def test_missing_candidate_rejects_atomically(self):
        with self.Session.begin() as s:s.delete(s.get(Prop, next(iter(scope.PROP_IDS))))
        result=self.run_operation()
        self.assertIn("candidate_missing",result["rejections"])
        self.assertEqual(result["committed"]["events_created"],0)
        with self.Session() as s:self.assertEqual(s.query(Event).count(),0)

    def test_changed_line_rejected(self):
        self.changed_prop("line",999.5)

    def test_changed_opponent_rejected(self):
        self.changed_prop("opponent","Other Team")

    def test_changed_side_rejected(self):
        self.changed_prop("is_home",True)

    def test_changed_schedule_rejected(self):
        self.changed_prop("game_time",datetime(2026,10,20,19,0,3))

    def test_changed_market_rejected(self):
        self.changed_prop("prop_type","rebounds")

    def changed_prop(self,field,value):
        with self.Session.begin() as s:setattr(s.get(Prop,next(iter(scope.PROP_IDS))),field,value)
        result=self.run_operation()
        self.assertEqual(result["status"],"rejected")
        self.assert_untouched()

    def test_changed_player_identity_rejected(self):
        with self.Session.begin() as s:
            prop=s.get(Prop,next(iter(scope.PROP_IDS)))
            s.get(Player,prop.player_id).name="Changed Athlete"
        result=self.run_operation()
        self.assertEqual(result["status"],"rejected")
        self.assert_untouched()

    def test_extra_related_prop_cannot_expand_scope(self):
        with self.Session.begin() as s:
            source=s.get(Prop,next(iter(scope.PROP_IDS)))
            s.add(Prop(player_id=source.player_id,prop_type="assists",line=5.5,
                odds_event_id=scope.EVENT_METADATA["provider_event_id"],
                odds_sport_key=scope.EVENT_METADATA["sport_key"]))
        result=self.run_operation()
        self.assertIn("related_scope_changed",result["rejections"])
        with self.Session() as s:self.assertEqual(s.query(Event).count(),0)

    def test_unexpected_existing_event_requires_explicit_review(self):
        with self.Session.begin() as s:s.add(Event(**validate_event_metadata(**scope.EVENT_METADATA)))
        result=self.run_operation()
        self.assertIn("unexpected_existing_event",result["rejections"])
        with self.Session() as s:self.assertEqual(s.query(Prop).filter(Prop.event_id.is_not(None)).count(),0)

    def test_approved_existing_unlinked_event_can_be_reused_without_metadata_update(self):
        with self.Session.begin() as s:
            event=Event(**validate_event_metadata(**scope.EVENT_METADATA));s.add(event);s.flush();eid=event.id
        result=self.run_operation(expected_existing_event_id=eid)
        self.assertEqual(result["status"],"completed",result.get("rejections"))
        self.assertEqual(result["committed"],{"events_created":0,"links_created":10})
        self.assertEqual(result["before"]["events"],result["after"]["events"])

    def test_conflicting_event_metadata_rejects_even_with_uuid(self):
        with self.Session.begin() as s:
            event=Event(**validate_event_metadata(**{**scope.EVENT_METADATA,"home_team":"Other Team"}))
            s.add(event);s.flush();eid=event.id
        result=self.run_operation(expected_existing_event_id=eid)
        self.assertIn("existing_event_metadata_conflict",result["rejections"])

    def test_partial_existing_link_state_requires_review(self):
        with self.Session.begin() as s:
            event=Event(**validate_event_metadata(**scope.EVENT_METADATA));s.add(event);s.flush();eid=event.id
            s.get(Prop,next(iter(scope.PROP_IDS))).event=event
        result=self.run_operation(expected_existing_event_id=eid)
        self.assertIn("partial_or_conflicting_existing_links",result["rejections"])
        with self.Session() as s:self.assertEqual(s.query(Prop).filter(Prop.event_id.is_not(None)).count(),1)

    def test_lock_contention_no_writes(self):
        with odds_ingestion_lock(self.engine) as acquired:
            self.assertTrue(acquired)
            result=self.run_operation()
        self.assertIn("ingestion_lock_held",result["rejections"])
        self.assert_untouched()

    def test_failure_after_partial_work_rolls_back_event_and_all_links(self):
        original=executor.link_prop_to_event
        calls=[]
        def failing(prop,event):
            calls.append(prop.id)
            if len(calls)==4:raise RuntimeError("deliberate isolated failure")
            original(prop,event)
        with patch.object(executor,"link_prop_to_event",side_effect=failing):result=self.run_operation()
        self.assertEqual(result["transaction_outcome"],"rolled_back")
        self.assertEqual(result["attempted"],{"events_created":1,"links_created":3})
        self.assertEqual(result["committed"],{"events_created":0,"links_created":0})
        self.assertTrue(result["lock_released"])
        self.assert_untouched()

    def test_interruption_releases_lock_and_rolls_back(self):
        with patch.object(executor,"link_prop_to_event",side_effect=KeyboardInterrupt):result=self.run_operation()
        self.assertTrue(result["interrupted"])
        self.assertTrue(result["lock_released"])
        self.assert_untouched()

    def test_file_recheck_failure_under_lock_prevents_writes(self):
        self.mock_loader.side_effect=[deepcopy(self.reviewed),ValueError("manifest_file_hash_conflict")]
        result=self.run_operation()
        self.assertEqual(result["status"],"rejected")
        self.assert_untouched()

    def test_preservation_failure_before_commit_rolls_back(self):
        with patch.object(executor,"verify_preservation",side_effect=executor.LinkageRejected("preservation_conflict")):
            result=self.run_operation()
        self.assertEqual(result["transaction_outcome"],"rolled_back")
        self.assert_untouched()

    def test_postcommit_failure_keeps_committed_counts_honest(self):
        original=executor.fingerprints
        calls=[]
        def fail_last(*args):
            calls.append(1)
            if len(calls)==3:raise RuntimeError("postcommit fixture failure")
            return original(*args)
        with patch.object(executor,"fingerprints",side_effect=fail_last):result=self.run_operation()
        self.assertEqual(result["transaction_outcome"],"committed")
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["committed"],{"events_created":1,"links_created":10})
        with self.Session() as s:self.assertEqual(s.query(Prop).filter(Prop.event_id.is_not(None)).count(),10)

    def test_write_snapshot_starts_only_after_all_table_locks(self):
        from sqlalchemy import event
        observed=[]
        @event.listens_for(self.engine,"before_cursor_execute")
        def ordering(connection,cursor,statement,parameters,context,many):
            if statement.startswith("SET TRANSACTION"):
                connection.info['bounded_write'] = "READ WRITE" in statement
                connection.info['bounded_locked'] = False
            if connection.info.get('bounded_write'):
                if statement.startswith("LOCK TABLE"):
                    connection.info['bounded_locked'] = True
                    observed.append('locked')
                if statement.lstrip().startswith("SELECT"):
                    self.assertTrue(connection.info.get('bounded_locked'))
        try:result=self.run_operation()
        finally:event.remove(self.engine,"before_cursor_execute",ordering)
        self.assertEqual(result['status'],'completed',result.get('rejections'))
        self.assertEqual(observed,['locked'])

    def test_commit_acknowledgement_failure_requires_review_even_if_server_committed(self):
        from sqlalchemy import event
        holder={}
        @event.listens_for(self.engine,'before_cursor_execute')
        def identify(connection,cursor,statement,parameters,context,many):
            if statement.startswith('SET TRANSACTION') and 'READ WRITE' in statement:
                holder['driver']=connection.connection.driver_connection
        original=self.engine.dialect.do_commit
        def lost_ack(driver):
            original(driver)
            if getattr(driver, 'driver_connection', driver) is holder.get('driver'):
                raise RuntimeError('simulated lost acknowledgement')
        try:
            with patch.object(self.engine.dialect,'do_commit',side_effect=lost_ack):result=self.run_operation()
        finally:event.remove(self.engine,'before_cursor_execute',identify)
        self.assertEqual(result['transaction_outcome'],'commit_unknown')
        self.assertEqual(result['status'],'requires_review')
        self.assertIsNone(result['committed'])
        self.assertTrue(result['lock_released'])
        with self.Session() as s:self.assertEqual(s.query(Prop).filter(Prop.event_id.is_not(None)).count(),10)

    def test_missing_relationship_trigger_blocks_execution(self):
        with self.engine.begin() as c:c.execute(text('DROP TRIGGER trg_props_event_identity ON props'))
        result=self.run_operation()
        self.assertIn('link_guard_missing',result['rejections'])
        self.assert_untouched()

    def test_commit_and_rollback_failure_cannot_report_zero_committed_with_certainty(self):
        from sqlalchemy import event
        from sqlalchemy.engine import RootTransaction
        @event.listens_for(self.engine, 'before_cursor_execute')
        def identify(connection, cursor, statement, parameters, context, many):
            if statement.startswith('SET TRANSACTION'):
                connection.info['bounded_write'] = 'READ WRITE' in statement
        original_commit, original_rollback = RootTransaction.commit, RootTransaction.rollback
        def fail_commit(transaction):
            if transaction.connection.info.get('bounded_write'):
                raise RuntimeError('isolated commit transport failure')
            return original_commit(transaction)
        def fail_rollback(transaction):
            writable = transaction.connection.info.get('bounded_write')
            original_rollback(transaction)
            if writable:
                raise RuntimeError('isolated rollback acknowledgement failure')
        try:
            with patch.object(RootTransaction, 'commit', fail_commit), \
                 patch.object(RootTransaction, 'rollback', fail_rollback):
                result = self.run_operation()
        finally:
            event.remove(self.engine, 'before_cursor_execute', identify)
        self.assertEqual(result['transaction_outcome'], 'commit_unknown')
        self.assertEqual(result['status'], 'requires_review')
        self.assertIsNone(result['committed'])
        self.assertTrue(result['lock_released'])
        self.assert_untouched()

    def test_foreign_key_rejects_nonexistent_event(self):
        with self.assertRaises(IntegrityError),self.engine.begin() as c:
            c.execute(text("UPDATE props SET event_id='00000000-0000-0000-0000-000000000999' WHERE id=:id"),
                      {'id':next(iter(scope.PROP_IDS))})
        self.assert_untouched()


class VerifiedTargetTests(unittest.TestCase):
    def test_wrong_production_url_rejected_without_connecting(self):
        for url in ("postgresql://localhost:5432/other","postgresql://remote:5432/proppulse","sqlite://",
                    "postgresql://localhost:5432/proppulse?host=remote",
                    "postgresql://localhost:5432/proppulse?dbname=other",
                    "postgresql://localhost:5432/proppulse?hostaddr=203.0.113.1"):
            engine=MagicMock(url=__import__('sqlalchemy').engine.make_url(url))
            result=executor.run_verified_linkage(engine)
            self.assertEqual(result["status"],"rejected")
            engine.connect.assert_not_called()

    def test_test_entry_refuses_development_without_connecting(self):
        engine=MagicMock(url=__import__('sqlalchemy').engine.make_url("postgresql://localhost:5432/proppulse"))
        result=executor.run_isolated_linkage(engine)
        self.assertEqual(result["status"],"rejected")
        engine.connect.assert_not_called()

    def test_live_dsn_override_is_rejected_before_application_queries(self):
        from sqlalchemy.engine import make_url
        connection=MagicMock()
        connection.connection.driver_connection.get_dsn_parameters.return_value={'dbname':'proppulse','host':'remote','port':'5432'}
        with self.assertRaisesRegex(executor.LinkageRejected,'connected_dsn_target_mismatch'):
            executor.verify_database(connection,make_url('postgresql://localhost:5432/proppulse'))
        connection.execute.assert_not_called()

    def test_actual_database_name_is_checked(self):
        from sqlalchemy.engine import make_url
        connection=MagicMock()
        connection.connection.driver_connection.get_dsn_parameters.return_value={'dbname':'proppulse','host':'localhost','port':'5432'}
        connection.execute.return_value.one.return_value=('other',5432,'public')
        with self.assertRaisesRegex(executor.LinkageRejected,'connected_database_mismatch'):
            executor.verify_database(connection,make_url('postgresql://localhost:5432/proppulse'))

    def test_service_refresh_guard_rejects_before_any_connection(self):
        from app.config import settings
        from sqlalchemy.engine import make_url
        engine=MagicMock(url=make_url('postgresql://localhost:5432/proppulse'))
        with patch.object(settings,'LIVE_REFRESH_ENABLED',True):
            result=executor.run_verified_linkage(engine)
        self.assertEqual(result['rejections'],['development_refresh_guard'])
        engine.connect.assert_not_called()
        engine.execution_options.assert_not_called()
