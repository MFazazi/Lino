from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, SecretStr
from mcp_routes import local
from services.stripe_monitor import stripe_monitor
from tools.windows import _allowed_roots
from user_config import get_user_setting, save_user_config

router=APIRouter(prefix='/personal')
class StripeKey(BaseModel):
    key: SecretStr
class Roots(BaseModel):
    roots: list[str]=Field(max_length=30)

@router.get('/stripe')
async def stripe_status(request:Request):
    local(request);return stripe_monitor.snapshot()

@router.post('/stripe/connect')
async def stripe_connect(request:Request,body:StripeKey):
    local(request)
    try:return await stripe_monitor.connect(body.key.get_secret_value())
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception:raise HTTPException(503,'Connexion Stripe impossible. Vérifie le réseau et réessaie.')

@router.post('/stripe/disconnect')
async def stripe_disconnect(request:Request):
    local(request);return await stripe_monitor.disconnect()

@router.post('/stripe/notifications/{event_id}/read')
async def read_notification(request:Request,event_id:str):
    local(request);return await stripe_monitor.acknowledge(event_id)

@router.get('/files')
async def file_roots(request:Request):
    local(request)
    return {'roots':[str(p) for p in _allowed_roots()],'custom_roots':get_user_setting('file_search_roots',[])}

@router.post('/files')
async def configure_roots(request:Request,body:Roots):
    local(request);roots=[]
    for value in body.roots:
        path=Path(value.strip()).expanduser()
        if value.startswith(('\\\\','//')) or not path.is_absolute() or not path.is_dir():
            raise HTTPException(400,'Choisis un dossier local existant avec son chemin complet.')
        roots.append(str(path.resolve()))
    save_user_config({'file_search_roots':list(dict.fromkeys(roots))})
    return await file_roots(request)


@router.post('/document')
async def upload_document(request:Request,file:UploadFile=File(...)):
    local(request)
    import asyncio, uuid
    from config import settings
    data=await file.read(50*1024*1024+1)
    if len(data)>50*1024*1024:raise HTTPException(413,'Choisis un PDF de moins de 50 Mo.')
    if not data.startswith(b'%PDF-'):raise HTTPException(400,'Choisis un fichier PDF valide.')
    folder=Path(settings.download_dir)/'documents';folder.mkdir(parents=True,exist_ok=True)
    name=Path(file.filename or 'document.pdf').name
    import re
    name=re.sub(r'[^\w .-]','_',name)[:100]
    if not name.lower().endswith('.pdf'):name+=' .pdf'
    target=folder/(uuid.uuid4().hex[:12]+'-'+name)
    await asyncio.to_thread(target.write_bytes,data)
    return {'path':str(target.resolve()),'name':name}

@router.post('/dictate')
async def dictate(request:Request,file:UploadFile=File(...)):
    local(request)
    import asyncio,tempfile
    from services.transcription import transcribe_file
    data=await file.read(15*1024*1024+1)
    if len(data)>15*1024*1024:raise HTTPException(413,'Enregistrement trop long (maximum 60 secondes).')
    if not data:raise HTTPException(400,'Aucun son reçu.')
    path=None
    try:
        with tempfile.NamedTemporaryFile(suffix='.webm',delete=False) as tmp:tmp.write(data);path=Path(tmp.name)
        text=await asyncio.to_thread(transcribe_file,str(path))
        if not text.strip():raise HTTPException(422,'Aucune parole reconnue. Réessaie ou écris ton message.')
        return {'transcript':text.strip()}
    except HTTPException:raise
    except Exception:raise HTTPException(503,'La transcription est indisponible. Vérifie le moteur vocal dans Lino.')
    finally:
        if path:path.unlink(missing_ok=True)
