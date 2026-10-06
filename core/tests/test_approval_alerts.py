import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import queue
import threading

from services.approval_events import ApprovalEvents
from services.approval_watcher import ApprovalWatcher
from state import runtime

spec = importlib.util.spec_from_file_location('lino_hook', Path(__file__).resolve().parents[2] / 'integrations/codex/lino_hook.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.events = ApprovalEvents(self.directory)
        runtime.update(external_approvals=[])

    def tearDown(self):
        self.tmp.cleanup()
        runtime.update(external_approvals=[])

    def send(self, event, session='chat-1', command='echo PRIVATE', turn='turn-1'):
        return hook.publish({'hook_event_name': event, 'session_id': session, 'turn_id': turn,
                             'tool_name': 'Bash', 'tool_input': {'command': command}}, self.directory)

    def test_exact_request_is_cleared_by_completion(self):
        self.send('PermissionRequest')
        self.assertEqual(len(self.events.scan()), 1)
        self.send('PostToolUse', command='unrelated')
        self.assertEqual(len(self.events.scan()), 1)
        self.send('PostToolUse')
        self.assertFalse(self.events.scan())

    def test_no_commands_or_session_names_stored(self):
        self.send('PermissionRequest')
        text = next(self.directory.glob('*.json')).read_text()
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('chat-1', text)

    def test_duplicate_prompt_notifies_once(self):
        watcher = ApprovalWatcher()
        watcher._events = self.events
        with patch.object(watcher, '_notify') as notify:
            self.send('PermissionRequest')
            watcher._poll_events()
            self.send('PermissionRequest')
            watcher._poll_events()
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(len(runtime.snapshot()['external_approvals']), 1)
            self.send('PostToolUse')
            watcher._poll_events()
            self.assertFalse(runtime.snapshot()['external_approvals'])

    def test_sessions_are_isolated_and_replay_has_no_stale_alert(self):
        self.send('PermissionRequest')
        self.send('PermissionRequest', session='chat-2')
        self.send('Interrupt')
        pending = self.events.scan()
        self.assertEqual(len(pending), 1)
        self.assertEqual(next(iter(pending.values()))['session'], hook.digest('chat-2'))
        self.send('Stop', session='chat-2')
        self.assertFalse(ApprovalEvents(self.directory).scan())

    def test_events_with_same_windows_wall_clock_tick_keep_order(self):
        with patch.object(hook.time, 'time', return_value=time.time()):
            self.send('PermissionRequest')
            self.send('PostToolUse')
        self.assertFalse(self.events.scan())

    def test_no_alert_from_discussion_or_disabled_controls(self):
        discussion = 'Codex : comment autoriser une commande ?'
        self.assertIsNone(ApprovalWatcher._approval_match(discussion))
        self.assertIsNone(ApprovalWatcher._approval_match('Would you like to run this command?', ['Copy', 'Send']))
        self.assertIsNone(ApprovalWatcher._approval_match('Codex supports approval workflows', ['Allow', 'Deny']))

    def test_explicit_prompt_with_controls(self):
        self.assertIsNotNone(ApprovalWatcher._approval_match('Codex: Would you like to run this command?', ['Allow once', 'Deny']))
        self.assertIsNotNone(ApprovalWatcher._approval_match('Claude: Autoriser cette commande ?', ['Autoriser', 'Refuser']))

    def test_invalid_and_expired_events_ignored(self):
        (self.directory/'invalid.json').write_text('{}')
        (self.directory/'missing-event.json').write_text(json.dumps({'session':'a'*32,'request':'b'*32,'timestamp':time.time()}))
        (self.directory/'wrong-shape.json').write_text('[]')
        self.assertFalse(self.events.scan())
        self.assertFalse(hook.publish({'hook_event_name': 'random'}, self.directory))
        self.send('PermissionRequest')
        self.assertFalse(self.events.scan(now=time.time()+3700))

    def test_installer_preserves_existing_hooks_and_is_idempotent(self):
        installer_spec = importlib.util.spec_from_file_location('install_hook', Path(__file__).resolve().parents[2] / 'integrations/codex/install_hook.py')
        installer = importlib.util.module_from_spec(installer_spec)
        installer_spec.loader.exec_module(installer)
        existing = {'description':'user config', 'hooks':{'Stop':[{'hooks':[{'command':'existing command'}]}]}}
        incoming = {'hooks':{'Stop':[{'hooks':[{'command':'lino command'}]}]}}
        merged = installer.merge(existing, incoming)
        installer.merge(merged, incoming)
        self.assertEqual(merged['description'],'user config')
        self.assertEqual(len(merged['hooks']['Stop']),2)
        self.assertEqual(merged['hooks']['Stop'][0]['hooks'][0]['command'],'existing command')


class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from services.voice import VoiceService
        cls.VoiceService = VoiceService

    def make_voice(self):
        v = self.VoiceService.__new__(self.VoiceService)
        v._queue = queue.Queue()
        v._muted = False
        v._last_delivery = None
        v._stop_event = threading.Event()
        v._ready = threading.Event()
        v._player = None
        v._speaker = None
        v._last_error = ''
        return v

    def test_muted_alert_not_queued(self):
        v = self.make_voice()
        v.set_muted(True)
        v.notify_approval('Codex','x')
        self.assertTrue(v._queue.empty())
        self.assertTrue(runtime.snapshot()['voice_muted'])
        v.set_muted(False)
        v.notify_approval('Codex','x')
        self.assertEqual(v._queue.get(), ('','x'))

    def test_resolved_alert_not_spoken(self):
        v = self.make_voice()
        runtime.update(external_approvals=[])
        v.notify_approval('Codex','resolved')
        v._queue.put(None)
        with patch.object(v,'_init_sapi',return_value=object()), patch.object(v,'_edge_available',return_value=False), patch.object(v,'_speak_sapi') as speak:
            v._worker()
            speak.assert_not_called()

    def test_alert_uses_sound_without_speech_or_changing_task_state(self):
        v = self.make_voice()
        runtime.update(external_approvals=[{'id':'pending'}],status='thinking')
        v.notify_approval('Codex','pending')
        v._queue.put(None)
        with patch.object(v,'_init_sapi',return_value=object()), patch.object(v,'_edge_available',return_value=True), patch.object(v,'_speak_sapi',return_value=True) as speak, patch.object(v,'_speak_edge') as edge, patch('winsound.MessageBeep') as sound:
            v._worker()
            speak.assert_not_called()
            sound.assert_called_once()
            edge.assert_not_called()
        self.assertEqual(runtime.snapshot()['status'],'thinking')
        runtime.update(external_approvals=[],status='ready')


if __name__ == '__main__':
    unittest.main()
