"""Google Docs sign-in using Lino's existing registered Google application."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from tools.gmail import _client_config
from user_config import app_data_dir

SCOPES = ['https://www.googleapis.com/auth/documents.readonly', 'https://www.googleapis.com/auth/drive.readonly']

def token_path(): return app_data_dir() / 'google_docs.dpapi'

def save(creds):
    import win32crypt
    path=token_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.with_suffix('.tmp').write_bytes(win32crypt.CryptProtectData(creds.to_json().encode(),'Lino Google Docs',None,None,None,0))
    path.with_suffix('.tmp').replace(path)

def credentials():
    import win32crypt
    if not token_path().exists(): raise ValueError('Connecte Google Docs dans Connexions.')
    data=json.loads(win32crypt.CryptUnprotectData(token_path().read_bytes(),None,None,None,0)[1])
    creds=Credentials.from_authorized_user_info(data,SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); save(creds)
    if not creds.valid: raise ValueError('Reconnecte Google Docs dans Connexions.')
    return creds

def status():
    return {'connected':token_path().exists(),'ready_to_connect':bool(_client_config())}

def connect():
    config=_client_config()
    if not config: raise ValueError('La connexion Google doit être intégrée à cette installation de Lino.')
    flow=InstalledAppFlow.from_client_config(config,SCOPES)
    creds=flow.run_local_server(port=0,open_browser=True,prompt='consent',timeout_seconds=180)
    save(creds)
    return {'ok':True,**status()}

def search(query: str, limit: int=10):
    escaped=query.replace('\\','\\\\').replace("'","\\'")
    service=build('drive','v3',credentials=credentials(),cache_discovery=False)
    return service.files().list(q=f"trashed = false and mimeType = 'application/vnd.google-apps.document' and name contains '{escaped}'",pageSize=max(1,min(limit,30)),fields='files(id,name,webViewLink)').execute()

def read(document_id: str):
    if document_id.startswith('https://docs.google.com/document/d/'):
        document_id=urlsplit(document_id).path.split('/')[3]
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+',document_id): raise ValueError('Identifiant Google Docs invalide.')
    doc=build('docs','v1',credentials=credentials(),cache_discovery=False).documents().get(documentId=document_id,includeTabsContent=True).execute()
    chunks=[]
    def walk(value):
        if isinstance(value,dict):
            if 'textRun' in value: chunks.append(value['textRun'].get('content',''))
            for key,item in value.items():
                if key != 'textRun': walk(item)
        elif isinstance(value,list):
            for item in value: walk(item)
    walk(doc.get('tabs') or doc.get('body',{}))
    text=''.join(chunks)
    return {'title':doc.get('title'),'url':f'https://docs.google.com/document/d/{document_id}/edit','text':text[:40000],'truncated':len(text)>40000}
