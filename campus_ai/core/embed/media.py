"""Decode audio and video files with PyAV (bundles FFmpeg, no system packages)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

AUDIO_RATE = 16_000  # EmbeddingGemma 2 expects mono 16 kHz audio
VIDEO_FPS = 1.0  # and samples video at 1 frame per second


def load_audio(path: str | Path, rate: int = AUDIO_RATE) -> np.ndarray:
    """Return the first audio stream as mono float32 samples at `rate` Hz."""
    import av

    resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
    chunks = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            chunks += [out.to_ndarray().reshape(-1) for out in resampler.resample(frame)]
    chunks += [out.to_ndarray().reshape(-1) for out in resampler.resample(None)]
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def load_video(path: str | Path, fps: float = VIDEO_FPS) -> dict:
    """Return RGB frames sampled at `fps` as {"array": (frames, h, w, 3), "video_metadata": ...}."""
    import av

    frames, next_time = [], 0.0
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.time is None or frame.time >= next_time:
                frames.append(frame.to_ndarray(format="rgb24"))
                next_time += 1 / fps
    if not frames:
        raise ValueError(f"no video frames in {path}")
    array = np.stack(frames)
    metadata = {"fps": fps, "total_num_frames": len(array), "duration": len(array) / fps}
    return {"array": array, "video_metadata": metadata}
