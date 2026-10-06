from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from connections import connection_snapshot
from services.google_mcp import google_mcp
from services.mcp_connections import mcp_connections
from mcp_routes import router as mcp_router
from personal_routes import router as personal_router
from services.stripe_monitor import stripe_monitor
from services.agent import agent
from services.approval_watcher import approval_watcher
from services.approval_notifications import approval_notifications
from services.transcription import transcribe_file
from services.voice import voice
from state import runtime
from tools.gmail import gmail_configure_client, gmail_connect, gmail_disconnect, gmail_status
from tools.web import search_web, web_mode
from tools.windows import open_application, open_path, open_url, search_file_paths
from user_config import delete_user_config_keys, get_user_setting, save_user_config

@asynccontextmanager
async def lifespan(_app: FastAPI):
    approval_watcher.start()
    approval_notifications.start()
    await mcp_connections.start()
    await stripe_monitor.start()
    try:
        async with google_mcp.session_manager.run():
            yield
    finally:
        approval_watcher.stop()
        approval_notifications.stop()
        await stripe_monitor.stop()
        await mcp_connections.stop()


app = FastAPI(title='Lino Core', version='0.2.4', lifespan=lifespan)
app.include_router(mcp_router)
app.include_router(personal_router)
app.mount('/google-mcp', google_mcp.streamable_http_app())

@app.middleware('http')
async def protect_google_mcp(request, call_next):
    if request.url.path.startswith('/google-mcp'):
        from mcp_routes import local
        from fastapi.responses import JSONResponse
        try: local(request)
        except HTTPException: return JSONResponse({'detail':'Accès local uniquement.'},status_code=403)
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

def _spoken_answer(answer: str) -> str:
    # Links and code remain readable in the interface, not recited by the voice.
    text = _strip_source_markers(answer)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*#`]+', '', text).strip()
    if len(text) > 650:
        cut = text.rfind('.', 0, 550)
        text = text[:cut+1] if cut > 100 else text[:500].rsplit(' ',1)[0] + '…'
        text += ' La suite est affichée dans Lino.'
    return text


WAKE_RE = re.compile(r"^\s*(?:bonjour|salut|hey|ok)\s*[,!\- ]*\s*lino\b[\s,!.;:\-]*", re.IGNORECASE)
SLEEP_RE = re.compile(r"\b(?:au revoir|bonne nuit|dors|endors-toi|mets-toi en veille|veille)\s+lino\b", re.IGNORECASE)
GREETING = "Bonjour boss, que dois-je faire pour toi aujourd'hui ?"


class ChatRequest(BaseModel):
    message: str
    speak: bool = True


class ListeningRequest(BaseModel):
    listening: bool = True


class VoiceMuteRequest(BaseModel):
    muted: bool


class VoiceTestRequest(BaseModel):
    text: str = 'Bonjour, je suis Lino.'


class QueryRequest(BaseModel):
    query: str


class PathRequest(BaseModel):
    path: str


class UrlRequest(BaseModel):
    url: str


class AppRequest(BaseModel):
    app: str


class GmailConfigureRequest(BaseModel):
    client_id: str
    client_secret: str = ''


class N8nConfigureRequest(BaseModel):
    url: str


class WebConfigureRequest(BaseModel):
    brave_api_key: str = ''


def _safe_health_component(name: str, func) -> dict:
    """Optional integrations must never make the whole Core look offline."""
    try:
        value = func()
        if isinstance(value, dict):
            return value
        return {'available': True, 'value': value}
    except Exception as exc:
        return {'available': False, 'error': f'{name}: {exc}'}


@app.get('/health')
def health() -> dict:
    # /health is a liveness endpoint used by Android. It MUST stay HTTP 200
    # while FastAPI itself is alive, even if Gmail/TTS diagnostics have a problem.
    try:
        snapshot = runtime.snapshot()
    except Exception:
        snapshot = {}

    gmail = _safe_health_component('gmail', gmail_status)
    tts_status = getattr(voice, 'status', None)
    if callable(tts_status):
        tts = _safe_health_component('tts', tts_status)
    else:
        tts = {'available': True, 'backend': 'legacy', 'ready': True}

    return {
        'ok': True,
        'version': '0.2.4',
        'model': settings.lino_model,
        'web_enabled': True,
        'web_mode': web_mode(),
        'gmail': gmail,
        'tts': tts,
        'awake': bool(snapshot.get('awake', False)),
        'android_connected': bool(snapshot.get('android_connected', False)),
        'approval_monitor': snapshot.get('approval_monitor', {}),
        'external_approvals': snapshot.get('external_approvals', []),
    }


@app.get('/connections')
def connections() -> dict:
    return {'ok': True, **connection_snapshot()}


@app.post('/connections/gmail/configure')
def connections_gmail_configure(body: GmailConfigureRequest) -> dict:
    try:
        status = gmail_configure_client(body.client_id, body.client_secret)
        return {'ok': True, 'gmail': status}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post('/connections/gmail/connect')
async def connections_gmail_connect() -> dict:
    try:
        # OAuth opens the system browser and may wait for the user, so never block FastAPI's event loop.
        result = await asyncio.to_thread(gmail_connect)
        return result
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post('/connections/gmail/disconnect')
def connections_gmail_disconnect() -> dict:
    return gmail_disconnect()


@app.post('/connections/n8n')
def connections_n8n(body: N8nConfigureRequest) -> dict:
    url = body.url.strip().rstrip('/')
    if url and not url.startswith(('http://', 'https://')):
        raise HTTPException(400, 'Entre une adresse n8n valide, par exemple https://n8n.exemple.com')
    if url:
        save_user_config({'n8n_webhook_base_url': url})
    else:
        delete_user_config_keys('n8n_webhook_base_url')
    return {'ok': True, **connection_snapshot()}


@app.post('/connections/web')
def connections_web(body: WebConfigureRequest) -> dict:
    key = body.brave_api_key.strip()
    if key:
        save_user_config({'brave_search_api_key': key})
    else:
        delete_user_config_keys('brave_search_api_key')
    return {'ok': True, **connection_snapshot()}


@app.get('/state')
def state() -> dict:
    return runtime.snapshot()


@app.post('/state/listening')
def state_listening(body: ListeningRequest) -> dict:
    snapshot = runtime.snapshot()
    runtime.update(
        status='listening' if body.listening else 'ready',
        status_label="J'écoute" if body.listening else ('Prêt' if snapshot['awake'] else 'En veille'),
        android_connected=True,
    )
    return {'ok': True, **runtime.snapshot()}


@app.post('/ui/show')
def ui_show() -> dict:
    runtime.update(awake=True)
    if runtime.snapshot().get('status') == 'ready':
        runtime.update(status_label='Prêt')
    runtime.request_ui('expand_island')
    return {'ok': True, **runtime.snapshot()}


@app.post('/ui/sleep')
def ui_sleep() -> dict:
    voice.stop()
    runtime.sleep()
    return {'ok': True, **runtime.snapshot()}


@app.post('/chat')
async def chat(body: ChatRequest) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(400, 'Message vide')

    if SLEEP_RE.search(message):
        answer = "À tout à l'heure boss."
        runtime.update(transcript=message, answer=answer)
        voice.speak(answer)
        runtime.sleep()
        return {'answer': answer, 'actions': [], 'sources': []}

    runtime.update(awake=True)
    try:
        answer = await agent.run(message)
    except Exception as exc:
        runtime.update(status='error', status_label='Erreur', answer=str(exc))
        raise HTTPException(500, str(exc)) from exc
    if body.speak:
        voice.speak(_spoken_answer(answer))
    snapshot = runtime.snapshot()
    return {'answer': answer, 'actions': snapshot['actions'], 'sources': snapshot['sources']}


@app.post('/transcribe')
async def transcribe(
    file: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    speak: bool = True,
) -> dict:
    """Receive Android audio, detect Lino wake phrase, then run the agent.

    The compact island remains visible while Lino sleeps. Saying "Bonjour Lino"
    wakes the assistant, speaks the greeting on the PC and asks the same Tauri window
    to open via the shared runtime state.
    """
    upload = file or audio
    if upload is None:
        raise HTTPException(400, 'Fichier audio manquant (champ multipart `file` ou `audio`).')

    suffix = Path(upload.filename or 'audio.webm').suffix or '.webm'
    runtime.update(status='thinking', status_label='Transcription en cours', android_connected=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = Path(tmp.name)
            while chunk := await upload.read(1024 * 1024):
                tmp.write(chunk)

        transcript = (await asyncio.to_thread(transcribe_file, temp_path)).strip()
        if not transcript:
            current = runtime.snapshot()
            runtime.update(status='ready', status_label='Prêt' if current['awake'] else 'En veille')
            return {'transcript': '', 'answer': '', 'actions': [], 'sources': [], 'ignored': True}

        if SLEEP_RE.search(transcript):
            answer = "À tout à l'heure boss."
            runtime.update(transcript=transcript, answer=answer, android_connected=True)
            if speak:
                voice.speak(answer)
            runtime.sleep()
            return {'transcript': transcript, 'answer': answer, 'actions': [], 'sources': [], 'sleep': True}

        wake_match = WAKE_RE.match(transcript)
        current = runtime.snapshot()

        if wake_match:
            remainder = transcript[wake_match.end():].strip()
            # Agrandir la même island lorsque le wake word est prononcé.
            if not remainder:
                runtime.wake(transcript=transcript, answer=GREETING)
                if speak:
                    voice.speak(GREETING)
                return {
                    'transcript': transcript,
                    'answer': GREETING,
                    'actions': [],
                    'sources': [],
                    'wake': True,
                }

            # "Bonjour Lino, cherche ..." : réveille puis exécute directement la commande.
            runtime.wake(transcript=remainder, answer='')
            answer = await agent.run(remainder)
            if speak:
                voice.speak(_spoken_answer(answer))
            snapshot = runtime.snapshot()
            return {
                'transcript': transcript,
                'answer': answer,
                'actions': snapshot['actions'],
                'sources': snapshot['sources'],
                'wake': True,
            }

        # Tant que Lino dort, les bruits ou phrases non précédées du wake word sont ignorés.
        if not current['awake']:
            runtime.update(
                status='ready',
                status_label='En veille',
                transcript='',
                answer='',
                android_connected=True,
            )
            return {'transcript': transcript, 'answer': '', 'actions': [], 'sources': [], 'ignored': True}

        runtime.update(transcript=transcript, android_connected=True)
        answer = await agent.run(transcript)
        if speak:
            voice.speak(_spoken_answer(answer))
        snapshot = runtime.snapshot()
        return {'transcript': transcript, 'answer': answer, 'actions': snapshot['actions'], 'sources': snapshot['sources']}
    except Exception as exc:
        runtime.update(status='error', status_label='Erreur', answer=str(exc), android_connected=True)
        raise HTTPException(500, str(exc)) from exc
    finally:
        if temp_path and temp_path.exists():
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@app.post('/tools/files/search')
def files_search(body: QueryRequest) -> dict:
    query = body.query.strip()
    if not query:
        return {'results': []}
    return {'results': search_file_paths(query, 40)}


@app.post('/tools/open-path')
def tools_open_path(body: PathRequest) -> dict:
    result = open_path(body.path)
    if result.startswith(('ERREUR:', 'REFUSÉ:')):
        raise HTTPException(400, result)
    return {'ok': True, 'message': result}


@app.post('/tools/open-url')
def tools_open_url(body: UrlRequest) -> dict:
    result = open_url(body.url)
    if result.startswith(('ERREUR:', 'REFUSÉ:')):
        raise HTTPException(400, result)
    return {'ok': True, 'message': result}


@app.post('/tools/open-app')
def tools_open_app(body: AppRequest) -> dict:
    result = open_application(body.app)
    if result.startswith(('ERREUR:', 'REFUSÉ:')):
        raise HTTPException(400, result)
    return {'ok': True, 'message': result}


@app.post('/tools/web/search')
async def tools_web_search(body: QueryRequest) -> dict:
    query = body.query.strip()
    if not query:
        return {'results': []}
    results = await search_web(query, None)
    return {'results': [item.public() for item in results]}


@app.post('/voice/test')
def test_voice(body: VoiceTestRequest) -> dict:
    voice.speak(body.text)
    return {'ok': True, 'tts': voice.status()}


@app.post('/voice/mute')
def mute_voice(body: VoiceMuteRequest) -> dict:
    voice.set_muted(body.muted)
    return {'ok': True, 'tts': voice.status()}


@app.post('/agents/test-alert')
def test_approval_alert() -> dict:
    key = 'Lino:test:' + uuid.uuid4().hex
    runtime.upsert_external_approval({'id': key, 'app': 'Codex', 'title': 'Test de notification',
        'message': 'Test : Codex attend ta validation. Aucune action réelle à autoriser.',
        'detected_at': __import__('time').strftime('%H:%M:%S'), 'source': 'test'})
    runtime.request_ui('expand_island')
    voice.notify_approval('Codex', key)
    timer = threading.Timer(12.0, runtime.remove_external_approval, args=(key,))
    timer.daemon = True
    timer.start()
    return {'ok': True, 'test': True, 'id': key}


@app.post('/voice/stop')
def stop_voice() -> dict:
    voice.stop()
    return {'ok': True}


def _strip_source_markers(text: str) -> str:
    return re.sub(r'\s*\[S\d+\]', '', text).strip()


if __name__ == '__main__':
    import uvicorn
    # Tauri starts the Core as a background Windows process. In that mode
    # sys.stdout may not exist (notably with pythonw.exe), while Uvicorn's
    # default color formatter expects stdout.isatty(). Disabling Uvicorn's
    # default log_config keeps the server independent from a console.
    uvicorn.run(
        'main:app',
        host=settings.lino_host,
        port=settings.lino_port,
        reload=False,
        log_config=None,
        access_log=False,
    )
