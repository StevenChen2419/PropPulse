"""Local control safety checks; no Docker processes, databases or providers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import production_stack_control as control


class ProductionControlGuards(unittest.TestCase):
    def test_cleanup_handles_partial_startup_and_never_selects_other_resources(self):
        calls = []
        def fake_docker(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("container", "ls"):
                return "pp-stage3-api-a\nunrelated-db\n"
            if args[:2] == ("network", "ls"):
                return "pp-stage3-private\nunrelated-network\n"
            if args[1] == "inspect":
                return json.dumps([{"Config": {"Labels": {"proppulse.task": "security-stage3"}},
                    "Labels": {"proppulse.task": "security-stage3"}}])
            return ""
        with patch.object(control, "docker", side_effect=fake_docker):
            control.cleanup()
        removals = [args for args in calls if args[0] == "rm" or args[:2] == ("network", "rm")]
        self.assertEqual(removals, [("rm", "-f", "pp-stage3-api-a"), ("network", "rm", "pp-stage3-private")])

    def test_foreign_named_resource_prevents_any_removal(self):
        calls = []
        def fake_docker(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("container", "ls"):
                return "pp-stage3-api-a\npp-stage3-db"
            if args[:2] == ("network", "ls"):
                return ""
            return json.dumps([{"Config": {"Labels": {"proppulse.task":
                "security-stage3" if args[-1] == "pp-stage3-api-a" else "another-task"}}}])
        with patch.object(control, "docker", side_effect=fake_docker):
            with self.assertRaisesRegex(RuntimeError, "unowned"):
                control.cleanup()
        self.assertFalse(any(args[0] == "rm" for args in calls))

    def test_prepare_refuses_to_replace_existing_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            private = state / "secrets.json"
            private.write_text("preserved test state")
            with patch.object(control, "STATE", state):
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    control.prepare()
            self.assertEqual(private.read_text(), "preserved test state")
            self.assertEqual([p.name for p in state.iterdir()], ["secrets.json"])


if __name__ == "__main__":
    unittest.main()
