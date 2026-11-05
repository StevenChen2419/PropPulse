import unittest
from app.services.live_refresh_service import due


class RefreshScheduleTests(unittest.TestCase):
    def test_first_start_is_due(self):
        self.assertTrue(due({}, 900, 2000))

    def test_restart_does_not_repeat_recent_refresh(self):
        self.assertFalse(due({"finished_epoch": 1950}, 900, 2000))

    def test_refresh_becomes_due_at_interval(self):
        self.assertTrue(due({"finished_epoch": 1100}, 900, 2000))

    def test_interrupted_refresh_retries_after_restart(self):
        self.assertTrue(due({"status": "interrupted", "finished_epoch": 1999}, 900, 2000))
