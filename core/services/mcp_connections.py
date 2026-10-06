"""Remote MCP connections with browser OAuth and Windows-encrypted credentials."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull, OAuthToken

from state import runtime
from user_config import app_data_dir

NOTION_URL = 'https://mcp.notion.com/mcp'
CALLBACK = 'http://127.0.0.1:8766/oauth/callback'


def validate_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError('Adresse de serveur invalide.')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}):
        raise ValueError('Utilise une adresse HTTPS, ou HTTP pour un serveur local.')
    return url.strip()


class SecureStorage:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        if not self.path.exists():
            return {}
        import win32crypt
        return json.loads(win32crypt.CryptUnprotectData(self.path.read_bytes(), None, None, None, 0)[1])

    def save(self, data):
        import win32crypt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = win32crypt.CryptProtectData(json.dumps(data).encode(), 'Lino MCP', None, None, None, 0)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_bytes(raw)
        tmp.replace(self.path)

    async def get_tokens(self):
        data = self.load()
        token = data.get('tokens')
        if token:
            if token.get('expires_in') is not None:
                token['expires_in'] = max(0, int(token['expires_in'] - (time.time() - data.get('saved_at', 0))))
            return OAuthToken.model_validate(token)

    async def set_tokens(self, tokens):
        data = self.load()
        data.update(tokens=tokens.model_dump(mode='json'), saved_at=time.time())
        self.save(data)

    async def get_client_info(self):
        data = self.load().get('client')
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info):
        data = self.load()
        data['client'] = client_info.model_dump(mode='json')
        self.save(data)

    def clear_tokens(self):
        data = self.load()
        data.pop('tokens', None)
        data.pop('saved_at', None)
        self.save(data)


class MCPConnections:
    def __init__(self, root=None):
        self.root = Path(root) if root else app_data_dir() / 'mcp'
        self.servers = {}
        self.workers = {}
        self.statuses = {}
        self.queues = {}
        self.catalogs = {}
        self.approvals = {}
        self.last_results = {}
        self.oauth_states = {}
        self.callback_server = None
        self.secure_storage_ready = False
        config = self.root / 'servers.json'
        if config.exists():
            self.servers = json.loads(config.read_text(encoding='utf-8'))

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / 'servers.json'
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.servers, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)

    def storage(self, key):
        return SecureStorage(self.root / (key + '.dpapi'))

    def snapshot(self):
        return [{'id': key, **value, **self.statuses.get(key, {'status': 'disconnected'}),
                 'tool_count': len(self.catalogs.get(key, []))} for key, value in self.servers.items()]

    async def add(self, name, url):
        url = validate_url(url)
        if url == 'http://127.0.0.1:8765/google-mcp': url += '/'
        name = name.strip()[:60]
        if not name:
            raise ValueError('Donne un nom à cette connexion.')
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        self.servers[key] = {'name': name, 'url': url}
        self.save()
        await self.connect(key, interactive=True)
        return key

    async def connect(self, key, interactive=True):
        if key not in self.servers:
            raise ValueError('Connexion inconnue.')
        if interactive:
            self.servers[key]['enabled'] = True
            self.save()
        if key in self.workers and not self.workers[key].done():
            return
        self.statuses[key] = {'status': 'connecting', 'message': 'Connexion en cours…'}
        self.queues[key] = asyncio.Queue()
        self.workers[key] = asyncio.create_task(self._worker(key, interactive))

    async def start(self):
        try:
            import win32crypt
            probe = b'Lino storage availability check'
            encrypted = win32crypt.CryptProtectData(probe, 'Lino MCP check', None, None, None, 0)
            self.secure_storage_ready = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1] == probe
        except Exception:
            self.secure_storage_ready = False
        for key in self.servers:
            if self.servers[key].get('enabled', True):
                await self.connect(key, interactive=False)

    async def stop(self):
        for task in self.workers.values():
            task.cancel()
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
        if self.callback_server:
            await asyncio.to_thread(self.callback_server.shutdown)
            self.callback_server.server_close()
            self.callback_server = None

    async def disconnect(self, key):
        if key not in self.servers:
            raise ValueError('Connexion inconnue.')
        task = self.workers.pop(key, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.storage(key).clear_tokens()
        self.servers[key]['enabled'] = False
        self.save()
        self.catalogs.pop(key, None)
        self.statuses[key] = {'status': 'disconnected', 'message': 'Déconnecté de Lino'}

    def _ensure_callback(self):
        if self.callback_server:
            return
        manager = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                params = parse_qs(parsed.query)
                state = params.get('state', [''])[0]
                record = manager.oauth_states.get(state)
                if self.headers.get('Host') != '127.0.0.1:8766' or parsed.path != '/oauth/callback' or not record:
                    self.send_error(400, 'Connexion inconnue ou expiree')
                    return
                loop, future = record
                def resolve():
                    if future.done():
                        return
                    if params.get('error'):
                        future.set_exception(ValueError('Connexion refusée dans le navigateur.'))
                    elif params.get('code'):
                        future.set_result((params['code'][0], state))
                    else:
                        future.set_exception(ValueError('Code de connexion manquant.'))
                loop.call_soon_threadsafe(resolve)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write('<html lang="fr"><meta charset="utf-8"><title>Lino</title><body style="background:#181322;color:#eee;font:18px system-ui;padding:70px"><h1>Retour à Lino</h1><p>La réponse a été reçue. Lino vérifie la connexion.</p><p>Tu peux fermer cet onglet.</p></body></html>'.encode())
            def log_message(self, *_):
                pass
        self.callback_server = ThreadingHTTPServer(('127.0.0.1', 8766), Handler)
        threading.Thread(target=self.callback_server.serve_forever, daemon=True, name='LinoOAuthCallback').start()

    async def _worker(self, key, interactive):
        config = self.servers[key]
        callback_future = None
        callback_state = None
        active_future = None
        async def redirect(url):
            nonlocal callback_future, callback_state
            if not interactive:
                raise ValueError('Reconnecte ce service depuis Connexions.')
            if urlsplit(url).scheme != 'https' and urlsplit(url).hostname not in {'127.0.0.1', 'localhost'}:
                raise ValueError('Adresse de connexion non sécurisée.')
            self._ensure_callback()
            callback_state = parse_qs(urlsplit(url).query).get('state', [''])[0]
            if not callback_state:
                raise ValueError('État OAuth manquant.')
            callback_future = asyncio.get_running_loop().create_future()
            self.oauth_states[callback_state] = (asyncio.get_running_loop(), callback_future)
            self.statuses[key] = {'status': 'authorizing', 'message': 'Termine la connexion dans ton navigateur.'}
            opened = await asyncio.to_thread(webbrowser.open, url)
            if not opened:
                raise ValueError('Le navigateur n’a pas pu être ouvert.')
        async def callback():
            if callback_future is None:
                raise ValueError('Connexion non initialisée.')
            return await asyncio.wait_for(callback_future, 300)
        auth = OAuthClientProvider(
            server_url=config['url'],
            client_metadata=OAuthClientMetadata(client_name='Lino', redirect_uris=[CALLBACK],
                grant_types=['authorization_code', 'refresh_token'], response_types=['code'], token_endpoint_auth_method='none'),
            storage=self.storage(key), redirect_handler=redirect, callback_handler=callback,
        )
        try:
            async with httpx.AsyncClient(auth=auth, timeout=httpx.Timeout(30, read=320), follow_redirects=False) as http:
                async with streamable_http_client(config['url'], http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        async with asyncio.timeout(330):
                            await session.initialize()
                            tools = await session.list_tools()
                            catalog = list(tools.tools)
                            while tools.nextCursor:
                                tools = await session.list_tools(cursor=tools.nextCursor)
                                catalog.extend(tools.tools)
                        self.catalogs[key] = [tool.model_dump(mode='json') for tool in catalog]
                        self.statuses[key] = {'status': 'connected', 'message': 'Connecté'}
                        while True:
                            name, arguments, future = await self.queues[key].get()
                            active_future = future
                            if future.cancelled():
                                continue
                            try:
                                result = await asyncio.wait_for(session.call_tool(name, arguments), 60)
                                if not future.done():
                                    self.last_results[key] = {'tool': name, 'result': result.model_dump(mode='json')}
                                    future.set_result(result.model_dump(mode='json'))
                            except Exception:
                                if not future.done():
                                    future.set_exception(ValueError('Le service n’a pas confirmé le résultat de l’action.'))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not expose remote errors containing authorization URLs or tokens.
            self.statuses[key] = {'status': 'error', 'message': 'Connexion impossible ou expirée. Réessaie Connecter.', 'error_type': type(exc).__name__}
        finally:
            if active_future and not active_future.done():
                active_future.set_exception(ValueError('Connexion interrompue. Résultat non confirmé.'))
            if callback_state:
                self.oauth_states.pop(callback_state, None)
            self.catalogs.pop(key, None)
            queue = self.queues.get(key)
            if queue:
                while not queue.empty():
                    _, _, future = queue.get_nowait()
                    if not future.done():
                        future.set_exception(ValueError('Connexion interrompue.'))

    def list_tools(self, server=''):
        result = []
        for key, catalog in self.catalogs.items():
            if server and server not in {key, self.servers[key]['name']}:
                continue
            for tool in catalog:
                result.append({'server': key, 'service': self.servers[key]['name'], 'name': tool['name'],
                               'description': tool.get('description', '')[:1200], 'parameters': tool['inputSchema']})
        return result

    def decide(self, key, decision):
        future = self.approvals.get(key)
        if not future or future.done() or decision not in {'allow', 'deny'}:
            raise ValueError('Cette demande n’est plus disponible.')
        future.set_result(decision == 'allow')

    async def call(self, key, name, arguments):
        if key not in self.catalogs:
            raise ValueError('Connecte ce service dans Connexions.')
        tool = next((t for t in self.catalogs[key] if t['name'] == name), None)
        if not tool:
            raise ValueError('Outil inconnu sur ce serveur.')
        import jsonschema
        jsonschema.validate(arguments, tool['inputSchema'])
        # Remote annotations are not authorization. Only explicitly known Notion
        # read tools run without a per-action confirmation; other tools require it.
        read_only = (self.servers[key]['url'] == 'http://127.0.0.1:8765/google-mcp/' and name in {'search_gmail', 'read_gmail', 'search_google_docs', 'read_google_doc'}) or self.servers[key]['url'] == NOTION_URL and name in {'notion-search', 'notion-fetch', 'notion-get-users', 'notion-get-user', 'notion-get-teams', 'notion-get-comments'}
        if not read_only:
            preview = json.dumps(arguments, ensure_ascii=False, indent=2)
            if len(preview) > 12000:
                raise ValueError('Action trop longue pour être validée dans Lino.')
            approval_id = 'mcp:' + secrets.token_hex(16)
            future = asyncio.get_running_loop().create_future()
            self.approvals[approval_id] = future
            runtime.upsert_external_approval({'id': approval_id, 'app': self.servers[key]['name'],
                'title': 'Action à confirmer', 'message': name + '\n' + preview,
                'detected_at': time.strftime('%H:%M'), 'source': 'mcp', 'can_respond': True,
                'allow_label': 'Autoriser une fois', 'deny_label': 'Refuser'})
            runtime.request_ui('expand_island')
            from services.voice import voice
            voice.notify_approval(self.servers[key]['name'], approval_id)
            try:
                if not await asyncio.wait_for(future, 180):
                    return {'isError': True, 'content': [{'type': 'text', 'text': 'Action refusée par l’utilisateur. Rien n’a été envoyé.'}]}
            finally:
                self.approvals.pop(approval_id, None)
                runtime.remove_external_approval(approval_id)
        if key not in self.catalogs:
            raise ValueError('Le service a été déconnecté avant l’envoi. Aucune action envoyée.')
        future = asyncio.get_running_loop().create_future()
        await self.queues[key].put((name, arguments, future))
        return await asyncio.wait_for(future, 70)


mcp_connections = MCPConnections()
