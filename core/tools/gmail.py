from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import settings
from user_config import app_data_dir, delete_user_config_keys, get_user_setting, save_user_config

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose']
DOC_EXTENSIONS = ('.pdf', '.doc', '.docx', '.rtf', '.odt')


def _legacy_credentials_path() -> Path:
    path = Path(settings.gmail_credentials_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def _legacy_token_path() -> Path:
    path = Path(settings.gmail_token_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def _token_path() -> Path:
    """Tokens live outside the repo so updates do not wipe the Gmail connection."""
    target = app_data_dir() / 'gmail_token.json'
    legacy = _legacy_token_path()
    if not target.exists() and legacy.exists() and legacy.stat().st_size > 0:
        try:
            shutil.copy2(legacy, target)
        except Exception:
            pass
    return target


def _bundled_client_config() -> dict[str, Any] | None:
    """Load a developer-bundled Desktop OAuth client if one exists.

    End users never need to know this file exists. During development Lino can also
    store the client ID/secret once through the Connections screen.
    """
    candidates = [
        Path(__file__).resolve().parents[1] / 'resources' / 'google_oauth.json',
        _legacy_credentials_path(),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding='utf-8').strip()
            if not raw:
                continue
            data = json.loads(raw)
            installed = data.get('installed')
            if isinstance(installed, dict) and installed.get('client_id'):
                return data
        except Exception:
            continue
    return None


def _client_config() -> dict[str, Any] | None:
    client_id = str(get_user_setting('google_client_id', '') or '').strip()
    client_secret = str(get_user_setting('google_client_secret', '') or '').strip()
    if client_id:
        return {
            'installed': {
                'client_id': client_id,
                'client_secret': client_secret,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
                'redirect_uris': ['http://localhost'],
            }
        }
    return _bundled_client_config()


def gmail_configure_client(client_id: str, client_secret: str = '') -> dict[str, Any]:
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or '.apps.googleusercontent.com' not in client_id:
        raise RuntimeError('Le Client ID Google semble invalide.')
    save_user_config({'google_client_id': client_id, 'google_client_secret': client_secret})
    return gmail_status()


def gmail_status() -> dict[str, Any]:
    config = _client_config()
    token = _token_path()
    result: dict[str, Any] = {
        'connected': False,
        'ready_to_connect': bool(config),
        'needs_setup': not bool(config),
        'account': get_user_setting('gmail_account', None),
        'message': '',
    }
    if not config:
        result['message'] = 'Connexion Gmail disponible après configuration OAuth de l’application.'
        return result
    if not token.exists() or token.stat().st_size == 0:
        result['message'] = 'Prêt à connecter Gmail.'
        return result
    try:
        creds = Credentials.from_authorized_user_file(str(token))
        # Health/status must remain local and instant. Refresh happens only when Gmail is actually used.
        result['connected'] = bool(creds.valid or creds.refresh_token)
        result['message'] = 'Gmail connecté.' if result['connected'] else 'La connexion Gmail doit être renouvelée.'
        return result
    except Exception:
        result['message'] = 'La connexion Gmail doit être renouvelée.'
        return result


def _get_credentials(force_consent: bool = False) -> Credentials:
    config = _client_config()
    if not config:
        raise RuntimeError('Gmail n’est pas encore configuré dans Lino. Ouvre Connexions > Gmail.')

    creds: Credentials | None = None
    token_path = _token_path()
    if token_path.exists() and not force_consent:
        try:
            creds = Credentials.from_authorized_user_file(str(token_path))
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding='utf-8')
        except Exception:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_config(config, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, prompt='consent', timeout_seconds=180)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding='utf-8')

    return creds


def gmail_connect() -> dict[str, Any]:
    creds = _get_credentials(force_consent=True)
    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId='me').execute()
    email = profile.get('emailAddress')
    if email:
        save_user_config({'gmail_account': email})
    return {'ok': True, 'email': email, 'status': gmail_status()}


def gmail_disconnect() -> dict[str, Any]:
    token = _token_path()
    if token.exists():
        try:
            token.unlink()
        except OSError:
            pass
    delete_user_config_keys('gmail_account')
    return {'ok': True, 'status': gmail_status()}


def gmail_forget_developer_client() -> dict[str, Any]:
    delete_user_config_keys('google_client_id', 'google_client_secret')
    return {'ok': True, 'status': gmail_status()}


def _service():
    return build('gmail', 'v1', credentials=_get_credentials(), cache_discovery=False)


def _header(headers: list[dict[str, str]], name: str) -> str:
    wanted = name.lower()
    for header in headers:
        if header.get('name', '').lower() == wanted:
            return header.get('value', '')
    return ''


def _attachments(payload: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def walk(part: dict[str, Any]) -> None:
        filename = part.get('filename') or ''
        body = part.get('body') or {}
        attachment_id = body.get('attachmentId')
        if filename and attachment_id:
            found.append({
                'filename': filename,
                'attachment_id': attachment_id,
                'mime_type': part.get('mimeType') or '',
            })
        for child in part.get('parts') or []:
            walk(child)

    walk(payload)
    return found


def _get_full_message(service, message_id: str) -> dict[str, Any]:
    return service.users().messages().get(userId='me', id=message_id, format='full').execute()


def gmail_search(query: str, max_results: int = 10) -> str:
    """Search the authenticated Gmail account. No address is ever required."""
    query = query.strip()
    if not query:
        return 'ERREUR: requête Gmail vide.'
    try:
        service = _service()
        listing = service.users().messages().list(
            userId='me', q=query, maxResults=max(1, min(max_results, 20))
        ).execute()
        messages = listing.get('messages', [])
        if not messages:
            return 'Aucun e-mail trouvé.'
        lines: list[str] = []
        for index, item in enumerate(messages, start=1):
            message = _get_full_message(service, item['id'])
            payload = message.get('payload') or {}
            headers = payload.get('headers') or []
            attachments = _attachments(payload)
            attachment_text = ', '.join(a['filename'] for a in attachments) or 'aucune'
            lines.append(
                f"[G{index}] message_id={message.get('id')}\n"
                f"De: {_header(headers, 'From')}\n"
                f"Sujet: {_header(headers, 'Subject')}\n"
                f"Date: {_header(headers, 'Date')}\n"
                f"Pièces jointes: {attachment_text}\n"
                f"Extrait: {message.get('snippet', '')}"
            )
        return '\n\n'.join(lines)
    except Exception as exc:
        return f'ERREUR: {exc}'


def _normalized_words(value: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9]+", ' ', value.lower())
    return [w for w in cleaned.split() if len(w) > 1]


def _attachment_score(filename: str, person_name: str) -> int:
    name = filename.lower()
    score = 0
    if 'cv' in name or 'resume' in name or 'curriculum' in name:
        score += 8
    if name.endswith('.pdf'):
        score += 5
    elif name.endswith(DOC_EXTENSIONS):
        score += 3
    for word in _normalized_words(person_name):
        if word in name:
            score += 2
    return score


def gmail_find_cv(person_name: str, max_results: int = 20) -> dict[str, Any]:
    person_name = re.sub(r'\s+', ' ', person_name).strip(' .,:;!?')
    if not person_name:
        return {'ok': False, 'error': 'Nom de la personne manquant.'}
    try:
        service = _service()
        words = _normalized_words(person_name)
        queries = [f'"{person_name}" has:attachment']
        if words:
            queries.append(' '.join(words) + ' has:attachment')
        queries.append(f'"{person_name}" (CV OR resume OR curriculum)')
        seen: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for query in queries:
            listing = service.users().messages().list(
                userId='me', q=query, maxResults=max(1, min(max_results, 50))
            ).execute()
            for item in listing.get('messages', []) or []:
                mid = item.get('id')
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                message = _get_full_message(service, mid)
                payload = message.get('payload') or {}
                headers = payload.get('headers') or []
                sender = _header(headers, 'From')
                subject = _header(headers, 'Subject')
                snippet = message.get('snippet', '')
                for attachment in _attachments(payload):
                    filename = attachment['filename']
                    score = _attachment_score(filename, person_name)
                    haystack = f'{sender} {subject} {snippet}'.lower()
                    for word in words:
                        if word in haystack:
                            score += 2
                    if 'cv' in haystack or 'resume' in haystack or 'curriculum' in haystack:
                        score += 4
                    if filename.lower().endswith(DOC_EXTENSIONS):
                        candidates.append({
                            'score': score,
                            'message_id': mid,
                            'from': sender,
                            'subject': subject,
                            'date': _header(headers, 'Date'),
                            'snippet': snippet,
                            'filename': filename,
                            'attachment_id': attachment['attachment_id'],
                            'mime_type': attachment.get('mime_type', ''),
                        })
        if not candidates:
            return {'ok': False, 'error': f'Aucun CV trouvé pour {person_name} dans la boîte Gmail connectée.'}
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return {'ok': True, **candidates[0]}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def _safe_filename(name: str) -> str:
    name = Path(name).name.strip() or 'piece-jointe'
    return re.sub(r'[^\w.()\- ]+', '_', name, flags=re.UNICODE)


def gmail_download_attachment(message_id: str, filename: str = '') -> str:
    message_id = message_id.strip()
    if not message_id:
        return 'ERREUR: message_id Gmail manquant.'
    try:
        service = _service()
        message = _get_full_message(service, message_id)
        payload = message.get('payload') or {}
        attachments = _attachments(payload)
        if not attachments:
            return 'Aucune pièce jointe trouvée dans cet e-mail.'
        selected: dict[str, str] | None = None
        wanted = filename.strip().lower()
        if wanted:
            selected = next((a for a in attachments if a['filename'].lower() == wanted), None)
            if not selected:
                selected = next((a for a in attachments if wanted in a['filename'].lower()), None)
        if not selected:
            selected = next((a for a in attachments if a['filename'].lower().endswith(DOC_EXTENSIONS)), attachments[0])
        attachment = service.users().messages().attachments().get(
            userId='me', messageId=message_id, id=selected['attachment_id']
        ).execute()
        data = attachment.get('data')
        if not data:
            return 'ERREUR: contenu de la pièce jointe vide.'
        raw = base64.urlsafe_b64decode(data.encode('ascii'))
        download_dir = Path(settings.download_dir).expanduser()
        download_dir.mkdir(parents=True, exist_ok=True)
        target = download_dir / _safe_filename(selected['filename'])
        if target.exists():
            target = download_dir / f"{target.stem}-{message_id[:8]}{target.suffix}"
        target.write_bytes(raw)
        return f'Téléchargé: {target}'
    except Exception as exc:
        return f'ERREUR: {exc}'


def _compose_service():
    token = _token_path()
    if not token.exists(): raise ValueError('Connecte Gmail dans Connexions.')
    saved=json.loads(token.read_text(encoding='utf-8'))
    if 'https://www.googleapis.com/auth/gmail.compose' not in saved.get('scopes', []):
        raise ValueError('Reconnecte Gmail dans Connexions pour autoriser les brouillons et les envois.')
    return _service()


def gmail_create_draft(to: str, subject: str, body: str) -> dict:
    from email.message import EmailMessage
    from email.utils import parseaddr
    if not parseaddr(to)[1] or '@' not in parseaddr(to)[1] or any(c in to+subject for c in '\r\n'):
        raise ValueError('Destinataire ou objet invalide.')
    message=EmailMessage();message['To']=to;message['Subject']=subject;message.set_content(body)
    raw=base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
    result=_compose_service().users().drafts().create(userId='me',body={'message':{'raw':raw}}).execute()
    return {'draft_id':result['id'],'to':to,'subject':subject,'sent':False}


def gmail_send_message(to: str, subject: str, body: str) -> dict:
    from email.message import EmailMessage
    from email.utils import parseaddr
    if not parseaddr(to)[1] or '@' not in parseaddr(to)[1] or any(c in to+subject for c in '\r\n'):
        raise ValueError('Destinataire ou objet invalide.')
    message=EmailMessage();message['To']=to;message['Subject']=subject;message.set_content(body)
    raw=base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
    result=_compose_service().users().messages().send(userId='me',body={'raw':raw}).execute()
    return {'message_id':result['id'],'sent':True}


def gmail_read_message(message_id: str) -> dict:
    data=_get_full_message(_service(),message_id)
    payload=data.get('payload',{}); parts=[]; html=[]
    def walk(part):
        raw=part.get('body',{}).get('data')
        if raw and part.get('mimeType') == 'text/plain':
            parts.append(base64.urlsafe_b64decode(raw+'===').decode('utf-8',errors='replace'))
        if raw and part.get('mimeType') == 'text/html':
            from bs4 import BeautifulSoup
            html.append(BeautifulSoup(base64.urlsafe_b64decode(raw+'===').decode('utf-8',errors='replace'),'html.parser').get_text(' ',strip=True))
        for child in part.get('parts',[]): walk(child)
    walk(payload)
    text='\n'.join(parts or html) or data.get('snippet','')
    return {'message_id':data['id'],'subject':_header(payload.get('headers',[]),'Subject'),'text':text[:30000],'truncated':len(text)>30000}

