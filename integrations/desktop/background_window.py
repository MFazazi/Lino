"""Restore a recognized app only after its approval toast, without activating it.

Window leases contain handles/PIDs, not request text. Only windows restored by
Lino may be minimized again, and user activation cancels that ownership.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import time

APPS = {'chatgpt.exe': 'ChatGPT', 'codex.exe': 'Codex', 'claude.exe': 'Claude'}


def family(app):
    return 'OpenAI' if app in {'ChatGPT', 'Codex'} else app


class Windows:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

    def pid(self, hwnd):
        from ctypes import wintypes
        value = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, self.ctypes.byref(value))
        return value.value

    def valid(self, hwnd, pid):
        return bool(self.user.IsWindow(hwnd)) and self.pid(hwnd) == pid

    def minimized(self, hwnd):
        return bool(self.user.IsIconic(hwnd))

    def active(self, pid):
        return self.pid(self.user.GetForegroundWindow()) == pid

    def restore(self, hwnd):
        # Put the app behind other windows without changing size/position/focus.
        flags = 0x0001 | 0x0002 | 0x0010 | 0x4000
        if not self.user.SetWindowPos(hwnd, 1, 0, 0, 0, 0, flags):
            raise RuntimeError('Restauration en arrière-plan indisponible.')
        if not self.user.ShowWindowAsync(hwnd, 4):  # SW_SHOWNOACTIVATE
            raise RuntimeError('La fenêtre ne peut pas être restaurée.')

    def minimize(self, hwnd):
        self.user.ShowWindowAsync(hwnd, 7)  # SW_SHOWMINNOACTIVE


class BackgroundWindows:
    def __init__(self, path, windows, process_name):
        self.path = Path(path)
        self.windows = windows
        self.process_name = process_name

    @contextmanager
    def state(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as lock:
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            deadline = time.monotonic() + .7
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Relais occupé.')
                    time.sleep(.03)
            try:
                try:
                    data = json.loads(self.path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    data = {'leases': {}, 'seen': {}}
                yield data
                temp = self.path.with_suffix('.tmp')
                temp.write_text(json.dumps(data), encoding='utf-8')
                temp.replace(self.path)
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def wake(self, app, notification, desktop, now=None):
        now = time.time() if now is None else now
        with self.state() as data:
            data['seen'] = {k: v for k, v in data['seen'].items() if now - v < 300}
            if notification in data['seen']:
                return 'already_seen'
            candidates = []
            for window in desktop.windows(visible_only=False):
                pid = window.element_info.process_id
                source = APPS.get(self.process_name(pid))
                if source and family(source) == family(app) and self.windows.minimized(window.handle):
                    candidates.append((window.handle, pid, source))
            if len(candidates) != 1:
                return 'no_unique_minimized_window'
            hwnd, pid, source = candidates[0]
            if not self.windows.valid(hwnd, pid) or self.windows.active(pid):
                return 'window_changed'
            data['seen'][notification] = now
            self.windows.restore(hwnd)
            data['leases'][str(hwnd)] = {'pid': pid, 'app': source, 'at': now}
            return 'restoration_requested'

    def finish(self, hwnd):
        with self.state() as data:
            lease = data['leases'].pop(str(hwnd), None)
            if lease and self._owned(hwnd, lease) and not self.windows.active(lease['pid']):
                self.windows.minimize(hwnd)

    def _owned(self, hwnd, lease):
        return self.windows.valid(hwnd, lease['pid']) and APPS.get(self.process_name(lease['pid'])) == lease['app']

    def maintain(self, pending_apps, now=None):
        now = time.time() if now is None else now
        pending = {family(app) for app in pending_apps}
        with self.state() as data:
            for handle, lease in list(data['leases'].items()):
                hwnd = int(handle)
                if not self._owned(hwnd, lease) or self.windows.active(lease['pid']):
                    data['leases'].pop(handle)
                elif now - lease['at'] > 300 or (now - lease['at'] > 15 and family(lease['app']) not in pending):
                    self.windows.minimize(hwnd)
                    data['leases'].pop(handle)
