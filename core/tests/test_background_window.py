import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

module = Path(__file__).with_name('background_window.py')
if not module.exists():
    module = Path(__file__).resolve().parents[2] / 'integrations/desktop/background_window.py'
spec = importlib.util.spec_from_file_location('background_window', module)
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Mock()
        self.api.active.return_value = False
        self.api.valid.return_value = True
        self.api.minimized.return_value = True
        self.desktop = Mock()
        self.window = SimpleNamespace(handle=700, element_info=SimpleNamespace(process_id=42))
        self.desktop.windows.return_value = [self.window]
        self.process = Mock(return_value='chatgpt.exe')
        self.manager = bg.BackgroundWindows(Path(self.temp.name)/'leases.json', self.api, self.process)

    def wake(self):
        return self.manager.wake('ChatGPT', 'toast-1', self.desktop, now=1000)

    def test_restore_once_and_minimize_only_owned(self):
        self.assertEqual(self.wake(), 'restoration_requested')
        self.assertEqual(self.wake(), 'already_seen')
        self.api.restore.assert_called_once_with(700)
        self.manager.finish(999)
        self.api.minimize.assert_not_called()
        self.manager.finish(700)
        self.api.minimize.assert_called_once_with(700)

    def test_do_not_restore_normal_window(self):
        self.api.minimized.return_value = False
        self.assertEqual(self.wake(), 'no_unique_minimized_window')
        self.api.restore.assert_not_called()

    def test_do_not_guess_between_windows(self):
        self.desktop.windows.return_value = [self.window, SimpleNamespace(handle=701,element_info=SimpleNamespace(process_id=42))]
        self.assertEqual(self.wake(), 'no_unique_minimized_window')
        self.api.restore.assert_not_called()

    def test_never_touch_unrelated_app(self):
        self.process.return_value = 'chrome.exe'
        self.assertEqual(self.wake(), 'no_unique_minimized_window')
        self.api.restore.assert_not_called()

    def test_user_activation_cancels_ownership(self):
        self.wake()
        self.api.active.return_value = True
        self.manager.maintain(['ChatGPT'], now=1001)
        self.api.active.return_value = False
        self.manager.finish(700)
        self.api.minimize.assert_not_called()

    def test_reused_handle_is_never_minimized(self):
        self.wake()
        self.api.valid.return_value = False
        self.manager.finish(700)
        self.api.minimize.assert_not_called()

    def test_cleanup_without_request(self):
        self.wake()
        self.manager.maintain([], now=1004)
        self.api.minimize.assert_not_called()
        self.manager.maintain([], now=1016)
        self.api.minimize.assert_called_once_with(700)

    def test_active_request_is_kept(self):
        self.wake()
        self.manager.maintain(['Codex'], now=1100)
        self.api.minimize.assert_not_called()


if __name__ == '__main__': unittest.main()
