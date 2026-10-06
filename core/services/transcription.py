from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from config import settings


@lru_cache(maxsize=1)
def _model():
    # Import lazily so a broken audio backend cannot prevent Lino Core from starting.
    from faster_whisper import WhisperModel
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def _decode_audio(path: Path, sampling_rate: int = 16000) -> np.ndarray:
    """Decode audio with PyAV without faster-whisper's deprecated metadata kwargs.

    Some PyAV releases no longer accept ``metadata_errors`` / ``metadata_encoding``.
    Passing a numpy waveform to faster-whisper bypasses that compatibility problem
    completely instead of monkey-patching ``av.open``.
    """
    import av

    chunks: list[np.ndarray] = []
    resampler = av.audio.resampler.AudioResampler(format='s16', layout='mono', rate=sampling_rate)

    # Deliberately call av.open with only stable arguments.
    with av.open(str(path), mode='r') as container:
        for frame in container.decode(audio=0):
            resampled = resampler.resample(frame)
            if resampled is None:
                continue
            frames = resampled if isinstance(resampled, list) else [resampled]
            for item in frames:
                array = item.to_ndarray().reshape(-1)
                if array.size:
                    chunks.append(array)

    # Flush buffered samples if this PyAV version supports it.
    try:
        flushed = resampler.resample(None)
        if flushed:
            frames = flushed if isinstance(flushed, list) else [flushed]
            for item in frames:
                array = item.to_ndarray().reshape(-1)
                if array.size:
                    chunks.append(array)
    except Exception:
        pass

    if not chunks:
        return np.zeros((0,), dtype=np.float32)
    audio = np.concatenate(chunks).astype(np.float32)
    return audio / 32768.0


def transcribe_file(path: Path) -> str:
    waveform = _decode_audio(path)
    if waveform.size == 0:
        return ''
    segments, _ = _model().transcribe(
        waveform,
        language='fr',
        vad_filter=True,
        beam_size=4,
    )
    return ' '.join(segment.text.strip() for segment in segments).strip()
