"""Production startup guards, without providers, Docker or database connections."""
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts import production_runtime as runtime


class ProductionRuntimeTests(unittest.TestCase):
    def test_database_routing_cannot_be_overridden(self):
        base = "postgresql://pp_app:invented@db:5432/proppulse"
        for value in (base.replace("@db:", "@localhost:"), base + "?host=localhost",
                      base.replace("/proppulse", "/development"), base.replace("pp_app:", "postgres:"),
                      base.replace(":5432", ":5433"), base.replace(":5432", "")):
            with self.subTest(), patch.object(runtime, "secret", return_value=value):
                with self.assertRaisesRegex(RuntimeError, "database target"):
                    runtime.configure("serve")

    def test_serve_forces_refresh_off_and_reads_file_secrets(self):
        from app import config
        values = {"database_url": "postgresql://pp_app:invented@db:5432/proppulse", "jwt_secret": "invented-test-only"}
        with patch.dict(os.environ, {"LIVE_REFRESH_ENABLED": "true", "THE_ODDS_API_KEY": "invented"}), \
                patch.object(runtime, "secret", side_effect=values.__getitem__), \
                patch.object(config, "settings", SimpleNamespace(production=True, configuration_errors=lambda: [])):
            runtime.configure("serve")
            self.assertEqual(os.environ["LIVE_REFRESH_ENABLED"], "false")
            self.assertEqual(os.environ["THE_ODDS_API_KEY"], "")
            self.assertEqual(os.environ["JWT_SECRET"], values["jwt_secret"])

    def test_migration_uses_owner_not_application_role(self):
        with patch.object(runtime, "secret", return_value="postgresql://pp_app:invented@db:5432/proppulse"):
            with self.assertRaisesRegex(RuntimeError, "database target"):
                runtime.configure("migrate")

    def test_serve_only_trusts_one_gateway_and_does_not_migrate(self):
        with patch.object(runtime.sys, "argv", ["runtime", "serve"]), \
                patch.object(runtime, "configure"), \
                patch.dict(os.environ, {"TRUSTED_GATEWAY_IP": "10.78.0.2"}), \
                patch.object(runtime.os, "execv") as execute:
            runtime.main()
            arguments = execute.call_args.args[1]
            self.assertIn("--proxy-headers", arguments)
            self.assertEqual(arguments[arguments.index("--forwarded-allow-ips") + 1], "10.78.0.2")
            self.assertNotIn("alembic", arguments)
        for gateway in ("*", "0.0.0.0", "10.78.0.0/24"):
            with patch.object(runtime.sys, "argv", ["runtime", "serve"]), \
                    patch.object(runtime, "configure"), patch.dict(os.environ, {"TRUSTED_GATEWAY_IP": gateway}), \
                    patch.object(runtime.os, "execv") as execute:
                with self.assertRaises((ValueError, RuntimeError)):
                    runtime.main()
                execute.assert_not_called()

    def test_unknown_operation_is_rejected(self):
        with patch.object(runtime.sys, "argv", ["runtime", "refresh"]):
            with self.assertRaisesRegex(RuntimeError, "explicit"):
                runtime.main()
