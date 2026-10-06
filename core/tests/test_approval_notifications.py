import unittest
from unittest.mock import patch
from services.approval_notifications import ApprovalNotifications, detect_approval
from state import runtime


class NotificationTests(unittest.TestCase):
    def setUp(self):
        runtime.update(external_approvals=[])

    def tearDown(self):
        runtime.update(external_approvals=[])

    def test_user_screenshot(self):
        self.assertEqual(detect_approval('ShellExperienceHost.exe', ['ChatGPT', 'Approbation d’autorisation', 'Test de notification Lino', 'Close']), 'Codex')

    def test_rejects_chat_and_browser_content(self):
        for process in ['Codex.exe', 'ChatGPT.exe', 'chrome.exe', 'powershell.exe']:
            self.assertIsNone(detect_approval(process, ['ChatGPT', 'Approbation d’autorisation']))

    def test_rejects_nonapproval_notifications(self):
        self.assertIsNone(detect_approval('ShellExperienceHost.exe', ['ChatGPT', 'Tâche terminée']))
        self.assertIsNone(detect_approval('ShellExperienceHost.exe', ['Mail', 'Approbation d’autorisation']))
        self.assertIsNone(detect_approval('ShellExperienceHost.exe', ['ChatGPT', 'Voici un exemple : Approbation d’autorisation']))

    def test_straight_apostrophe_and_normalization(self):
        self.assertEqual(detect_approval('ShellExperienceHost.exe', ['CHATGPT', "Approbation d'autorisation"]),'Codex')

    def test_notify_once_and_remove_reminder(self):
        observer = ApprovalNotifications()
        labels=['ChatGPT','Approbation d’autorisation','Test privé']
        with patch('services.voice.voice.notify_approval') as notify:
            key=observer.observe('ShellExperienceHost.exe',labels,1000)
            observer.observe('ShellExperienceHost.exe',labels,1001)
            self.assertEqual(notify.call_count,1)
            self.assertEqual(len(runtime.snapshot()['external_approvals']),1)
            self.assertNotIn('Test privé',str(runtime.snapshot()['external_approvals']))
            observer.expire(1022)
            self.assertFalse(runtime.snapshot()['external_approvals'])
            observer.observe('ShellExperienceHost.exe',labels,1023)
            self.assertEqual(notify.call_count,1)
            observer.expire(1100)
            observer.observe('ShellExperienceHost.exe',labels,1101)
            self.assertEqual(notify.call_count,2)


if __name__ == '__main__':
    unittest.main()
