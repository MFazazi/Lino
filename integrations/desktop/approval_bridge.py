"""Local, user-operated approval relay. No HTTP listener or keyboard injection.

Only explicit permission dialogs from supported desktop processes are eligible.
A Windows toast is a notification, never evidence of an actionable approval.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata

APPS = {'chatgpt.exe': 'ChatGPT', 'codex.exe': 'Codex', 'claude.exe': 'Claude'}
ALLOW = {'allow', 'allow once', 'allow this time', 'approve', 'approve once',
         'autoriser', 'autoriser une fois', 'approuver', 'approuver une fois',
         'autoriser cette fois', 'autoriser une seule fois'}
DENY = {'deny', 'decline', 'reject', 'refuser', 'rejeter', 'cancel', 'annuler'}
DIAGNOSTICS = []
PROMPT = re.compile(r'permission|approval|autorisation|approbation|autoriser|approuver', re.I)


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def identity(node):
    info = node.element_info
    return [info.process_id, list(info.runtime_id)]


def describe(container, app, window_id, minimized=False):
    """Require one local choice pair and complete, bounded dialog text."""
    nodes = container.descendants()
    if len(nodes) > 100:
        DIAGNOSTICS.append({"reason": "group_too_large", "count": len(nodes)})
        return None
    # Minimized providers mark the whole window offscreen. Include all exposed
    # controls in that case, including options, so ambiguity still fails closed.
    visible = list(nodes) if minimized else [n for n in nodes if n.is_visible()]
    buttons = [n for n in visible if n.element_info.control_type == 'Button' and n.is_enabled()]
    allow = [n for n in buttons if norm(n.window_text()) in ALLOW]
    deny = [n for n in buttons if norm(n.window_text()) in DENY]
    if len(allow) != 1 or len(deny) != 1:
        DIAGNOSTICS.append({"reason": "choice_pair_missing", "allow": len(allow), "deny": len(deny)})
        return None
    # Sibling choice buttons alone are not a request: require actual prompt text.
    chunks = []
    for node in [container, *visible]:
        if node.element_info.control_type in {'Button', 'Edit'}:
            continue
        value = node.window_text().strip()
        if value and value not in chunks:
            chunks.append(value)
    message = '\n'.join(chunks)
    if not 20 <= len(message) <= 6000 or not PROMPT.search(message):
        DIAGNOSTICS.append({"reason": "request_text_missing_or_too_long"})
        return None
    # Do not operate dialogs offering editable arguments or unmirrored choices.
    if any(n.element_info.control_type in {'Edit', 'CheckBox', 'ComboBox', 'RadioButton'} for n in visible):
        DIAGNOSTICS.append({'reason': 'additional_options', 'types': sorted({n.element_info.control_type for n in visible})})
        return None
    proof = [app, window_id, identity(container), message,
             identity(allow[0]), allow[0].window_text(), identity(deny[0]), deny[0].window_text()]
    key = 'desktop:' + hashlib.sha256(json.dumps(proof, ensure_ascii=False).encode()).hexdigest()
    return {'id': key, 'app': app, 'title': app, 'message': message,
            'source': 'desktop', 'detected_at': '', 'can_respond': True,
            'allow_label': allow[0].window_text(), 'deny_label': deny[0].window_text(),
            'background': minimized, 'window_id': window_id}, allow[0], deny[0]


def scan(desktop, process_name):
    matches = {}
    for window in desktop.windows(visible_only=False):
        try:
            app = APPS.get(process_name(window.element_info.process_id))
            if not app:
                continue
            minimized = window.is_minimized()
            # Exclude hidden helper windows and closed dialogs. Only a real
            # minimized app window gets the offscreen exception.
            if not window.is_visible() and not minimized:
                continue
            DIAGNOSTICS.append({'app': app, 'reason': 'window_found', 'minimized': minimized})
            buttons = window.descendants(control_type='Button')
            labels = [b.window_text()[:90] for b in buttons if re.search(r'allow|autor|appro|refus|deny|decl|annul|cancel|yes|oui|accept|accepter|confirm|valider|continuer', b.window_text(), re.I)]
            DIAGNOSTICS.append({'reason': 'choice_labels', 'labels': labels[:20]})
            # Start at a recognized button, seek the smallest local request group.
            for button in buttons:
                if (not minimized and not button.is_visible()) or not button.is_enabled() or norm(button.window_text()) not in ALLOW:
                    continue
                parent = button.parent()
                for _ in range(8):
                    # Never use the entire conversation window as an approval dialog.
                    if identity(parent) == identity(window):
                        break
                    candidate = describe(parent, app, window.handle, minimized=minimized)
                    if candidate:
                        matches[candidate[0]['id']] = candidate
                        break
                    parent = parent.parent()
        except Exception as exc:
            DIAGNOSTICS.append({'reason': 'scan_error', 'type': type(exc).__name__})
            continue
    return list(matches.values())[:8]


def respond(request_id, decision, discover, after_response=None):
    if decision not in {'allow', 'deny'}:
        raise ValueError('Choix invalide.')
    # Always rescan at the moment of the user's click. No cached UIA references.
    matches = [m for m in discover() if m[0]['id'] == request_id]
    if len(matches) != 1:
        raise ValueError('La demande a changé ou a disparu. Rien n’a été autorisé.')
    record, allow, deny = matches[0]
    button = allow if decision == 'allow' else deny
    if (not record.get('background') and not button.is_visible()) or not button.is_enabled():
        raise ValueError('Ce choix n’est plus disponible.')
    # Invoke the exact observed button; never use Enter, focus, coordinates or retries.
    button.iface_invoke.Invoke()
    if after_response:
        try:
            after_response(record['window_id'])
        except Exception:
            pass  # A completed decision must not be reported as failed by window cleanup.
    return {'ok': True, 'message': 'Choix transmis à ' + record['app'] + '.'}


def dispatch(request, desktop, process_name, background):
    from pathlib import Path
    import time
    started = time.perf_counter()
    DIAGNOSTICS.clear()
    discover = lambda: scan(desktop, process_name)
    if request.get('action') == 'scan':
        approvals = [m[0] for m in discover()]
        # Read-only fallback for the Windows notification shown in the user's screenshot.
        from services.approval_notifications import detect_approval, SHELL_HOSTS
        for window in desktop.windows(visible_only=True):
            try:
                host = process_name(window.element_info.process_id)
                if host not in SHELL_HOSTS:
                    continue
                if host == 'explorer.exe' and window.class_name() in {'CabinetWClass', 'ExploreWClass', 'Progman', 'WorkerW', 'Shell_TrayWnd'}:
                    continue
                labels = [window.window_text()] + [n.window_text() for n in window.descendants()[:200] if n.is_visible()]
                app = detect_approval(host, labels)
                if not app:
                    continue
                if any(norm(label) == 'chatgpt' for label in labels):
                    app = 'ChatGPT'
                if any(a['app'] == app for a in approvals):
                    continue
                key = 'notification:' + hashlib.sha256(json.dumps(labels).encode()).hexdigest()
                wake = background.wake(app, key, desktop)
                DIAGNOSTICS.append({'app': app, 'reason': wake})
                approvals.append({'id': key, 'app': app, 'title': 'Notification Windows',
                                  'message': 'Une autorisation a été demandée. Les boutons de réponse ne sont pas accessibles à Lino pour cette demande.',
                                  'source': 'desktop', 'can_respond': False, 'detected_at': ''})
            except Exception:
                continue
        background.maintain([a['app'] for a in approvals if a.get('can_respond')])
        result = {'ok': True, 'approvals': approvals}
        # Diagnostic counts/types only: no request content, commands or secrets.
        import time
        diagnostics = {'at': time.time(), 'actionable': sum(bool(a.get('can_respond')) for a in approvals), 'notifications': sum(not a.get('can_respond') for a in approvals), 'checks': DIAGNOSTICS[:80]}
        target = Path(__file__).resolve().parents[2] / 'core/.runtime/desktop-relay-diagnostics.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(diagnostics), encoding='utf-8')
        if diagnostics['notifications'] or any(c.get('reason') not in {'window_found', 'choice_labels'} for c in DIAGNOSTICS) or any(c.get('labels') for c in DIAGNOSTICS):
            target.with_name('desktop-relay-last-request.json').write_text(json.dumps(diagnostics), encoding='utf-8')
    elif request.get('action') == 'respond':
        result = respond(request.get('id'), request.get('decision'), discover, after_response=background.finish)
    else:
        raise ValueError('Action inconnue.')
    result['elapsed_ms'] = round((time.perf_counter() - started) * 1000)
    return result


def main():
    import pythoncom
    import threading
    import time
    import os
    from pathlib import Path
    pythoncom.CoInitialize()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'core'))
    from services.approval_notifications import process_name
    from pywinauto import Desktop
    from background_window import BackgroundWindows, Windows
    desktop = Desktop(backend='uia')
    background = BackgroundWindows(Path(__file__).resolve().parents[2] / 'core/.runtime/desktop-window-leases.json', Windows(), process_name)
    watching = '--watch' in sys.argv
    if watching:
        # Closing Lino closes this pipe. Exit even if a UI provider is stuck.
        def parent_closed():
            sys.stdin.buffer.read()
            os._exit(0)
        threading.Thread(target=parent_closed, daemon=True).start()
    try:
        while True:
            try:
                request = {'action': 'scan'} if watching else json.loads(sys.stdin.read())
                result = dispatch(request, desktop, process_name, background)
            except Exception as exc:
                result = {'ok': False, 'message': str(exc)}
            print(json.dumps(result, ensure_ascii=True), flush=True)
            if not watching:
                break
            time.sleep(.25)
    finally:
        pythoncom.CoUninitialize()


if __name__ == '__main__':
    main()
