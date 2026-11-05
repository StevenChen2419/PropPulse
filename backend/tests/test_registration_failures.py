"""Phase 3H registration contracts and rehearsal target/process safety guards."""
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.routers import users
import rehearse_release as rehearsal


class RehearsalSafetyTests(unittest.TestCase):
    def test_inherited_routing_overrides_are_removed(self):
        self.assertEqual(rehearsal.clean_environment({"PGHOSTADDR": "remote", "PGSERVICE": "development",
            "pgpassword": "private", "DOCKER_CONTEXT": "production", "DOCKER_HOST": "tcp://remote",
            "PROPPULSE_TEST_POSTGRES_URL": "development", "PATH": "tools"}), {"PATH": "tools"})

    def test_docker_command_pins_local_endpoint(self):
        args = rehearsal.docker_args("inspect", "fixture")
        self.assertEqual(args[:2], ["docker", "--host"])
        self.assertTrue(args[2].startswith(("npipe:", "unix:")))
        self.assertEqual(args[3:], ["inspect", "fixture"])

    def test_private_server_rejects_non_rehearsal_targets(self):
        rehearsal.server_target("postgresql://rehearsal_reader@127.0.0.1:59876/proppulse_test_m3h_restore", 59876)
        for value in ("postgresql://user@localhost:5432/proppulse", "postgresql://user@remote/database",
                      "postgresql://rehearsal_reader@127.0.0.1:59877/proppulse_test_m3h_restore"):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "non-rehearsal"):
                rehearsal.server_target(value, 59876)

    def test_container_requires_exact_identity_label_port_and_tmpfs(self):
        import copy
        identity, name = "a"*64, "proppulse-test-m3h-"+"b"*12
        state = {"Id": identity, "Name": "/"+name, "Config": {"Labels": {"proppulse.rehearsal": "m3h"}},
                 "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "59876"}]}},
                 "Mounts": [], "HostConfig": {"Tmpfs": {"/var/lib/postgresql/data": "rw,noexec,nosuid,size=512m"}}}
        rehearsal.owned_container(state, identity, name, 59876)
        for key, value in (("Id", "c"*64), ("Name", "/development"), ("Config", {}),
                           ("NetworkSettings", {}), ("HostConfig", {}), ("Mounts", [{"Type": "volume"}])):
            invalid = copy.deepcopy(state)
            invalid[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "unowned"):
                rehearsal.owned_container(invalid, identity, name, 59876)

    def test_windows_cleanup_targets_only_spawned_pid_tree(self):
        proc = Mock(pid=12345)
        proc.poll.side_effect = [None, 0]
        with patch.object(rehearsal.os, "name", "nt"), patch.object(rehearsal.subprocess, "run") as run:
            rehearsal.stop_tree(proc)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])
        proc.kill.assert_not_called()
        proc.wait.assert_called_once_with(timeout=10)


class RegistrationFailureTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.query.return_value.filter.return_value.first.return_value = None
        app = FastAPI(debug=False)
        app.include_router(users.router, prefix="/auth")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        proof = self.client.get("/auth/csrf").json()["csrf_token"]
        self.headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": proof}
        self.body = {"email": "fixture@example.com", "password": "fixture-password"}

    def test_concurrent_registration_failure_rolls_back_and_is_sanitized(self):
        self.db.commit.side_effect = IntegrityError(
            "INSERT secret-sql", {"email": self.body["email"]},
            Exception("duplicate email credential-must-not-leak"))
        with patch.object(users, "hash_password", return_value="fixture-hash"), \
                patch.object(users, "create_token") as token:
            response = self.client.post("/auth/register", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Unable to register account"})
        self.db.rollback.assert_called_once_with()
        self.db.refresh.assert_not_called()
        token.assert_not_called()
        for private in (self.body["email"], self.body["password"], "secret-sql", "credential-must-not-leak"):
            self.assertNotIn(private, response.text)

    def test_existing_email_contract_is_preserved_without_writing(self):
        self.db.query.return_value.filter.return_value.first.return_value = Mock()
        with patch.object(users, "hash_password") as hash_password:
            response = self.client.post("/auth/register", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Unable to register account"})
        hash_password.assert_not_called()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

    def test_success_sets_httponly_cookie_after_committing_and_refreshing(self):
        with patch.object(users, "hash_password", return_value="fixture-hash"), \
                patch.object(users, "create_token", return_value="fixture-token") as token:
            response = self.client.post("/auth/register", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(response.cookies.get("proppulse_session"), "fixture-token")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        user = self.db.add.call_args.args[0]
        self.assertEqual(user.email, self.body["email"])
        self.assertEqual(user.hashed_password, "fixture-hash")
        self.db.commit.assert_called_once_with()
        self.db.refresh.assert_called_once_with(user)
        self.db.rollback.assert_not_called()
        token.assert_called_once_with(user.id)
