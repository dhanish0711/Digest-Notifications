"""
tests/test_digest_notifications.py

Consolidated test suite for Digest Notifications.
Contains key integration and unit tests (max 15 tests, no forbidden names or calendar generator checks).

Run with:
    python -m pytest tests/ -v
  or
    python tests/test_digest_notifications.py
"""

import os
import sys
import json
import datetime
import unittest
from unittest.mock import MagicMock

# Path setup
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
sys.path.insert(0, os.path.abspath(SRC_DIR))

from models import DigestFrequency, DigestPayload, DigestRecipient, InterviewEvent
from digest_builder import build_digest, group_interviews_by_date
from renderer import render_digest_html, render_digest_text
from sender import send_digest_for_recipient
from digest import get_upcoming_interviews, generate_digest_html_output, generate_all_outputs


def _make_recipient(freq=DigestFrequency.DAILY):
    return DigestRecipient(
        user_id="u-test-001",
        email="recruiter@example.com",
        display_name="Recruiter",
        frequency=freq
    )


def _make_event(interview_id="iv-001", candidate="Alex Rivera", role="Frontend Engineer",
                interviewer="Sarah Connor", dt=None):
    return InterviewEvent(
        interview_id=interview_id,
        candidate_name=candidate,
        role_title=role,
        interviewer_name=interviewer,
        scheduled_at=dt or datetime.datetime(2026, 7, 1, 10, 0)
    )


class TestDigestNotifications(unittest.TestCase):
    
    # ── 1. Model Tests ──
    def test_event_date_key_and_display(self):
        ev = _make_event(dt=datetime.datetime(2026, 7, 4, 14, 30))
        self.assertEqual(ev.date_key, "2026-07-04")
        self.assertIn("14:30", ev.scheduled_at.time().isoformat())

    def test_payload_total_count(self):
        recipient = _make_recipient()
        events = [_make_event("iv-1"), _make_event("iv-2")]
        payload = build_digest(recipient, events)
        self.assertEqual(payload.total_count, 2)

    # ── 2. Builder Tests ──
    def test_group_interviews_by_date(self):
        events = [
            _make_event("iv-1", dt=datetime.datetime(2026, 7, 1, 15, 0)),
            _make_event("iv-2", dt=datetime.datetime(2026, 7, 1, 9, 0)),
            _make_event("iv-3", dt=datetime.datetime(2026, 7, 2, 10, 0))
        ]
        grouped = group_interviews_by_date(events)
        self.assertEqual(list(grouped.keys()), ["2026-07-01", "2026-07-02"])
        # Verify chronological sorting within the day
        self.assertEqual(grouped["2026-07-01"][0].interview_id, "iv-2")

    # ── 3. Renderer Tests ──
    def test_html_and_text_rendering(self):
        recipient = _make_recipient()
        events = [_make_event(candidate="Jordan Smith")]
        payload = build_digest(recipient, events)
        
        # Test HTML Renderer
        html = render_digest_html(payload, unsubscribe_url="http://test.com/unsub")
        self.assertIn("Jordan Smith", html)
        self.assertIn("http://test.com/unsub", html)
        
        # Test Text Renderer
        txt = render_digest_text(payload, unsubscribe_url="http://test.com/unsub")
        self.assertIn("Jordan Smith", txt)
        self.assertIn("http://test.com/unsub", txt)

    # ── 4. Sender Tests ──
    def test_send_digest_skips_when_empty(self):
        sender = MagicMock()
        result = send_digest_for_recipient(
            recipient=_make_recipient(),
            interviews=[],
            email_sender=sender,
            unsubscribe_base_url="https://orchestrator.example.com"
        )
        self.assertEqual(result["status"], "skipped")
        sender.send_html_email.assert_not_called()

    def test_send_digest_success(self):
        sender = MagicMock()
        sender.send_html_email.return_value = {"status": "sent", "provider": "mock"}
        result = send_digest_for_recipient(
            recipient=_make_recipient(),
            interviews=[_make_event()],
            email_sender=sender,
            unsubscribe_base_url="https://orchestrator.example.com"
        )
        self.assertEqual(result["status"], "sent")
        sender.send_html_email.assert_called_once()

    # ── 5. Engine & Spec Compliance Tests ──
    def test_upcoming_interviews_cap_at_five(self):
        # get_upcoming_interviews must limit results to the configured batch limit (default 5)
        events = get_upcoming_interviews("2026-06-01")
        self.assertLessEqual(len(events), 5)

    def test_generate_digest_html_output(self):
        html, count, date_range = generate_digest_html_output("daily", "2026-06-27")
        self.assertIn("Daily Digest", html)
        self.assertGreaterEqual(count, 0)

    def test_empty_digest_suppression(self):
        result = generate_all_outputs("daily", "2099-01-01")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_upcoming_interviews")

    def test_output_files_generated(self):
        result = generate_all_outputs("daily", "2026-06-27")
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["output_html"]))
        self.assertTrue(os.path.exists(result["output_text"]))


if __name__ == '__main__':
    unittest.main()
