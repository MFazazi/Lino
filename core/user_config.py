from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

_LOCK = RLock()


def app_data_dir() -> Path:
    """Persistent per-user Lino data directory.

    On Windows this resolves to %LOCALAPPDATA%\\Lino. It deliberately lives outside
    the source tree so updates never overwrite connections or user settings.
    """
    base = os.environ.get('LOCALAPPDATA')
    if base:
        root = Path(base) / 'Lino'
    else:
        root = Path.home() / '.lino'
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return app_data_dir() / 'config.json'


def load_user_config() -> dict[str, Any]:
    with _LOCK:
        path = config_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def save_user_config(values: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        current = load_user_config()
        current.update(values)
        path = config_path()
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
        return current


def delete_user_config_keys(*keys: str) -> dict[str, Any]:
    with _LOCK:
        current = load_user_config()
        for key in keys:
            current.pop(key, None)
        path = config_path()
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        return current


def get_user_setting(name: str, default: Any = None) -> Any:
    return load_user_config().get(name, default)
