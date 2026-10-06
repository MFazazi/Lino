from __future__ import annotations

from typing import Any

from config import settings
from services.voice import voice
from state import runtime
from tools.gmail import gmail_status
from user_config import get_user_setting


def connection_snapshot() -> dict[str, Any]:
    gmail = gmail_status()
    try:
        tts = voice.status() if hasattr(voice, 'status') else {'ready': True, 'backend': 'Windows'}
    except Exception as exc:
        tts = {'ready': False, 'backend': 'Windows', 'error': str(exc)}

    brave_key = str(get_user_setting('brave_search_api_key', '') or settings.brave_search_api_key or '').strip()
    n8n_url = str(get_user_setting('n8n_webhook_base_url', '') or settings.n8n_webhook_base_url or '').strip().rstrip('/')
    snapshot = runtime.snapshot()

    return {
        'gmail': {
            'connected': bool(gmail.get('connected')),
            'ready_to_connect': bool(gmail.get('ready_to_connect')),
            'needs_setup': bool(gmail.get('needs_setup')),
            'account': gmail.get('account'),
            'message': gmail.get('message', ''),
        },
        'web': {
            'connected': True,
            'mode': 'Brave Search' if brave_key else 'Automatique',
            'detail': 'Brave Search' if brave_key else 'Sans clé API',
        },
        'n8n': {
            'connected': bool(n8n_url),
            'url': n8n_url,
        },
        'phone': {
            'connected': bool(snapshot.get('android_connected')),
            'detail': 'Micro Android connecté' if snapshot.get('android_connected') else 'En attente du téléphone',
        },
        'voice': {
            'connected': bool(tts.get('ready', True)),
            'backend': tts.get('backend', 'Windows'),
        },
    }
