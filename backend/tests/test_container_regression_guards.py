"""Ensure the opt-in image runner never adopts/deletes existing resources."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import container_postgres_regression as regression


class ContainerRegressionGuards(unittest.TestCase):
    def test_existing_private_artifacts_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            artifact = state / "source.dump"
            artifact.write_bytes(b"preserved fixture backup")
            with patch.object(regression, "STATE", state), patch.object(subprocess, "run") as execute:
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    regression.run("test-backend", "test-postgres")
                execute.assert_not_called()
            self.assertEqual(artifact.read_bytes(), b"preserved fixture backup")

    def test_existing_container_is_not_adopted_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def execute(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")
            with patch.object(regression, "STATE", Path(directory) / "new-run"), patch.object(subprocess, "run", side_effect=execute):
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    regression.run("test-backend", "test-postgres")
            self.assertEqual(len(calls), 1)
            self.assertIn("inspect", calls[0])
            self.assertFalse(any("rm" in args for args in calls))

    def test_existing_network_is_not_adopted_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def execute(args, **kwargs):
                calls.append(args)
                present = args[3] == "network"
                return subprocess.CompletedProcess(args, 0 if present else 1, stdout="[]", stderr="")
            with patch.object(regression, "STATE", Path(directory) / "new-run"), patch.object(subprocess, "run", side_effect=execute):
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    regression.run("test-backend", "test-postgres")
            self.assertFalse(any("create" in args or "rm" in args for args in calls))


if __name__ == "__main__":
    unittest.main()
