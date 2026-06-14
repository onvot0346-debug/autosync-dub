"""
Google Gemini API kullanarak cok dilli dublaj cevirisi yapan ana servis.
Bu dosya projenin diger kisimlariyla cakismamasi icin orijinal fonksiyon yapisini korur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import List, Dict

# Google Generative AI resmi kutuphanesini kullaniyoruz
import google.generativeai as genai

log = logging.getLogger("dubbing.gpt_translator")

# Gemini'a ceviri kurallarini ve teknik HVAC terimlerini ogrettigimiz sistem talimati
SYSTEM_PROMPT_TEMPLATE = """You are a professional simultaneous-interpretation translator from {source_language_name} to {target_language_name}, specialized in video dubbing for technical / repair / HVAC content.

You will receive an array of transcribed segments from a {source_language_name} video. Each segment has:
  - id: integer
  - start: seconds (float)
  - end: seconds (float)
  - text_src: the original {source_language_name} (may contain ASR / transcription errors — fix them using context!)

Your task: produce a fluent, natural, high-quality {target_language_name} translation suitable for spoken voice-over.

CRITICAL RULES:
1. **Use the WHOLE transcript as context.** Disambiguate words and fix obvious ASR mistakes using surrounding context.

2. **DOMAIN — HVAC / AC repair / refrigeration / appliance repair / electronics / mechanics.**
   Translate technical / repair terms using CANONICAL {target_language_name} equivalents (e.g. if target is Turkish: klima/AC, kompresör, kondenser, evaporatör, voltaj, kondansatör, sigorta, röle, ana kart etc.). Pick the canonical professional term in the target language.

3. **Match speaking duration.** Each target sentence's character count should be close to the spoken duration; don't add filler.
4. **Natural target language.** Idiomatic, grammatically correct, proper punctuation, repair-shop register suitable for spoken voice-over.
5. **Numbers, units, model codes:** keep as-is (e.g. "R32", "220V", "5A", "1.5 ton").
6. **Brand / part numbers / people / places:** keep original spelling unless a well-known local form exists.
7. **Output JSON ONLY.** No prose. No markdown. No code fences.

OUTPUT FORMAT (return EXACTLY this JSON structure):
{{
  "segments": [
    {{"id": 0, "text_tr": "..."}},
    {{"id": 1, "text_tr": "..."}},
    ...
  ]
}}

(The field is named `text_tr` for historical compatibility; it must contain the {target_language_name} translation.)

If a segment is empty / pure noise, set text_tr to "".
"""

_LANG_NAME_MAP = {
    "zh": "Chinese (Mandarin)", "vi": "Vietnamese", "en": "English",
    "ja": "Japanese", "ko": "Korean", "ru": "Russian", "ar": "Arabic",
    "fa": "Persian", "hi": "Hindi", "id": "Indonesian", "th": "Thai",
    "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian",
    "tr": "Turkish",
}

def _source_language_name(code: str) -> str:
    if not code or code == "auto":
        return "the source language (auto-detected)"
    return _LANG_NAME_MAP.get(code, code)

def _target_language_name(code: str) -> str:
    return _LANG_NAME_MAP.get(code or "tr", "Turkish")

def _build_user_payload(segments: List[Dict]) -> str:
    minimal = [
        {"id": s["id"], "start": round(s["start"], 2), "end": round(s["end"], 2),
         "text_src": s.get("text_src") or s.get("text_zh", "")}
        for s in segments
    ]
    return json.dumps({"segments": minimal}, ensure_ascii=False)

def _strip_code_fences(text: str) -> str:
    text = text.strip()
    # Kodun bölünmesini önlemek için tırnak işaretlerini hex formatında yazıyoruz
    uc_tirnak = "\x60\x60\x60"
    if text.startswith(uc_tirnak):
        text = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", text)
        text = re.sub(r"\s*\x60\x60\x60\s*$", "", text)
    return text.strip()

def _parse_response(raw: str) -> Dict[int, str]:
    cleaned = _strip_code_fences(raw)
    if not cleaned.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            cleaned = m.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Gemini JSON formatinda yanit vermedi: %s | head=%r", e, cleaned[:200])
        return {}
    out = {}
    for s in data.get("segments", []):
        try:
            out[int(s["id"])] = (s.get("text_tr") or "").strip()
        except Exception:
            continue
    return out

async def translate_with_gpt4o(segments: List[Dict], source_lang: str = "auto",
                                target_lang: str = "tr") -> List[Dict]:
    """Segment dizisini Gemini API kullanarak hedef dile cevirir.
    Diger kodlarin bozulmamasi icin orijinal fonksiyon ismi korunmustur.
    """
    if not segments:
        return segments

    # Kendi .env dosyandaki Gemini API anahtarini sistemden cekiyoruz
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY bulunamadi - ceviri islemi atlandi")
        return segments

    # Gemini yapilandirmasi yapiliyor
    genai.configure(api_key=api_key)

    system_msg = SYSTEM_PROMPT_TEMPLATE.format(
        source_language_name=_source_language_name(source_lang),
        target_language_name=_target_language_name(target_lang),
    )

    payload = _build_user_payload(segments)

    # 1.5 Flash modeli hızlı ve ekonomiktir
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_msg
    )

    try:
        # Sunucunun donmamasi icin asenkron thread havuzunda calistiriyoruz
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                payload,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )
        )
        raw = response.text
    except Exception as e:
        log.exception("Gemini ceviri istegi basarisiz oldu: %s", e)
        return segments

    mapping = _parse_response(raw)
    if not mapping:
        log.warning("Gemini'dan gecersiz yanit alindi - orijinal altyazilar korundu")
        return segments

    # Cevrilen segmentleri mevcut listeye yaziyoruz
    for s in segments:
        new_tr = mapping.get(s["id"])
        if new_tr:
            s["text_tr"] = new_tr
            
    return segments
