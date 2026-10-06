from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from config import settings
from state import runtime


class VoiceService:
    """Natural voice first, zero-setup fallback second.

    On Windows Lino prefers Edge neural speech when the optional ``edge-tts`` package
    is installed. It requires no user API key. If the online voice is unavailable,
    Lino falls back to the local Windows SAPI voice in the same worker thread.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, str | None] | None] = queue.Queue()
        self._muted = False
        self._last_delivery = None
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._backend = 'initializing'
        self._last_error = ''
        self._player: subprocess.Popen | None = None
        self._speaker: Any = None
        self._thread = threading.Thread(target=self._worker, daemon=True, name='lino-tts')
        self._thread.start()
        self._ready.wait(timeout=4.0)

    def status(self) -> dict[str, Any]:
        return {
            'enabled': bool(settings.tts_enabled),
            'backend': self._backend,
            'ready': self._ready.is_set() and self._backend != 'unavailable',
            'last_error': self._last_error,
            'muted': self._muted,
            'last_delivery': self._last_delivery,
        }

    def speak(self, text: str) -> None:
        clean = (text or '').strip()
        if not settings.tts_enabled or self._muted or not clean:
            return
        self._stop_event.clear()
        self._queue.put((clean, None))

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        runtime.update(voice_muted=muted)
        if muted:
            self.stop()

    def notify_approval(self, app: str, key: str) -> None:
        if self._muted:
            return
        self._queue.put(('', key))

    def stop(self) -> None:
        self._stop_event.set()
        try:
            if self._player and self._player.poll() is None:
                self._player.terminate()
        except Exception:
            pass
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        current = runtime.snapshot()
        if current['status'] == 'speaking':
            runtime.update(status='ready', status_label='Prêt' if current['awake'] else 'En veille')

    def _init_sapi(self) -> Any:
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore

            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch('SAPI.SpVoice')
            try:
                voices = speaker.GetVoices()
                for index in range(voices.Count):
                    voice = voices.Item(index)
                    description = str(voice.GetDescription()).lower()
                    try:
                        language = str(voice.GetAttribute('Language')).lower()
                    except Exception:
                        language = ''
                    if 'french' in description or 'français' in description or '040c' in language:
                        speaker.Voice = voice
                        break
            except Exception:
                pass
            speaker.Rate = 0
            return speaker
        except Exception as exc:
            self._last_error = f'SAPI: {exc}'
            return None

    @staticmethod
    def _edge_available() -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False

    def _play_mp3_windows(self, path: Path) -> None:
        # PresentationCore is present on standard Windows desktop installations and
        # can play MP3 without asking the user to install an audio player.
        safe = str(path).replace("'", "''")
        script = (
            "Add-Type -AssemblyName presentationCore; "
            "$p=New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([Uri]'{safe}'); $p.Play(); "
            "$limit=0; while((-not $p.NaturalDuration.HasTimeSpan) -and $limit -lt 100){Start-Sleep -Milliseconds 50;$limit++}; "
            "if($p.NaturalDuration.HasTimeSpan){$ms=[math]::Ceiling($p.NaturalDuration.TimeSpan.TotalMilliseconds)+250; Start-Sleep -Milliseconds $ms}else{$p.Close();exit 1}; "
            "$p.Close();"
        )
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self._player = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        while self._player.poll() is None:
            if self._stop_event.is_set():
                try:
                    self._player.terminate()
                except Exception:
                    pass
                break
            time.sleep(0.05)
        code = self._player.returncode
        self._player = None
        if code not in (0, None) and not self._stop_event.is_set():
            raise RuntimeError(f'lecture audio Windows impossible (code {code})')

    def _speak_edge(self, text: str) -> bool:
        try:
            import edge_tts

            tmp = Path(tempfile.gettempdir()) / f'lino-voice-{threading.get_ident()}.mp3'

            async def make_audio() -> None:
                communicate = edge_tts.Communicate(
                    text,
                    voice='fr-FR-HenriNeural',
                    rate='+2%',
                    pitch='-2Hz',
                )
                await communicate.save(str(tmp))

            asyncio.run(asyncio.wait_for(make_audio(), timeout=12.0))
            if self._stop_event.is_set():
                return True
            self._play_mp3_windows(tmp)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return True
        except Exception as exc:
            self._last_error = f'Voix neuronale: {exc}'
            return False

    def _speak_sapi(self, text: str) -> bool:
        if self._speaker is None:
            return False
        try:
            self._speaker.Speak(text, 1)
            while not self._speaker.WaitUntilDone(100):
                if self._stop_event.is_set():
                    self._speaker.Speak('', 3)
                    break
            return True
        except Exception as exc:
            self._last_error = f'SAPI: {exc}'
            return False

    def _worker(self) -> None:
        edge_ready = os.name == 'nt' and self._edge_available()
        self._speaker = self._init_sapi() if os.name == 'nt' else None
        if edge_ready:
            self._backend = 'voix-neuronale'
        elif self._speaker is not None:
            self._backend = 'windows-sapi'
        else:
            self._backend = 'unavailable'
        self._ready.set()

        while True:
            item = self._queue.get()
            if item is None:
                break
            text, approval_key = item
            if self._muted:
                continue
            if approval_key and not any(a['id'] == approval_key for a in runtime.snapshot()['external_approvals']):
                continue  # The user already handled this request while speech was queued.
            self._stop_event.clear()
            if not approval_key:
                runtime.update(status='speaking', status_label='Je réponds')
            try:
                # Permission alerts are a short system sound; never read the request aloud.
                if approval_key:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    self._last_delivery = {'kind': 'approval', 'spoken': False, 'sound': True, 'at': time.time()}
                else:
                    spoken = self._speak_edge(text) if edge_ready else False
                    if not spoken and not self._stop_event.is_set():
                        spoken = self._speak_sapi(text)
                    self._last_delivery = {'kind': 'reply', 'spoken': spoken, 'at': time.time()}
                    if not spoken and not self._stop_event.is_set():
                        runtime.update(status='error', status_label='Voix indisponible')
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                current = runtime.snapshot()
                if not approval_key and current['status'] == 'speaking':
                    runtime.update(status='ready', status_label='Prêt' if current['awake'] else 'En veille')


voice = VoiceService()
