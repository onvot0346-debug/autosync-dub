"""Monkey-patches demucs.audio.save_audio and demucs.separate.load_track
to use soundfile/numpy instead of torchaudio (which requires torchcodec
on newer pytorch and is broken in our environment)."""

import logging
import numpy as np
import soundfile as sf
import torch

log = logging.getLogger("dubbing.demucs_patch")


def _save_audio_sf(wav, path, samplerate, bitrate=320, clip="rescale",
                   bits_per_sample=16, as_float=False, preset=2):
    """Drop-in replacement for demucs.audio.save_audio using soundfile."""
    import demucs.audio as da
    wav = da.prevent_clip(wav, mode=clip)
    # demucs wav tensor: shape (channels, samples) float32
    if hasattr(wav, "cpu"):
        arr = wav.detach().cpu().numpy()
    else:
        arr = np.asarray(wav)
    # soundfile expects (samples, channels)
    if arr.ndim == 2:
        arr = arr.T
    subtype = "FLOAT" if as_float else ("PCM_16" if bits_per_sample == 16
                                        else "PCM_24" if bits_per_sample == 24
                                        else "PCM_32")
    sf.write(str(path), arr, samplerate, subtype=subtype)


def apply_patch():
    try:
        import demucs.audio as da
        da.save_audio = _save_audio_sf
        log.info("Monkey-patched demucs.audio.save_audio with soundfile backend")
    except Exception as e:
        log.warning("Could not patch demucs.audio: %s", e)
