"""Notify Lino locally. Never approve, deny, or change a Codex tool call.

Only event identifiers and hashes are retained: no commands, transcript, or secrets.
An empty stdout and exit status 0 leave the normal Codex approval flow unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

EVENTS = {'PermissionRequest', 'PostToolUse', 'Stop', 'Interrupt', 'SessionEnd'}
EVENT_DIR = Path(__file__).resolve().parents[2] / 'core' / '.runtime' / 'approval-events'


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:32]


def event_from_payload(payload: dict) -> dict | None:
    event = payload.get('hook_event_name')
    session = payload.get('session_id')
    if event not in EVENTS or not isinstance(session, str) or not session:
        return None
    tool = payload.get('tool_name', '')
    return {
        'event': event, 'session': digest(session),
        'request': digest([session, payload.get('turn_id', ''), tool, payload.get('tool_input')]),
        'tool': 'command' if tool == 'Bash' else 'files' if tool == 'apply_patch' else 'tool',
        'timestamp': time.time(), 'order': time.perf_counter_ns(),
    }


def publish(payload: dict, directory: Path = EVENT_DIR) -> bool:
    event = event_from_payload(payload)
    if event is None:
        return False
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.tmp', dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(event, stream)
        os.replace(temporary, temporary.with_suffix('.json'))
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            publish(payload)
    except Exception:
        # Notification failures must never block work or influence permissions.
        pass


if __name__ == '__main__':
    main()
