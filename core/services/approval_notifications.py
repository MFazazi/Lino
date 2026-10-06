"""Observe approval toasts displayed by Windows, never operate their controls.

Only recognized shell hosts and exact approval headings are accepted. A chat,
terminal, webpage, or unrelated notification mentioning approval is not enough.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
from pathlib import PureWindowsPath
import threading
import time
import unicodedata

from state import runtime

SHELL_HOSTS = {'shellexperiencehost.exe', 'shellhost.exe', 'explorer.exe'}
APPROVAL_TITLES = {
    'approbation d’autorisation', "approbation d'autorisation", 'permission approval',
    'approval required', 'approbation requise', 'autorisation requise',
}


def normalize(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split()).replace('’', "'")


def detect_approval(host: str, labels: list[str]) -> str | None:
    if host.lower() not in SHELL_HOSTS:
        return None
    values = {normalize(label) for label in labels}
    if not values.intersection({normalize(title) for title in APPROVAL_TITLES}):
        return None
    # App identity must be its own accessible label, not a mention in a message.
    if values.intersection({'chatgpt', 'codex', 'openai codex'}):
        return 'Codex'
    if values.intersection({'claude', 'claude code'}):
        return 'Claude'
    return None


def process_name(pid: int) -> str:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ''
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return PureWindowsPath(buffer.value).name.casefold()
        return ''
    finally:
        kernel.CloseHandle(handle)


class ApprovalNotifications:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.active: dict[str, float] = {}
        self.notified: dict[str, float] = {}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name='LinoWindowsNotifications')
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def observe(self, host: str, labels: list[str], now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        app = detect_approval(host, labels)
        if not app:
            return None
        # Keep only a fingerprint of the notification, never its body or command.
        fingerprint = hashlib.sha256('\n'.join(sorted(set(labels))).encode()).hexdigest()[:24]
        key = f'{app}:notification:{fingerprint}'
        first = key not in self.active
        self.active[key] = now
        runtime.upsert_external_approval({
            'id': key, 'app': app, 'title': 'Notification Windows',
            'message': f'{app} a demandé une autorisation. Ouvre ChatGPT pour la vérifier.' if app == 'Codex' else 'Claude a demandé une autorisation. Ouvre Claude pour la vérifier.',
            'detected_at': time.strftime('%H:%M:%S', time.localtime(now)),
            'source': 'visual',
        })
        if first and now - self.notified.get(key, 0) > 60:
            self.notified[key] = now
            runtime.request_ui('expand_island')
            from services.voice import voice
            voice.notify_approval(app, key)
        runtime.update(notification_monitor={
            'ready': True, 'last_scan_at': now, 'last_detection_at': now,
            'message': 'Notification de validation Windows détectée',
        })
        return key

    def expire(self, now: float):
        # Disappearance of a toast is not proof that the user answered.
        # Retain a short reminder, described as a notification, not a pending state.
        for key, last_seen in list(self.active.items()):
            if now - last_seen > 20:
                self.active.pop(key, None)
                runtime.remove_external_approval(key)
        self.notified = {k: v for k, v in self.notified.items() if now - v < 300}

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
            from pywinauto import Desktop
            desktop = Desktop(backend='uia')
        except Exception as exc:
            runtime.update(notification_monitor={'ready': False, 'message': f'Notifications Windows indisponibles : {type(exc).__name__}'})
            return
        try:
            while not self.stop_event.wait(0.35):
                now = time.time()
                try:
                    windows = desktop.windows(visible_only=True)
                    hosts = {}
                    count = 0
                    headers = 0
                    sources = 0
                    for window in windows:
                        try:
                            pid = window.element_info.process_id
                            if pid not in hosts:
                                hosts[pid] = process_name(pid)
                            host = hosts[pid]
                            if host not in SHELL_HOSTS:
                                continue
                            # Exclude Explorer folder windows; they can display arbitrary filenames.
                            if host == 'explorer.exe' and window.class_name() in {'CabinetWClass', 'ExploreWClass', 'Progman', 'WorkerW', 'Shell_TrayWnd'}:
                                continue
                            count += 1
                            descendants = window.descendants()
                            labels = [window.window_text()]
                            labels.extend(child.window_text() for child in descendants[:200] if child.is_visible())
                            values = {normalize(label) for label in labels}
                            headers += bool(values.intersection({normalize(title) for title in APPROVAL_TITLES}))
                            sources += bool(values.intersection({'chatgpt', 'codex', 'openai codex', 'claude', 'claude code'}))
                            self.observe(host, labels, now)
                        except Exception:
                            continue
                    previous = runtime.snapshot().get('notification_monitor', {})
                    runtime.update(notification_monitor={**previous, 'ready': True, 'last_scan_at': time.time(), 'shell_windows': count, 'approval_headers': headers, 'recognized_sources': sources})
                    self.expire(now)
                except Exception as exc:
                    runtime.update(notification_monitor={'ready': False, 'message': f'Lecture des notifications impossible : {type(exc).__name__}'})
        finally:
            pythoncom.CoUninitialize()


approval_notifications = ApprovalNotifications()
