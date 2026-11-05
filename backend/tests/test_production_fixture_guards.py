"""Fixture routing checks only: never create an engine or connect to a DB."""
import os
import unittest
from unittest.mock import patch

from production_stack_fixture import ACKNOWLEDGEMENT, target_url


class ProductionFixtureTargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ,
            {"PROPPULSE_STAGE3_FIXTURE_ACK": ACKNOWLEDGEMENT}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_explicit_docker_source_and_restore_roles_allowed(self):
        for role in ("pp_stage3_owner", "pp_stage3_app"):
            for host, database in (("pp-stage3-db", "proppulse_test_stage3"),
                                   ("pp-stage3-restore-db", "proppulse_test_stage3_restore")):
                value = f"postgresql://{role}@{host}/{database}"
                self.assertEqual(target_url(value).database, database)

    def test_explicit_nonstandard_loopback_test_port_allowed(self):
        self.assertEqual(target_url("postgresql://pp_stage3_owner@127.0.0.1:59876/proppulse_test_stage3").port, 59876)

    def test_separate_restore_instance_source_slot_requires_bootstrap_mode(self):
        value = "postgresql://pp_stage3_owner@pp-stage3-restore-db/proppulse_test_stage3"
        with self.assertRaises(RuntimeError):
            target_url(value)
        self.assertEqual(target_url(value, allow_restore_bootstrap=True).database, "proppulse_test_stage3")

    def test_acknowledgement_required(self):
        os.environ.pop("PROPPULSE_STAGE3_FIXTURE_ACK")
        with self.assertRaisesRegex(RuntimeError, "acknowledgement"):
            target_url("postgresql://pp_stage3_owner@pp-stage3-db/proppulse_test_stage3")

    def test_development_remote_ambiguous_or_redirected_targets_rejected(self):
        for value in ("", "sqlite:///fixture.db", "postgresql://pp_stage3_owner@localhost:5432/proppulse",
                      "postgresql://pp_stage3_owner@localhost:5432/proppulse_test_stage3",
                      "postgresql://pp_stage3_owner@127.0.0.1/proppulse_test_stage3",
                      "postgresql://pp_stage3_owner@remote/proppulse_test_stage3",
                      "postgresql://pp_stage3_owner@pp-stage3-restore-db/proppulse_test_stage3",
                      "postgresql://stage3_admin@pp-stage3-db/proppulse_test_stage3",
                      "postgresql://pp_stage3_owner@pp-stage3-db/production",
                      "postgresql://pp_stage3_owner@pp-stage3-db/proppulse_test_stage3?host=remote"):
            with self.subTest(target=value), self.assertRaises(RuntimeError):
                target_url(value)

    def test_ambient_libpq_routing_overrides_rejected(self):
        for key in ("PGHOSTADDR", "PGSERVICE", "PGDATABASE", "pgpassword"):
            with self.subTest(variable=key), patch.dict(os.environ, {key: "fixture"}):
                with self.assertRaisesRegex(RuntimeError, "Ambient libpq"):
                    target_url("postgresql://pp_stage3_owner@pp-stage3-db/proppulse_test_stage3")


if __name__ == "__main__":
    unittest.main()
