from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.mcp_connections import mcp_connections, NOTION_URL

router = APIRouter(prefix='/mcp')


def local(request):
    if not request.client or request.client.host not in {'127.0.0.1', '::1'}:
        raise HTTPException(403, 'Cette connexion doit être configurée depuis Lino sur le PC.')
    origin = request.headers.get('origin')
    if origin and origin not in {'http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost', 'http://localhost:1420', 'http://127.0.0.1:1420'}:
        raise HTTPException(403, 'Origine non autorisée.')


class Server(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2048)


class Decision(BaseModel):
    id: str
    decision: str


@router.get('/servers')
async def servers(request: Request):
    local(request)
    return {'servers': mcp_connections.snapshot(), 'secure_storage_ready': mcp_connections.secure_storage_ready}


@router.post('/notion/connect')
async def notion(request: Request):
    local(request)
    key = await mcp_connections.add('Notion', NOTION_URL)
    return {'ok': True, 'id': key}


@router.post('/servers')
async def add_server(request: Request, body: Server):
    local(request)
    try:
        key = await mcp_connections.add(body.name, body.url)
        return {'ok': True, 'id': key}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/servers/{key}/connect')
async def connect(key: str, request: Request):
    local(request)
    try:
        await mcp_connections.connect(key)
        return {'ok': True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/servers/{key}/disconnect')
async def disconnect(key: str, request: Request):
    local(request)
    try:
        await mcp_connections.disconnect(key)
        return {'ok': True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/decision')
async def decision(request: Request, body: Decision):
    local(request)
    try:
        mcp_connections.decide(body.id, body.decision)
        return {'ok': True, 'message': 'Choix transmis.'}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/google/status')
async def google_status(request: Request):
    local(request)
    from tools.google_docs import status
    return status()

@router.post('/google/docs/connect')
async def google_docs_connect(request: Request):
    local(request)
    import asyncio
    from tools.google_docs import connect
    try:
        result = await asyncio.to_thread(connect)
        await mcp_connections.add('Google local', 'http://127.0.0.1:8765/google-mcp/')
        return result
    except Exception:
        raise HTTPException(400, 'Connexion Google Docs non terminée. Réessaie puis accepte la demande dans ton navigateur.')

@router.post('/google/gmail/connect')
async def google_gmail_connect(request: Request):
    local(request)
    import asyncio
    from tools.gmail import gmail_connect
    try:
        result = await asyncio.to_thread(gmail_connect)
        await mcp_connections.add('Google local', 'http://127.0.0.1:8765/google-mcp/')
        return result
    except Exception:
        raise HTTPException(400, 'Connexion Gmail non terminée. Réessaie puis accepte la demande dans ton navigateur.')


@router.get('/tools')
async def tools_catalog(request: Request, server: str = ''):
    local(request)
    return {'tools': mcp_connections.list_tools(server)}

@router.get('/last-result/{key}')
async def last_result(key: str, request: Request):
    local(request)
    return mcp_connections.last_results.get(key, {})

class ReadTool(BaseModel):
    server: str
    name: str
    arguments: dict = Field(default_factory=dict)

@router.post('/read')
async def read_tool(body: ReadTool, request: Request):
    local(request)
    config = mcp_connections.servers.get(body.server, {})
    if config.get('url') != NOTION_URL or body.name not in {'notion-search', 'notion-fetch'}:
        raise HTTPException(403, 'Recherche et lecture Notion uniquement.')
    return await mcp_connections.call(body.server, body.name, body.arguments)
