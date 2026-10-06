from __future__ import annotations

import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path

from config import settings


def _allowed_roots() -> list[Path]:
    from user_config import get_user_setting
    home = Path.home()
    roots = [home / name for name in ('Desktop', 'Documents', 'Downloads')]
    roots.append(Path(settings.download_dir))
    for variable in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        if os.environ.get(variable): roots.append(Path(os.environ[variable]))
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                for name in ('Desktop', 'Personal', '{374DE290-123F-4565-9164-39C4925E467B}'):
                    try: roots.append(Path(os.path.expandvars(winreg.QueryValueEx(key,name)[0])))
                    except OSError: pass
        except OSError: pass
    roots.extend(Path(p) for p in get_user_setting('file_search_roots', []) if isinstance(p,str))
    result=[]
    for root in roots:
        try:
            root=root.expanduser().resolve()
            if root.is_dir() and root not in result: result.append(root)
        except OSError: pass
    return [p for p in result if not any(other != p and other in p.parents for other in result)]


def _normalized(value):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))


def search_file_paths(query: str, limit: int = 20) -> list[str]:
    """Filename search, accent insensitive; inaccessible subfolders never stop a root."""
    stop={'cherche','chercher','recherche','rechercher','retrouve','trouve','moi','une','un','la','le','les','des','dans','mon','mes','sur','pc','ma','cette','ce','cet','ordinateur','fichier','fichiers','de','du','local','locaux','disque','onedrive','ordinateur','peux','tu','trouver','retrouver'}
    words=[w for w in re.findall(r'[\w]+',_normalized(query)) if len(w)>1 and w not in stop]
    if not words: return []
    found=[]; seen=set()
    for root in _allowed_roots():
        for directory, dirs, files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','AppData','$RECYCLE.BIN'} and not Path(directory,d).is_symlink() and not getattr(Path(directory,d),'is_junction',lambda:False)()]
            for filename in files:
                if not all(word in _normalized(filename) for word in words): continue
                path=Path(directory,filename)
                try:
                    resolved=path.resolve()
                    if not resolved.is_relative_to(root) or not resolved.is_file(): continue
                except OSError: continue
                if str(resolved) in seen: continue
                seen.add(str(resolved));found.append(str(resolved))
                if len(found)>=max(1,min(limit,100)): return found
    return found


def search_files(query: str, limit: int = 20) -> str:
    return '\n'.join(search_file_paths(query,limit)) or 'Aucun fichier trouvé par nom. Essaie le fournisseur, une date ou un mot du nom ; ajoute un dossier dans Connexions > Fichiers du PC si nécessaire.'


def _start_menu_roots() -> list[Path]:
    roots: list[Path] = []
    appdata = os.environ.get('APPDATA')
    programdata = os.environ.get('PROGRAMDATA')
    if appdata:
        roots.append(Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs')
    if programdata:
        roots.append(Path(programdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs')
    return [root for root in roots if root.exists()]


def open_application(app: str) -> str:
    """Open a desktop application without passing arbitrary input to a shell.

    Common applications use an explicit allow-list. For other installed apps, Lino
    looks for a matching Start Menu shortcut and opens the shortcut with Windows.
    """
    if os.name != 'nt':
        return 'ERREUR: open_application est prévu pour Windows.'

    requested = (app or '').strip()
    if not requested:
        return 'ERREUR: nom d’application vide.'

    key = re.sub(r'[^a-z0-9]+', ' ', requested.lower()).strip()
    aliases: dict[str, list[str]] = {
        'notepad': ['notepad.exe'],
        'bloc notes': ['notepad.exe'],
        'calculatrice': ['calc.exe'],
        'calculator': ['calc.exe'],
        'explorer': ['explorer.exe'],
        'explorateur': ['explorer.exe'],
        'powershell': ['powershell.exe'],
        'terminal': ['wt.exe'],
        'windows terminal': ['wt.exe'],
        'edge': ['msedge.exe'],
        'microsoft edge': ['msedge.exe'],
        'chrome': ['chrome.exe'],
        'google chrome': ['chrome.exe'],
        'firefox': ['firefox.exe'],
        'vscode': ['code.exe'],
        'visual studio code': ['code.exe'],
        'code': ['code.exe'],
    }

    command = aliases.get(key)
    if command:
        exe = shutil.which(command[0]) or command[0]
        try:
            subprocess.Popen(
                [exe, *command[1:]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            return f'Ouvert: {requested}'
        except OSError:
            # Some Windows apps (notably calc) may be shell aliases not found by which.
            try:
                os.startfile(command[0])  # type: ignore[attr-defined]
                return f'Ouvert: {requested}'
            except OSError:
                pass

    # Fallback: search installed Start Menu shortcuts. This does not execute arbitrary
    # user-provided command lines; it only opens an existing .lnk/.url file.
    terms = [term for term in key.split() if term]
    candidates: list[Path] = []
    for root in _start_menu_roots():
        try:
            for shortcut in root.rglob('*'):
                if shortcut.suffix.lower() not in {'.lnk', '.url'}:
                    continue
                stem = shortcut.stem.lower()
                if terms and all(term in stem for term in terms):
                    candidates.append(shortcut)
        except (PermissionError, OSError):
            continue

    if candidates:
        candidates.sort(key=lambda p: (len(p.stem), str(p).lower()))
        try:
            os.startfile(str(candidates[0]))  # type: ignore[attr-defined]
            return f'Ouvert: {candidates[0].stem}'
        except OSError as exc:
            return f'ERREUR: impossible d’ouvrir {requested}: {exc}'

    return f'ERREUR: application introuvable: {requested}'


def open_path(path: str) -> str:
    """Open a local file or folder with its default Windows application."""
    resolved = Path(path).expanduser().resolve()
    allowed = any(resolved == root or root in resolved.parents for root in _allowed_roots())
    if not allowed:
        return 'REFUSÉ: le chemin est hors des dossiers utilisateur autorisés.'
    if not resolved.exists():
        return 'ERREUR: fichier introuvable.'
    if os.name == 'nt':
        os.startfile(str(resolved))  # type: ignore[attr-defined]
        return f'Ouvert: {resolved.name}'
    return 'ERREUR: open_path est prévu pour Windows.'


def open_url(url: str) -> str:
    """Open an http/https URL in the user's default browser."""
    if not url.startswith(('https://', 'http://')):
        return 'REFUSÉ: seules les URL http/https sont autorisées.'
    webbrowser.open(url)
    return f'URL ouverte: {url}'

