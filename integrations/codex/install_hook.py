"""Run once by the user, then review the hooks in Codex. Does not grant trust."""
import json
import sys
from pathlib import Path


def merge(existing, incoming):
    hooks = existing.setdefault('hooks', {})
    for event, groups in incoming['hooks'].items():
        current = hooks.setdefault(event, [])
        for group in groups:
            if group not in current:
                current.append(group)
    return existing


if __name__ == '__main__':
    target = Path.home() / '.codex' / 'hooks.json'
    # Generate machine-specific commands locally; never ship personal hooks.
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = f"& {quote(sys.executable)} {quote(Path(__file__).with_name('lino_hook.py').resolve())}"
    incoming = {'hooks': {
        event: [{'hooks': [{'type': 'command', 'command': command,
                            'commandWindows': command, 'timeout': 3}]}]
        for event in ('PermissionRequest', 'PostToolUse', 'Stop', 'Interrupt', 'SessionEnd')
    }}
    if target.exists():
        original = target.read_text(encoding='utf-8-sig')
        existing = json.loads(original)
        backup = Path(__file__).with_name('hooks-before-lino.json')
        if not backup.exists():
            backup.write_text(original, encoding='utf-8')
    else:
        existing = {}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merge(existing, incoming), ensure_ascii=False, indent=2), encoding='utf-8')
    print('Liaison Lino installée. Dans Codex CLI, ouvrez /hooks et approuvez les hooks Lino.')
    print('Ils notifient uniquement : aucune autorisation de tâche n’est accordée automatiquement.')
