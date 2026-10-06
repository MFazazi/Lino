import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

BRIDGE = Path(__file__).resolve().parents[2] / 'integrations' / 'desktop' / 'approval_bridge.py'
if not BRIDGE.exists():
    BRIDGE = Path(__file__).with_name('approval_bridge.py')
spec = importlib.util.spec_from_file_location('relay', BRIDGE)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class Node:
    def __init__(self, text='', kind='Text', rid=1, nodes=None):
        self.text = text
        self.element_info = SimpleNamespace(process_id=42, runtime_id=[rid], control_type=kind)
        self.nodes = nodes or []
        self.visible = self.enabled = True
        self.iface_invoke = SimpleNamespace(Invoke=Mock())
    def descendants(self): return self.nodes
    def window_text(self): return self.text
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.text = Node('Autorisation demandée : lire uniquement D:\\Lino\\README.md', rid=2)
        self.allow = Node('Autoriser une fois', 'Button', 3)
        self.deny = Node('Refuser', 'Button', 4)
        self.dialog = Node(kind='Pane', nodes=[self.text, self.allow, self.deny])
    def candidate(self): return relay.describe(self.dialog, 'ChatGPT', 900)
    def test_full_request_shown(self):
        record, _, _ = self.candidate()
        self.assertEqual(record['message'], self.text.text)
        self.assertTrue(record['can_respond'])
    def test_allow_and_deny_target_exact_button(self):
        for decision, target in [('allow', self.allow), ('deny', self.deny)]:
            candidate = self.candidate()
            result = relay.respond(candidate[0]['id'], decision, lambda: [candidate])
            self.assertTrue(result['ok'])
            target.iface_invoke.Invoke.assert_called_once()
    def test_changed_request_rejected(self):
        old = self.candidate()[0]['id']
        self.text.text = 'Autorisation demandée : supprimer un autre fichier'
        with self.assertRaises(ValueError): relay.respond(old, 'allow', lambda: [self.candidate()])
        self.allow.iface_invoke.Invoke.assert_not_called()
    def test_disappeared_and_duplicate_rejected(self):
        c = self.candidate()
        for found in [[], [c, c]]:
            with self.assertRaises(ValueError): relay.respond(c[0]['id'], 'allow', lambda: found)
        self.allow.iface_invoke.Invoke.assert_not_called()
    def test_invalid_choice_rejected(self):
        with self.assertRaises(ValueError): relay.respond('id', 'always', lambda: [self.candidate()])
    def test_always_allow_not_offered(self):
        self.allow.text = 'Always allow'
        self.assertIsNone(self.candidate())
    def test_ambiguous_buttons_rejected(self):
        self.dialog.nodes.append(Node('Allow', 'Button', 8))
        self.assertIsNone(self.candidate())
    def test_disabled_or_hidden_choice_rejected(self):
        self.allow.enabled = False
        self.assertIsNone(self.candidate())
        self.allow.enabled = True
        self.deny.visible = False
        self.assertIsNone(self.candidate())
    def test_unmirrored_options_rejected(self):
        for kind in ['Edit', 'CheckBox', 'ComboBox', 'RadioButton']:
            self.dialog.nodes = [self.text, self.allow, self.deny, Node('option', kind, 8)]
            self.assertIsNone(self.candidate())
    def test_conversation_without_permission_heading_rejected(self):
        self.text.text = 'Voici une conversation ordinaire et ses boutons.'
        self.assertIsNone(self.candidate())
    def test_recreated_controls_change_identity(self):
        old = self.candidate()[0]['id']
        self.allow.element_info.runtime_id = [999]
        self.assertNotEqual(self.candidate()[0]['id'], old)
    def test_minimized_request_retains_offscreen_controls(self):
        for node in self.dialog.nodes:
            node.visible = False
        self.assertIsNone(self.candidate())
        candidate = relay.describe(self.dialog, 'ChatGPT', 900, minimized=True)
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate[0]['background'])
        relay.respond(candidate[0]['id'], 'deny', lambda: [candidate])
        self.deny.iface_invoke.Invoke.assert_called_once()
        self.allow.iface_invoke.Invoke.assert_not_called()

    def test_minimized_options_still_rejected(self):
        option = Node('option', 'CheckBox', 10)
        option.visible = False
        self.dialog.nodes.append(option)
        self.assertIsNone(relay.describe(self.dialog, 'ChatGPT', 900, minimized=True))

    def test_minimize_does_not_change_request_identity(self):
        original = self.candidate()[0]['id']
        for node in self.dialog.nodes:
            node.visible = False
        current = relay.describe(self.dialog, 'ChatGPT', 900, minimized=True)
        self.assertEqual(original, current[0]['id'])
        self.text.text = 'Autorisation demandée : une autre opération'
        changed = relay.describe(self.dialog, 'ChatGPT', 900, minimized=True)
        with self.assertRaises(ValueError):
            relay.respond(original, 'allow', lambda: [changed])
        self.allow.iface_invoke.Invoke.assert_not_called()

    def test_arbitrary_process_not_supported(self):
        for name in ['chrome.exe', 'powershell.exe', 'consent.exe', 'lino.exe']:
            self.assertNotIn(name, relay.APPS)


if __name__ == '__main__': unittest.main()
