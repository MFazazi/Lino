from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any


class RuntimeState:
    def __init__(self) -> None:
        self._lock = RLock()
        self._data: dict[str, Any] = {
            'status': 'ready',
            'status_label': 'En veille',
            'transcript': '',
            'answer': '',
            'actions': [],
            'sources': [],
            'external_approvals': [],
            'approval_monitor': {'ready': False, 'message': 'Démarrage…'},
            'android_connected': False,
            'awake': False,
            'ui_event': 'none',
            'ui_event_id': 0,
            'updated_at': self._now(),
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._data)
            data['actions'] = [dict(item) for item in self._data.get('actions', [])]
            data['sources'] = [dict(item) for item in self._data.get('sources', [])]
            data['external_approvals'] = [dict(item) for item in self._data.get('external_approvals', [])]
            data['approval_monitor'] = dict(self._data.get('approval_monitor', {}))
            return data

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._data.update(kwargs)
            self._data['updated_at'] = self._now()

    def request_ui(self, event: str) -> None:
        with self._lock:
            self._data['ui_event'] = event
            self._data['ui_event_id'] = int(self._data.get('ui_event_id', 0)) + 1
            self._data['updated_at'] = self._now()

    def set_monitor_status(self, ready: bool, message: str) -> None:
        self.update(approval_monitor={'ready': ready, 'message': message})

    def upsert_external_approval(self, payload: dict[str, Any]) -> None:
        with self._lock:
            items = list(self._data.get('external_approvals', []))
            existing = next((item for item in items if item.get('id') == payload.get('id')), None)
            if existing:
                existing.update(payload)
            else:
                items.insert(0, payload)
            self._data['external_approvals'] = items[:8]
            self._data['updated_at'] = self._now()

    def remove_external_approval(self, approval_id: str) -> None:
        with self._lock:
            self._data['external_approvals'] = [
                item for item in self._data.get('external_approvals', []) if item.get('id') != approval_id
            ]
            self._data['updated_at'] = self._now()

    def wake(self, transcript: str = '', answer: str = '') -> None:
        with self._lock:
            self._data.update({
                'awake': True,
                'status': 'ready',
                'status_label': 'Prêt',
                'transcript': transcript,
                'answer': answer,
                'actions': [],
                'sources': [],
                'android_connected': True,
            })
            self._data['ui_event'] = 'expand_island'
            self._data['ui_event_id'] = int(self._data.get('ui_event_id', 0)) + 1
            self._data['updated_at'] = self._now()

    def sleep(self) -> None:
        with self._lock:
            self._data.update({
                'awake': False,
                'status': 'ready',
                'status_label': 'En veille',
                'transcript': '',
                'answer': '',
                'actions': [],
                'sources': [],
            })
            self._data['ui_event'] = 'compact_island'
            self._data['ui_event_id'] = int(self._data.get('ui_event_id', 0)) + 1
            self._data['updated_at'] = self._now()

    def action(self, action_id: str, label: str, detail: str = '', state: str = 'running', tool: str = 'assistant') -> None:
        with self._lock:
            actions = list(self._data.get('actions', []))
            existing = next((a for a in actions if a['id'] == action_id), None)
            payload = {'id': action_id, 'label': label, 'detail': detail, 'state': state, 'tool': tool}
            if existing:
                existing.update(payload)
            else:
                actions.append(payload)
            self._data['actions'] = actions[-12:]
            self._data['updated_at'] = self._now()

    def reset_task(self, transcript: str) -> None:
        self.update(
            awake=True,
            status='thinking',
            status_label='Analyse en cours',
            transcript=transcript,
            answer='',
            actions=[],
            sources=[],
        )


runtime = RuntimeState()
