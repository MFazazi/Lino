from __future__ import annotations

import hashlib
import re
import sys
import threading
import time
from dataclasses import dataclass
from services.approval_events import ApprovalEvents

from state import runtime

APP_HINTS = {
    'claude': 'Claude',
    'claude code': 'Claude',
    'codex': 'Codex',
    'openai codex': 'Codex',
}

CANDIDATE_WINDOW_TOKENS = (
    'claude', 'codex', 'terminal', 'powershell', 'command prompt', 'cmd',
    'visual studio code', 'cursor', 'windsurf'
)


@dataclass
class SeenApproval:
    signature: str
    last_seen: float


class ApprovalWatcher:
    """Observe visible Windows UI text for Claude/Codex approval prompts.

    This intentionally uses Windows UI Automation instead of reading private files or
    process memory. It only inspects text already exposed by visible application windows.
    """

    def __init__(self, interval: float = 1.6) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: dict[str, SeenApproval] = {}
        self._last_notified: dict[str, float] = {}
        self._events = ApprovalEvents()
        self._hook_keys: set[str] = set()

    def start(self) -> None:
        if sys.platform != 'win32' or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='LinoApprovalWatcher', daemon=True)
        self._thread.start()
        self._event_thread = threading.Thread(target=self._run_events, name='LinoCodexEvents', daemon=True)
        self._event_thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_events(self) -> None:
        while not self._stop.wait(0.4):
            try:
                self._poll_events()
            except Exception:
                runtime.set_monitor_status(False, 'Liaison Codex : lecture des événements impossible')

    def _run(self) -> None:
        try:
            from pywinauto import Desktop  # type: ignore
        except Exception as exc:
            runtime.set_monitor_status(False, f'Contrôle Claude/Codex indisponible: {exc}')
            return

        try:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
        except Exception:
            pythoncom = None  # type: ignore

        runtime.set_monitor_status(True, 'Détection visuelle active · liaison Codex à activer')
        desktop = Desktop(backend='uia')

        while not self._stop.wait(self.interval):
            now = time.time()
            seen_keys: set[str] = set()
            try:
                windows = desktop.windows(visible_only=True)
            except Exception:
                continue

            for window in windows:
                try:
                    title = (window.window_text() or '').strip()
                except Exception:
                    continue
                title_lower = title.lower()
                if title_lower and not any(token in title_lower for token in CANDIDATE_WINDOW_TOKENS):
                    continue

                text = self._window_text(window, title)
                if not text:
                    continue
                app = self._detect_app(text)
                if not app:
                    continue
                # A conversation mentioning approval is not a permission prompt.
                try:
                    buttons = [b.window_text() for b in window.descendants(control_type='Button')
                               if b.is_visible() and b.is_enabled()]
                except Exception:
                    buttons = []
                match = self._approval_match(text, buttons)
                if not match:
                    continue
                if app == 'Codex' and self._hook_keys:
                    continue

                snippet = self._snippet(text, match[0], match[1])
                signature = hashlib.sha1(f'{app}|{title}|{snippet}'.encode('utf-8', 'ignore')).hexdigest()[:16]
                key = f'{app}:{signature}'
                seen_keys.add(key)
                self._active[key] = SeenApproval(signature=signature, last_seen=now)

                payload = {
                    'id': key,
                    'app': app,
                    'title': title or app,
                    'message': self._friendly_message(app, snippet),
                    'detected_at': time.strftime('%H:%M:%S'),
                    'source': 'visual',
                }
                is_new = key not in {item.get('id') for item in runtime.snapshot().get('external_approvals', [])}
                runtime.upsert_external_approval(payload)

                if is_new and now - self._last_notified.get(key, 0) > 45:
                    self._last_notified[key] = now
                    self._notify(app, key)
                    runtime.request_ui('expand_island')

            # Remove prompts that disappeared for a few scans.
            for key, item in list(self._active.items()):
                if key not in seen_keys and now - item.last_seen > 5.0:
                    self._active.pop(key, None)
                    runtime.remove_external_approval(key)

    def _window_text(self, window, title: str) -> str:
        chunks: list[str] = [title]
        try:
            descendants = window.descendants()
        except Exception:
            descendants = []
        # Keep this bounded: terminals and IDEs can expose thousands of UIA nodes.
        for child in descendants[-180:]:
            try:
                value = (child.window_text() or '').strip()
            except Exception:
                continue
            if value and value not in chunks:
                chunks.append(value)
            if sum(len(x) for x in chunks) > 14000:
                break
        return '\n'.join(chunks)[-14000:]

    @staticmethod
    def _detect_app(text: str) -> str | None:
        lowered = text.lower()
        for token, label in APP_HINTS.items():
            if token in lowered:
                return label
        return None

    @staticmethod
    def _approval_match(text: str, buttons: list[str] | None = None) -> tuple[int, int] | None:
        buttons = [re.sub(r'\s+', ' ', b).strip().lower() for b in (buttons or [])]
        allow = re.compile(r'^(?:allow|approve|autoriser|approuver|oui|yes|run|exécuter|confirmer|confirm)(?:\s+(?:once|always|this time|une fois|toujours|pour cette session))?[.!]?$')
        deny = re.compile(r'^(?:deny|decline|reject|refuser|non|no|cancel|annuler)[.!]?$')
        if not (any(allow.fullmatch(b) for b in buttons) and any(deny.fullmatch(b) for b in buttons)):
            return None
        tail = text[-6500:]
        prompt = re.compile(r'(?:do you want to (?:proceed|continue|run|apply|allow)|would you like to (?:proceed|continue|run|apply|allow)|(?:autoriser|exécuter|appliquer|allow|run)[^\n?]{0,180}\?|(?:needs?|requires?|waiting for|awaiting)\s+(?:your\s+)?(?:approval|confirmation|permission))', re.IGNORECASE)
        match = prompt.search(tail)
        if match:
            offset = len(text) - len(tail)
            return offset + match.start(), offset + match.end()
        return None

    def _poll_events(self) -> None:
        pending = self._events.scan()
        for key in self._hook_keys - pending.keys():
            runtime.remove_external_approval(key)
        for key, event in pending.items():
            message = {'command': 'Codex attend votre validation pour exécuter une commande.',
                       'files': 'Codex attend votre validation pour modifier des fichiers.'}.get(
                           event['tool'], 'Codex attend votre validation avant de continuer.')
            runtime.upsert_external_approval({'id': key, 'app': 'Codex', 'title': 'Codex',
                'message': message, 'detected_at': time.strftime('%H:%M:%S', time.localtime(event['timestamp'])),
                'source': 'hook'})
            if key not in self._hook_keys:
                runtime.request_ui('expand_island')
                self._notify('Codex', key)
        self._hook_keys = set(pending)
        if self._events.last_event:
            runtime.set_monitor_status(True, 'Codex CLI : signal reçu · Application : notifications Windows')

    @staticmethod
    def _notify(app: str, key: str) -> None:
        from services.voice import voice
        voice.notify_approval(app, key)

    @staticmethod
    def _snippet(text: str, start: int, end: int) -> str:
        left = max(0, start - 180)
        right = min(len(text), end + 260)
        snippet = re.sub(r'\s+', ' ', text[left:right]).strip()
        return snippet[:420]

    @staticmethod
    def _friendly_message(app: str, snippet: str) -> str:
        lowered = snippet.lower()
        if 'command' in lowered or 'commande' in lowered:
            return f'{app} attend votre validation pour exécuter une commande.'
        if 'file' in lowered or 'fichier' in lowered or 'changes' in lowered or 'modif' in lowered:
            return f'{app} attend votre validation pour modifier des fichiers.'
        return f'{app} attend votre validation avant de continuer.'


approval_watcher = ApprovalWatcher()
