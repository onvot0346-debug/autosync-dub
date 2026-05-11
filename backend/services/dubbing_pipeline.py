"""
Chinese video -> Turkish dubbed video pipeline.
All processing is local / free (no API keys required):
  - whisper (transcription)
  - deep-translator (Google free translate)
  - edge-tts (Microsoft Edge neural TTS)
  - demucs (vocal/music separation, optional fallback to ffmpeg filter)
  - librosa + soundfile (time-stretch)
  - ffmpeg (audio/video muxing)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Dict, Optional

import edge_tts
import librosa
import numpy as np
import soundfile as sf
import whisper
from deep_translator import GoogleTranslator
from pydub import AudioSegment

from .glossary import apply_glossary
from .gpt_translator import translate_with_gpt4o

log = logging.getLogger("dubbing")

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "medium")
TTS_VOICE = os.environ.get("TTS_VOICE", "tr-TR-AhmetNeural")  # professional male


# ------------------------------------------------------------------
# Resolve ffmpeg / ffprobe binaries (static-ffmpeg bundled, persistent in venv)
# ------------------------------------------------------------------
def _resolve_ffmpeg_binaries():
    # Prefer system if available (faster startup), fall back to static-ffmpeg
    sys_ffmpeg = shutil.which("ffmpeg")
    sys_ffprobe = shutil.which("ffprobe")
    if sys_ffmpeg and sys_ffprobe:
        return sys_ffmpeg, sys_ffprobe
    try:
        from static_ffmpeg import run as _sf
        ff, fp = _sf.get_or_fetch_platform_executables_else_raise()
        # Make sure pydub also finds ffmpeg
        os.environ["PATH"] = os.path.dirname(ff) + os.pathsep + os.environ.get("PATH", "")
        return ff, fp
    except Exception as e:
        log.error("Could not resolve ffmpeg/ffprobe: %s", e)
        return "ffmpeg", "ffprobe"  # last-resort, will fail clearly later


FFMPEG_BIN, FFPROBE_BIN = _resolve_ffmpeg_binaries()
log.info(f"Using ffmpeg: {FFMPEG_BIN}")
log.info(f"Using ffprobe: {FFPROBE_BIN}")

# Make sure pydub uses the same ffmpeg
try:
    from pydub import AudioSegment as _AS
    _AS.converter = FFMPEG_BIN
    _AS.ffmpeg = FFMPEG_BIN
    _AS.ffprobe = FFPROBE_BIN
except Exception:
    pass

# Lazy-loaded model cache
_whisper_model = None


# ------------------------------------------------------------------
# Supported source languages (Whisper ISO-639-1 codes + Turkish names)
# ------------------------------------------------------------------
SUPPORTED_LANGUAGES: List[Dict[str, str]] = [
    {"code": "auto", "name": "Otomatik Algıla"},
    {"code": "zh", "name": "Çince"},
    {"code": "vi", "name": "Vietnamca"},
    {"code": "en", "name": "İngilizce"},
    {"code": "ja", "name": "Japonca"},
    {"code": "ko", "name": "Korece"},
    {"code": "ru", "name": "Rusça"},
    {"code": "ar", "name": "Arapça"},
    {"code": "fa", "name": "Farsça"},
    {"code": "hi", "name": "Hintçe"},
    {"code": "id", "name": "Endonezce"},
    {"code": "th", "name": "Tayca"},
    {"code": "fr", "name": "Fransızca"},
    {"code": "de", "name": "Almanca"},
    {"code": "es", "name": "İspanyolca"},
    {"code": "it", "name": "İtalyanca"},
    {"code": "pt", "name": "Portekizce"},
    {"code": "nl", "name": "Hollandaca"},
    {"code": "pl", "name": "Lehçe"},
    {"code": "uk", "name": "Ukraynaca"},
    {"code": "tr", "name": "Türkçe"},
]
_LANG_NAMES_TR = {lng["code"]: lng["name"] for lng in SUPPORTED_LANGUAGES}


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        log.info(f"Loading whisper model: {WHISPER_MODEL_NAME}")
        _whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    return _whisper_model


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    log.info("RUN: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, check=True, capture_output=True, **kwargs)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-1500:]
        log.error("Command failed (exit %s): %s\nSTDERR:\n%s",
                  e.returncode, " ".join(cmd), stderr_tail)
        raise


# ------------------------------------------------------------------
# Stage 1 — Extract audio from video
# ------------------------------------------------------------------
def extract_audio(video_path: Path, out_wav: Path) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([
        FFMPEG_BIN, "-y", "-i", str(video_path),
        "-vn", "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_s16le", str(out_wav),
    ])
    return out_wav


# ------------------------------------------------------------------
# Stage 2 — Separate vocals from background music
# ------------------------------------------------------------------
def separate_vocals(input_wav: Path, work_dir: Path) -> Dict[str, Path]:
    """Return paths to vocals.wav and accompaniment.wav"""
    out_dir = work_dir / "demucs"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _run([
            "python", "-m", "demucs.separate",
            "--two-stems", "vocals",
            "-n", "htdemucs",
            "-o", str(out_dir),
            str(input_wav),
        ])
        # demucs writes to <out>/<model>/<stem>/{vocals.wav,no_vocals.wav}
        stem = input_wav.stem
        produced = out_dir / "htdemucs" / stem
        return {
            "vocals": produced / "vocals.wav",
            "music": produced / "no_vocals.wav",
        }
    except Exception as e:
        log.warning(f"Demucs failed ({e}). Using original audio as fallback (no separation).")
        # Pragmatic fallback: use original audio for transcription, and a
        # lowered-volume copy as the "music" track (we can't truly separate).
        vocals = work_dir / "vocals.wav"
        music = work_dir / "music.wav"
        # Vocals = original (whisper handles speech-with-music decently)
        _run([FFMPEG_BIN, "-y", "-i", str(input_wav), "-c:a", "pcm_s16le", str(vocals)])
        # Music track = original at -10dB so the new Turkish voice dominates the mix
        _run([
            FFMPEG_BIN, "-y", "-i", str(input_wav),
            "-af", "volume=-10dB",
            "-c:a", "pcm_s16le", str(music),
        ])
        return {"vocals": vocals, "music": music}


# ------------------------------------------------------------------
# Stage 3 — Transcribe speech with timestamps (segments)
#   Supports auto language detection (language="auto" or None)
# ------------------------------------------------------------------
def transcribe_audio(vocals_wav: Path, language: Optional[str] = None,
                    initial_prompt: Optional[str] = None) -> Dict:
    """Returns {"segments": [...], "language": "zh"|"vi"|...}.
    If `language` is None or "auto", Whisper auto-detects.
    """
    model = _get_whisper()
    kwargs = dict(
        verbose=False,
        condition_on_previous_text=True,
        task="transcribe",
    )
    if language and language != "auto":
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    result = model.transcribe(str(vocals_wav), **kwargs)
    detected_lang = result.get("language", language or "unknown")
    segments = []
    for s in result.get("segments", []):
        segments.append({
            "id": s["id"],
            "start": float(s["start"]),
            "end": float(s["end"]),
            "text_src": s["text"].strip(),
        })
    return {"segments": segments, "language": detected_lang}


# Backward-compat alias (kept temporarily; unused after refactor)
def transcribe_chinese(vocals_wav: Path) -> List[Dict]:
    return transcribe_audio(vocals_wav, language="zh")["segments"]


# ------------------------------------------------------------------
# Stage 4 — Translate each segment to Turkish (GPT-4o context-aware,
# with deep-translator fallback). Source language is dynamic.
# ------------------------------------------------------------------
# ISO-639-1 codes used by Whisper -> deep-translator equivalents
_DEEP_LANG = {
    "zh": "zh-CN", "vi": "vi", "en": "en", "ko": "ko", "ja": "ja",
    "ru": "ru", "ar": "ar", "fr": "fr", "de": "de", "es": "es",
    "it": "it", "pt": "pt", "hi": "hi", "id": "id", "th": "th",
    "tr": "tr", "nl": "nl", "pl": "pl", "fa": "fa", "uk": "uk",
}


def translate_segments(segments: List[Dict], source_lang: str = "auto") -> List[Dict]:
    if not segments:
        return segments

    # Pre-fill text_tr empty so we can detect what GPT-4o filled
    for s in segments:
        s.setdefault("text_tr", "")

    # 1) Try GPT-4o whole-transcript pass (highest quality, any source language)
    used_gpt = False
    try:
        asyncio.run(translate_with_gpt4o(segments, source_lang=source_lang))
        used_gpt = any(s.get("text_tr") for s in segments)
        log.info("GPT-4o translation: %s segments translated (src=%s)",
                 sum(1 for s in segments if s.get("text_tr")), source_lang)
    except Exception as e:
        log.warning("GPT-4o translator threw: %s", e)

    # 2) Per-segment fallback for any still-empty entries
    missing = [s for s in segments if not s.get("text_tr") and (s.get("text_src") or s.get("text_zh", "")).strip()]
    if missing:
        log.info("Falling back to deep-translator for %d untranslated segments", len(missing))
        deep_src = _DEEP_LANG.get(source_lang, "auto")
        try:
            translator = GoogleTranslator(source=deep_src, target="tr")
        except Exception:
            translator = GoogleTranslator(source="auto", target="tr")
        for seg in missing:
            src_text = seg.get("text_src") or seg.get("text_zh", "")
            try:
                tr = translator.translate(src_text) or ""
            except Exception as e:
                log.warning(f"Translate failed for seg {seg['id']}: {e}")
                tr = ""
            seg["text_tr"] = tr

    # 3) Apply glossary corrections (Chinese-only; harmless for other languages)
    for seg in segments:
        seg["text_tr"] = apply_glossary(
            seg.get("text_src") or seg.get("text_zh", ""),
            seg.get("text_tr", ""),
        )

    log.info("Translation complete (gpt4o_used=%s, src=%s)", used_gpt, source_lang)
    return segments


# ------------------------------------------------------------------
# Stage 5 — TTS each Turkish segment, then time-stretch to fit original duration
# ------------------------------------------------------------------
async def _tts_one(text: str, out_path: Path, voice: str = TTS_VOICE):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+0%")
    await communicate.save(str(out_path))


def _time_stretch_to_duration(in_wav: Path, target_seconds: float, out_wav: Path):
    """Time-stretch audio to exactly target_seconds using librosa."""
    y, sr = librosa.load(str(in_wav), sr=None, mono=True)
    cur_dur = len(y) / sr
    if cur_dur <= 0.05 or target_seconds <= 0.05:
        sf.write(str(out_wav), y, sr)
        return
    # rate > 1 -> faster (shorter); rate < 1 -> slower (longer)
    rate = cur_dur / target_seconds
    # clamp to keep speech intelligible
    rate = max(0.7, min(1.6, rate))
    try:
        y_stretched = librosa.effects.time_stretch(y, rate=rate)
    except Exception:
        y_stretched = y
    # If still doesn't match target, pad / truncate
    target_samples = int(target_seconds * sr)
    if len(y_stretched) < target_samples:
        pad = np.zeros(target_samples - len(y_stretched), dtype=y_stretched.dtype)
        y_stretched = np.concatenate([y_stretched, pad])
    else:
        y_stretched = y_stretched[:target_samples]
    sf.write(str(out_wav), y_stretched, sr)


def synthesize_turkish_track(
    segments: List[Dict],
    work_dir: Path,
    total_duration_sec: float,
    voice: str = TTS_VOICE,
) -> Path:
    """Generate a single WAV track containing all Turkish TTS segments
    placed at the original timestamps."""
    seg_dir = work_dir / "tts_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    # 1) Generate raw TTS mp3 per segment
    async def _gen_all():
        for seg in segments:
            text = seg.get("text_tr") or ""
            seg_mp3 = seg_dir / f"seg_{seg['id']:04d}.mp3"
            if not text.strip():
                # write a tiny silent placeholder
                AudioSegment.silent(duration=10).export(seg_mp3, format="mp3")
            else:
                await _tts_one(text, seg_mp3, voice=voice)
            seg["_tts_mp3"] = seg_mp3
    asyncio.run(_gen_all())

    # 2) Time-stretch each to match original segment duration
    sr_target = 44100
    final = AudioSegment.silent(duration=int(total_duration_sec * 1000))
    for seg in segments:
        dur = max(0.1, seg["end"] - seg["start"])
        seg_wav = seg_dir / f"seg_{seg['id']:04d}.wav"
        # convert mp3 -> wav
        AudioSegment.from_file(seg["_tts_mp3"]).set_frame_rate(sr_target).set_channels(1).export(seg_wav, format="wav")
        stretched = seg_dir / f"seg_{seg['id']:04d}_fit.wav"
        _time_stretch_to_duration(seg_wav, dur, stretched)
        piece = AudioSegment.from_wav(stretched)
        # overlay at start time
        final = final.overlay(piece, position=int(seg["start"] * 1000))

    out_path = work_dir / "turkish_vocal.wav"
    final.set_frame_rate(sr_target).set_channels(2).export(out_path, format="wav")
    return out_path


# ------------------------------------------------------------------
# Stage 6 — Mix Turkish vocal + original music, then mux back into video
# ------------------------------------------------------------------
def mix_and_mux(
    original_video: Path,
    music_wav: Path,
    turkish_vocal_wav: Path,
    out_video: Path,
    music_db: float = -3.0,
    voice_db: float = 0.0,
):
    # Use a per-job mixed file inside the music_wav's directory (work_dir),
    # NOT a shared name in OUTPUT_DIR (concurrent jobs collide!).
    mixed_wav = music_wav.parent / "mixed_audio.wav"
    # Mix two tracks with ffmpeg
    _run([
        FFMPEG_BIN, "-y",
        "-i", str(music_wav),
        "-i", str(turkish_vocal_wav),
        "-filter_complex",
        f"[0:a]volume={music_db}dB[m];[1:a]volume={voice_db}dB[v];[m][v]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map", "[a]",
        str(mixed_wav),
    ])
    # Mux into video (re-encode audio to AAC for max MP4 compatibility)
    _run([
        FFMPEG_BIN, "-y",
        "-i", str(original_video),
        "-i", str(mixed_wav),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(out_video),
    ])
    return out_video


# ------------------------------------------------------------------
# Pipeline orchestrator
# ------------------------------------------------------------------
def get_video_duration(video_path: Path) -> float:
    out = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def run_pipeline(
    job_id: str,
    video_path: Path,
    work_dir: Path,
    out_video: Path,
    progress_cb: Callable[[str, int, Optional[str]], None],
    voice: str = TTS_VOICE,
    language: Optional[str] = "auto",
) -> Dict:
    """Run the full pipeline. progress_cb(stage, percent, message).

    Args:
        language: ISO-639-1 code (zh, vi, en, ko, ja, ...) or "auto" for detection.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    progress_cb("extract", 5, "Videodan ses çıkarılıyor")
    audio_wav = extract_audio(video_path, work_dir / "audio.wav")
    duration = get_video_duration(video_path)

    progress_cb("separate", 15, "Vokal ve müzik ayrıştırılıyor")
    stems = separate_vocals(audio_wav, work_dir)

    lang_label = "otomatik algılanıyor" if (not language or language == "auto") else language.upper()
    progress_cb("transcribe", 35, f"Konuşma metne dökülüyor ({lang_label})")
    # Only use Chinese-tech initial prompt if user explicitly chose Chinese
    initial_prompt = None
    if language == "zh":
        initial_prompt = "以下是普通话的句子。包含工程、机械、电气、软件、算法等技术术语。请使用简体字。"
    tr_result = transcribe_audio(stems["vocals"], language=language, initial_prompt=initial_prompt)
    segments = tr_result["segments"]
    detected_language = tr_result["language"]
    log.info("Transcription complete: %d segments, detected_language=%s",
             len(segments), detected_language)

    progress_cb("translate", 55, f"{_LANG_NAMES_TR.get(detected_language, detected_language)} → Türkçe çevriliyor")
    segments = translate_segments(segments, source_lang=detected_language)

    progress_cb("tts", 75, "Türkçe seslendirme oluşturuluyor")
    turkish_vocal = synthesize_turkish_track(segments, work_dir, duration, voice=voice)

    progress_cb("mux", 90, "Video birleştiriliyor")
    mix_and_mux(video_path, stems["music"], turkish_vocal, out_video)

    progress_cb("done", 100, "Tamamlandı")
    return {
        "duration": duration,
        "detected_language": detected_language,
        "segments": [
            {"id": s["id"], "start": s["start"], "end": s["end"],
             "text_src": s.get("text_src") or s.get("text_zh", ""),
             "text_tr": s.get("text_tr", "")}
            for s in segments
        ],
        "output": str(out_video),
    }
