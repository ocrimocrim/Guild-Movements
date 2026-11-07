import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'players.json'
        self.recovery = Path(self.tmp.name) / 'buffer-recovery.json'
        self.patches = [patch.object(tracker, 'STATE_PATH', self.state),
                        patch.object(tracker, 'RECOVERY_PATH', self.recovery),
                        patch.dict(os.environ, {'GUILD_TRACKER_GIT_CHECKPOINT': '0'}),
                        patch.object(tracker, 'fetch_html', return_value='ignored')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        tracker.save_json(self.state, {'A': 'Old', 'B': '', 'Offline': 'Keep'})

    def snapshot(self, value):
        return patch.object(tracker, 'parse_players', return_value=value)

    def read_state(self):
        return json.loads(self.state.read_text())

    def test_missing_webhook_leaves_state_unchanged(self):
        with self.assertRaises(ValueError):
            tracker.run_tracker('')
        self.assertEqual(self.read_state(), {'A': 'Old', 'B': '', 'Offline': 'Keep'})

    def test_http_failure_and_partial_success_retry_only_unsent(self):
        response_ok = Mock()
        response_bad = Mock()
        response_bad.raise_for_status.side_effect = requests.HTTPError('404')
        with self.snapshot({'A': 'New', 'B': 'Guild'}), patch.object(tracker.SESSION, 'post', side_effect=[response_ok, response_bad]) as post:
            with self.assertRaises(requests.HTTPError):
                tracker.run_tracker('https://example.test/webhook')
            self.assertEqual(post.call_count, 2)
        self.assertEqual(self.read_state(), {'A': 'New', 'B': '', 'Offline': 'Keep'})
        with self.snapshot({'A': 'New', 'B': 'Guild'}), patch.object(tracker.SESSION, 'post', return_value=response_ok) as post:
            tracker.run_tracker('https://example.test/webhook')
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['json']['content'], '🟢 **B** joined **Guild**.')
        self.assertEqual(self.read_state()['Offline'], 'Keep')

    def test_main_returns_failure_without_disclosing_url(self):
        response = requests.Response()
        response.status_code = 404
        with self.snapshot({'A': 'New'}), patch.object(tracker.SESSION, 'post', return_value=response), patch.dict(os.environ, {'DISCORD_WEBHOOK_URL': 'https://example.test/secret'}), patch.object(tracker.sys, 'argv', ['tracker.py']), patch('sys.stderr') as stderr:
            self.assertEqual(tracker.main(), 1)
            self.assertNotIn('secret', str(stderr.write.call_args_list))
        self.assertEqual(self.read_state()['A'], 'Old')

    def test_replay_is_explicit_and_only_once(self):
        tracker.save_json(self.recovery, {'delivered': False, 'message': '🟢 **BUFFER** joined **Momentum**.', 'source_commit': 'a96dc4e3cd6b4ae765f92a515c10dc3e7bffaf3e'})
        bad = Mock()
        bad.raise_for_status.side_effect = requests.HTTPError('404')
        with patch.object(tracker.SESSION, 'post', return_value=bad):
            with self.assertRaises(requests.HTTPError):
                tracker.replay_buffer('url')
        self.assertFalse(json.loads(self.recovery.read_text())['delivered'])
        with patch.object(tracker.SESSION, 'post', return_value=Mock()) as post:
            tracker.replay_buffer('url')
            tracker.replay_buffer('url')
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['json']['content'], '🟢 **BUFFER** joined **Momentum**.')
        self.assertEqual(self.read_state()['Offline'], 'Keep')

    def test_checkpoint_failure_stops_before_next_post(self):
        with self.snapshot({'A': 'New', 'B': 'Guild'}), patch.object(tracker.SESSION, 'post', return_value=Mock()) as post, patch.object(tracker, 'checkpoint', side_effect=RuntimeError('push failed')):
            with self.assertRaises(RuntimeError):
                tracker.run_tracker('url')
            self.assertEqual(post.call_count, 1)

    def test_invalid_state_does_not_reset_baseline(self):
        self.state.write_text('{broken')
        with self.snapshot({'A': 'New'}), self.assertRaises(ValueError):
            tracker.run_tracker('url')
        self.assertEqual(self.state.read_text(), '{broken')

    def test_oversized_message_is_not_sent(self):
        with patch.object(tracker.SESSION, 'post') as post, self.assertRaises(ValueError):
            tracker.post_to_discord('url', ['x' * 2001])
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
