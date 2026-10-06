"""Read-only Codex lifecycle notifications produced by the local hook."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

EVENT_DIR = Path(__file__).resolve().parents[1] / '.runtime' / 'approval-events'
MAX_AGE = 3600


class ApprovalEvents:
    def __init__(self, directory: Path = EVENT_DIR):
        self.directory = directory
        self.seen: set[str] = set()
        self.pending: dict[str, dict] = {}
        self.last_event = 0.0

    def scan(self, now: float | None = None) -> dict[str, dict]:
        now = time.time() if now is None else now
        events = []
        for path in self.directory.glob('*.json'):
            try:
                if now - path.stat().st_mtime > MAX_AGE:
                    path.unlink(missing_ok=True)
                    self.seen.discard(path.name)
                    continue
                if path.name in self.seen:
                    continue
                self.seen.add(path.name)
                if path.stat().st_size > 2048:
                    continue
                event = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(event, dict) or event.get('event') not in {'PermissionRequest', 'PostToolUse', 'Stop', 'Interrupt', 'SessionEnd'}:
                    continue
                if event.get('tool') not in {'command', 'files', 'tool'}:
                    continue
                if not isinstance(event.get('order', 0), int):
                    continue
                if not all(re.fullmatch(r'[a-f0-9]{32}', event.get(k, '')) for k in ('session', 'request')):
                    continue
                stamp = float(event['timestamp'])
                if not now - MAX_AGE <= stamp <= now + 5:
                    continue
                events.append(event)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        for event in sorted(events, key=lambda e: (e['timestamp'], e.get('order', 0))):
            self.last_event = max(self.last_event, event['timestamp'])
            key = 'Codex:hook:' + event['request']
            if event['event'] == 'PermissionRequest':
                self.pending[key] = event
            elif event['event'] == 'PostToolUse':
                self.pending.pop(key, None)
            elif event['event'] in {'Stop', 'Interrupt', 'SessionEnd'}:
                self.pending = {k: v for k, v in self.pending.items() if v['session'] != event['session']}
        self.pending = {k: v for k, v in self.pending.items() if now - v['timestamp'] <= MAX_AGE}
        return dict(self.pending)
