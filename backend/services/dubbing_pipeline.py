"""
Cok dilli video dublaj akisini (pipeline) yoneten ana servis dosyasi.
Gecici dosyalari otomatik temizleyerek sunucu disk alanini korur.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
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
# Konfigurasyon
# ------------------------------------------------------------------
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "medium")
TTS_VOICE = os.environ.get("TTS_VOICE", "tr-TR-AhmetNeural")


# ------------------------------------------------------------------
# ffmpeg ve ffprobe araclarini bulma fonksiyonu
# ------------------------------------------------------------------
def _resolve_ffmpeg_binaries():
    sys_ffmpeg = shutil.which("ffmpeg")
    sys_ffprobe = shutil.which("ffprobe")
    if sys_ffmpeg and sys_ffprobe:
        return sys_ffmpeg, sys_ffprobe
    try:
        from static_ffmpeg import run as _sf
        ff, fp = _sf.get_or_fetch_platform_executables_else_raise()
        os.environ["PATH"] = os.path.dirname(ff) + os.pathsep + os.environ.get("PATH", "")
        return ff, fp
    except Exception as e:
        log.error("ffmpeg/ffprobe cozumlenemedi: %s", e)
        return "ffmpeg", "ffprobe"


FFMPEG_BIN, FFPROBE_BIN = _resolve_ffmpeg_binaries()
log.info(f"Kullanilan ffmpeg: {FFMPEG_BIN}")
log.info(f"Kullanilan ffprobe: {FFPROBE_BIN}")

try:
    from pydub import AudioSegment as _AS
    _AS.converter = FFMPEG_BIN
    _AS.ffmpeg = FFMPEG_BIN
    _AS.ffprobe = FFPROBE_BIN
except Exception:
    pass

_whisper_model = None


# ------------------------------------------------------------------
# Desteklenen kaynak diller
# ------------------------------------------------------------------
SUPPORTED_LANGUAGES: List[Dict[str, str]] = [
    {"code": "auto", "name": "Otomatik Algila"},
    {"code": "zh", "name": "Cince"},
    {"code": "vi", "name": "Vietnamca"},
    {"code": "en", "name": "Ingilizce"},
    {"code": "ja", "name": "Japonca"},
    {"code": "ko", "name": "Korece"},
    {"code": "ru", "name": "Rusca"},
    {"code": "ar", "name": "Arapca"},
    {"code": "fa", "name": "Farsca"},
    {"code": "hi", "name": "Hintce"},
    {"code": "id", "name": "Endonezce"},
    {"code": "th", "name": "Tayca"},
    {"code": "fr", "name": "Fransizca"},
    {"code": "de", "name": "Almanca"},
    {"code": "es", "name": "Ispanyolca"},
    {"code": "it", "name": "Italyanca"},
    {"code": "pt", "name": "Portekizce"},
    {"code": "nl", "name": "Hollandaca"},
    {"code": "pl", "name": "Lehce"},
    {"code": "uk", "name": "Ukraynaca"},
    {"code": "tr", "name": "Turkce"},
]
_LANG_NAMES_TR = {lng["code"]: lng["name"] for lng in SUPPORTED_LANGUAGES}


# ------------------------------------------------------------------
# Hedef diller ve Edge-TTS ses kataloglari
# ------------------------------------------------------------------
TARGET_VOICES: Dict[str, List[Dict[str, str]]] = {
    "tr": [
        {"id": "tr-TR-AhmetNeural", "name": "Ahmet (Erkek)", "gender": "male"},
        {"id": "tr-TR-EmelNeural",  "name": "Emel (Kadin)",  "gender": "female"},
    ],
    "de": [
        {"id": "de-DE-ConradNeural", "name": "Conrad (Erkek)", "gender": "male"},
        {"id": "de-DE-KatjaNeural",  "name": "Katja (Kadin)",  "gender": "female"},
    ],
    "fr": [
        {"id": "fr-FR-HenriNeural",  "name": "Henri (Erkek)",  "gender": "male"},
        {"id": "fr-FR-DeniseNeural", "name": "Denise (Kadin)", "gender": "female"},
    ],
    "en": [
        {"id": "en-US-GuyNeural",   "name": "Guy (Erkek US)",   "gender": "male"},
        {"id": "en-US-JennyNeural", "name": "Jenny (Kadin US)", "gender": "female"},
        {"id": "en-GB-RyanNeural",  "name": "Ryan (Erkek UK)",  "gender": "male"},
    ],
    "es": [
        {"id": "es-ES-AlvaroNeural",  "name": "Alvaro (Erkek)",  "gender": "male"},
        {"id": "es-ES-ElviraNeural",  "name": "Elvira (Kadin)",  "gender": "female"},
    ],
    "it": [
        {"id": "it-IT-DiegoNeural", "name": "Diego (Erkek)", "gender": "male"},
        {"id": "it-IT-ElsaNeural",  "name": "Elsa (Kadin)",  "gender": "female"},
    ],
    "pt": [
        {"id": "pt-PT-DuarteNeural", "name": "Duarte (Erkek)", "gender": "male"},
        {"id": "pt-BR-AntonioNeural","name": "Antonio (Erkek BR)","gender": "male"},
    ],
    "ru": [{"id": "ru-RU-DmitryNeural", "name": "Dmitry (Erkek)", "gender": "male"}],
    "ja": [{"id": "ja-JP-KeitaNeural", "name": "Keita (Erkek)", "gender": "male"}],
    "ko": [{"id": "ko-KR-InJoonNeural", "name": "InJoon (Erkek)", "gender": "male"}],
    "zh": [{"id": "zh-CN-YunxiNeural", "name": "Yunxi (Erkek)", "gender": "male"}],
    "ar": [{"id": "ar-SA-HamedNeural", "name": "Hamed (Erkek)", "gender": "male"}],
    "nl": [{"id": "nl-NL-MaartenNeural", "name": "Maarten (Erkek)", "gender": "male"}],
    "pl": [{"id": "pl-PL-MarekNeural", "name": "Marek (Erkek)", "gender": "male"}],
    "vi": [{"id": "vi-VN-NamMinhNeural", "name": "NamMinh (Erkek)", "gender": "male"}],
}

TARGET_LANGUAGES: List[Dict[str, str]] = [
    {"code": "tr", "name": "Turkce",         "english": "Turkish"},
    {"code": "de", "name": "Almanca",        "english": "German"},
    {"code": "fr", "name": "Fransizca",      "english": "French"},
    {"code": "en", "name": "Ingilizce",      "english": "English"},
    {"code": "es", "name": "Ispanyolca",     "english": "Spanish"},
    {"code": "it", "name": "Italyanca",      "english": "Italian"},
    {"code": "pt", "name": "Portekizce",     "english": "Portuguese"},
    {"code": "ru", "name": "Rusca",          "english": "Russian"},
    {"code": "ja", "name": "Japonca",        "english": "Japanese"},
    {"code": "ko", "name": "Korece",         "english": "Korean"},
    {"code": "zh", "name": "Cince",          "english": "Chinese (Simplified)"},
    {"code": "ar", "name": "Arapca",         "english": "Arabic"},
    {"code": "nl", "name": "Hollandaca",     "english": "Dutch"},
    {"code": "pl", "name": "Lehce",          "english": "Polish"},
    {"code": "vi", "name": "Vietnamca",      "english": "Vietnamese"},
]
TARGET_LANG_CODES = {lng["code"] for lng in TARGET_LANGUAGES}


def default_voice_for(target_lang: str) -> str:
    voices = TARGET_VOICES.get(target_lang)
    if voices:
        return voices[0]["id"]
    return TARGET_VOICES["tr"][0]["id"]


def voices_for(target_lang: str) -> List[Dict[str, str]]:
    return TARGET_VOICES.get(target_lang, TARGET_VOICES["tr"])


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        log.info(f"Whisper modeli yukleniyor: {WHISPER_MODEL_NAME}")
        _whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    return _whisper_model


# ------------------------------------------------------------------
# Komut calistirici yardimci fonksiyon
# ------------------------------------------------------------------
def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    log.info("CALISTIRILIYOR: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, check=True, capture_output=True, **kwargs)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-1500:]
        log.error("Komut basarisiz oldu (Kod: %s): %s\nHATA DETAYI:\n%s",
                  e.returncode, " ".join(cmd), stderr_tail)
        raise


# ------------------------------------------------------------------
# Adim 1 — Videodan orijinal sesi cikarma
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
# Adim 2 — Vokal ve arka plan muzik sesini ayirma (Demucs)
# ------------------------------------------------------------------
def separate_vocals(input_wav: Path, work_dir: Path) -> Dict[str, Path]:
    out_dir = work_dir / "demucs"
    out_dir.mkdir(parents=True, exist_ok=True)

    runner = Path(__file__).parent / "demucs_runner.py"
    py_exec = sys.executable or "python"
    try:
        _run([
            py_exec, str(runner),
            "--two-stems", "vocals",
            "-n", "htdemucs",
            "-o", str(out_dir),
            str(input_wav),
        ])
        stem = input_wav.stem
        produced = out_dir / "htdemucs" / stem
        vocals = produced / "vocals.wav"
        music = produced / "no_vocals.wav"
        if vocals.exists() and music.exists():
            log.info("Demucs basariyla tamamlandi: %s", input_wav.name)
            return {"vocals": vocals, "music": music}
        raise FileNotFoundError("Demucs cikti dosyalari bulunamadi")
    except Exception as e:
        log.warning(f"Demucs hata verdi ({e}). Orijinal ses varsayilan olarak kullaniliyor.")
        vocals = work_dir / "vocals.wav"
        music = work_dir / "music.wav"
        _run([FFMPEG_BIN, "-y", "-i", str(input_wav), "-c:a", "pcm_s16le", str(vocals)])
        _run([
            FFMPEG_BIN, "-y", "-i", str(input_wav),
            "-af", "volume=-10dB",
            "-c:a", "pcm_s16le", str(music),
        ])
        return {"vocals": vocals, "music": music}


# ------------------------------------------------------------------
# Adim 3 — Whisper ile sesi metne dokme
# ------------------------------------------------------------------
def transcribe_audio(vocals_wav: Path, language: Optional[str] = None,
                    initial_prompt: Optional[str] = None) -> Dict:
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


# Geriye donuk uyumluluk takma adi
def transcribe_chinese(vocals_wav: Path) -> List[Dict]:
    return transcribe_audio(vocals_wav, language="zh")["segments"]


# ------------------------------------------------------------------
# Adim 4 — Gemini ile ceviriyi yapma (Yedek olarak Google Translate)
# ------------------------------------------------------------------
_DEEP_LANG = {
    "zh": "zh-CN", "vi": "vi", "en": "en", "ko": "ko", "ja": "ja",
    "ru": "ru", "ar": "ar", "fr": "fr", "de": "de", "es": "es",
    "it": "it", "pt": "pt", "hi": "hi", "id": "id", "th": "th",
    "tr": "tr", "nl": "nl", "pl": "pl", "fa": "fa", "uk": "uk",
}


def translate_segments(segments: List[Dict], source_lang: str = "auto",
                       target_lang: str = "tr") -> List[Dict]:
    if not segments:
        return segments

    for s in segments:
        s.setdefault("text_tr", "")

    used_gpt = False
    try:
        # translate_with_gpt4o fonksiyonumuz artik arka planda Gemini API kullanir
        asyncio.run(translate_with_gpt4o(segments, source_lang=source_lang,
                                         target_lang=target_lang))
        used_gpt = any(s.get("text_tr") for s in segments)
        log.info("Gemini translation: %s segment cevrildi (%s->%s)",
                 sum(1 for s in segments if s.get("text_tr")), source_lang, target_lang)
    except Exception as e:
        log.warning("Gemini cevirici hata verdi: %s", e)

    # Gemini'in bos biraktigi yerler olursa Google Translate ile tamamliyoruz
    missing = [s for s in segments if not s.get("text_tr") and (s.get("text_src") or s.get("text_zh", "")).strip()]
    if missing:
        log.info("Eksik kalan %d segment icin ucretsiz Google Translate kullaniliyor", len(missing))
        deep_src = _DEEP_LANG.get(source_lang, "auto")
        deep_tgt = _DEEP_LANG.get(target_lang, "tr")
        try:
            translator = GoogleTranslator(source=deep_src, target=deep_tgt)
        except Exception:
            translator = GoogleTranslator(source="auto", target=deep_tgt)
        for seg in missing:
            src_text = seg.get("text_src") or seg.get("text_zh", "")
            try:
                tr = translator.translate(src_text) or ""
            except Exception as e:
                log.warning(f"Google Translate ceviri hatasi: {e}")
                tr = ""
            seg["text_tr"] = tr

    # HVAC terimler sözlügünü sadece hedef dil Turkce ise uygula
    if target_lang == "tr":
        for seg in segments:
            seg["text_tr"] = apply_glossary(
                seg.get("text_src") or seg.get("text_zh", ""),
                seg.get("text_tr", ""),
            )

    log.info("Ceviri islemi tamamlandi (gemini_kullanildi=%s, %s->%s)",
             used_gpt, source_lang, target_lang)
    return segments


# ------------------------------------------------------------------
# Adim 5 — Edge-TTS ses sentezi ve hiza uydurma (Time-stretch)
# ------------------------------------------------------------------
async def _tts_one(text: str, out_path: Path, voice: str = TTS_VOICE):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+0%")
    await communicate.save(str(out_path))


def _time_stretch_to_duration(in_wav: Path, target_seconds: float, out_wav: Path):
    y, sr = librosa.load(str(in_wav), sr=None, mono=True)
    cur_dur = len(y) / sr
    if cur_dur <= 0.05 or target_seconds <= 0.05:
        sf.write(str(out_wav), y, sr)
        return
    rate = cur_dur / target_seconds
    rate = max(0.7, min(1.6, rate))
    try:
        y_stretched = librosa.effects.time_stretch(y, rate=rate)
    except Exception:
        y_stretched = y
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
    seg_dir = work_dir / "tts_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    async def _gen_all():
        for seg in segments:
            text = seg.get("text_tr") or ""
            seg_mp3 = seg_dir / f"seg_{seg['id']:04d}.mp3"
            if not text.strip():
                AudioSegment.silent(duration=10).export(seg_mp3, format="mp3")
            else:
                await _tts_one(text, seg_mp3, voice=voice)
            seg["_tts_mp3"] = seg_mp3
    asyncio.run(_gen_all())

    sr_target = 44100
    final = AudioSegment.silent(duration=int(total_duration_sec * 1000))
    for seg in segments:
        dur = max(0.1, seg["end"] - seg["start"])
        seg_wav = seg_dir / f"seg_{seg['id']:04d}.wav"
        AudioSegment.from_file(seg["_tts_mp3"]).set_frame_rate(sr_target).set_channels(1).export(seg_wav, format="wav")
        stretched = seg_dir / f"seg_{seg['id']:04d}_fit.wav"
        _time_stretch_to_duration(seg_wav, dur, stretched)
        piece = AudioSegment.from_wav(stretched)
        final = final.overlay(piece, position=int(seg["start"] * 1000))

    out_path = work_dir / "turkish_vocal.wav"
    final.set_frame_rate(sr_target).set_channels(2).export(out_path, format="wav")
    return out_path


# ------------------------------------------------------------------
# Adim 6 — Ses kanallarini birlestirme ve videoya gomme (Mux)
# ------------------------------------------------------------------
def mix_and_mux(
    original_video: Path,
    music_wav: Path,
    turkish_vocal_wav: Path,
    out_video: Path,
    music_db: float = -3.0,
    voice_db: float = 0.0,
    audio_mode: str = "dub_with_music",
):
    mixed_wav = music_wav.parent / "mixed_audio.wav"

    if audio_mode == "dub_only":
        _run([
            FFMPEG_BIN, "-y", "-i", str(turkish_vocal_wav),
            "-filter:a", f"volume={voice_db}dB",
            "-ar", "44100", "-ac", "2",
            str(mixed_wav),
        ])
    else:
        _run([
            FFMPEG_BIN, "-y",
            "-i", str(music_wav),
            "-i", str(turkish_vocal_wav),
            "-filter_complex",
            f"[0:a]volume={music_db}dB[m];[1:a]volume={voice_db}dB[v];[m][v]amix=inputs=2:duration=longest:dropout_transition=0[a]",
            "-map", "[a]",
            str(mixed_wav),
        ])

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
# Gecici Dosyalari Temizleme (Auto-Delete) Yardimci Fonksiyonu
# ------------------------------------------------------------------
def cleanup_temp_files(work_dir: Path, out_video: Path):
    """Render disk alanini korumak icin gecici WAV ve MP3 dosyalarini tamamen temizler."""
    try:
        for item in work_dir.iterdir():
            if item.is_file():
                # Nihai video dosyasini kesinlikle silmiyoruz!
                if item.resolve() != out_video.resolve():
                    item.unlink()
            elif item.is_dir():
                # Eger cikti videosu bu klasorun icindeyse klasoru silme (guvenlik onlemi)
                if not (out_video.resolve() == item.resolve() or out_video.resolve() in item.resolve().parents):
                    shutil.rmtree(item)
        log.info(f"Gecici calisma dosyaları temizlendi: {work_dir}")
    except Exception as e:
        log.warning(f"Gecici dosyalar temizlenirken hata olustu: {e}")


# ------------------------------------------------------------------
# Ana Akis Yoneticisi (Orchestrator)
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
    target_language: str = "tr",
    audio_mode: str = "dub_with_music",
) -> Dict:
    work_dir.mkdir(parents=True, exist_ok=True)

    progress_cb("extract", 5, "Videodan ses cikariliyor")
    audio_wav = extract_audio(video_path, work_dir / "audio.wav")
    duration = get_video_duration(video_path)

    if audio_mode == "dub_with_original":
        progress_cb("separate", 15, "Orijinal ses kullaniliyor (ayristirma atlandi)")
        original_lower = work_dir / "music.wav"
        _run([
            FFMPEG_BIN, "-y", "-i", str(audio_wav),
            "-af", "volume=-10dB", "-c:a", "pcm_s16le", str(original_lower),
        ])
        stems = {"vocals": audio_wav, "music": original_lower}
    elif audio_mode == "dub_only":
        progress_cb("separate", 15, "Vokal ayristirma atlandi (sadece dublaj modu)")
        stems = {"vocals": audio_wav, "music": audio_wav}
    else:
        progress_cb("separate", 15, "Vokal ve muzik ayristiriliyor (Demucs)")
        stems = separate_vocals(audio_wav, work_dir)

    lang_label = "otomatik algilaniyor" if (not language or language == "auto") else language.upper()
    progress_cb("transcribe", 35, f"Konusma metne dokuluyor ({lang_label})")
    initial_prompt = None
    if language == "zh":
        initial_prompt = "以下是普通话的句子。包含工程、机械、电气、软件、算法等技术术语。请使用简体字。"
    tr_result = transcribe_audio(stems["vocals"], language=language, initial_prompt=initial_prompt)
    segments = tr_result["segments"]
    detected_language = tr_result["language"]
    log.info("Whisper desifre tamamlandi: %d segment, algilanan_dil=%s",
             len(segments), detected_language)

    progress_cb("translate", 55, f"{_LANG_NAMES_TR.get(detected_language, detected_language)} -> {_LANG_NAMES_TR.get(target_language, target_language)} cevriliyor")
    segments = translate_segments(segments, source_lang=detected_language,
                                  target_lang=target_language)

    progress_cb("tts", 75, "Seslendirme olusturuluyor")
    turkish_vocal = synthesize_turkish_track(segments, work_dir, duration, voice=voice)

    progress_cb("mux", 90, "Video birlestiriliyor")
    mix_and_mux(video_path, stems["music"], turkish_vocal, out_video,
                audio_mode=audio_mode)

    # Render disk alanini korumak icin devasa WAV ve MP3 gecici dosyalarini hemen temizliyoruz
    cleanup_temp_files(work_dir, out_video)

    progress_cb("done", 100, "Tamamlandi")
    return {
        "duration": duration,
        "detected_language": detected_language,
        "target_language": target_language,
        "audio_mode": audio_mode,
        "segments": [
            {"id": s["id"], "start": s["start"], "end": s["end"],
             "text_src": s.get("text_src") or s.get("text_zh", ""),
             "text_tr": s.get("text_tr", "")}
            for s in segments
        ],
        "output": str(out_video),
    }
