"""
Context-aware Chinese -> Turkish translator using OpenAI GPT-4o
via emergentintegrations universal LLM key.

Key benefits over per-segment translation:
  - Whole transcript passed in one call (model uses surrounding context to
    disambiguate, fix transcription errors, and produce coherent Turkish).
  - Engineering / technical terminology preserved.
  - Natural, fluent Turkish (not literal word-for-word).
  - Lengths kept close to originals so time-stretch stays in clean range.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import List, Dict

from emergentintegrations.llm.chat import LlmChat, UserMessage

log = logging.getLogger("dubbing.gpt_translator")


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
   Translate technical / repair terms using CANONICAL {target_language_name} equivalents (klima/AC/Klimaanlage/climatiseur; kompresör/compressor/Kompressor/compresseur; kondenser/condenser/Kondensator/condenseur; evaporatör/evaporator/Verdampfer/évaporateur; voltaj/voltage/Spannung/tension; kondansatör/capacitor/Kondensator/condensateur; sigorta/fuse/Sicherung/fusible; röle/relay/Relais/relais; ana kart/mainboard/Hauptplatine/carte mère; etc.). Pick the canonical professional term in the target language.

3. **Match speaking duration.** Each target sentence's character count should be close to the spoken duration; don't add filler.
4. **Natural target language.** Idiomatic, grammatically correct, proper punctuation, repair-shop register.
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
    """Compact JSON payload to feed into GPT-4o."""
    minimal = [
        {"id": s["id"], "start": round(s["start"], 2), "end": round(s["end"], 2),
         "text_src": s.get("text_src") or s.get("text_zh", "")}
        for s in segments
    ]
    return json.dumps({"segments": minimal}, ensure_ascii=False)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    # remove ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _parse_response(raw: str) -> Dict[int, str]:
    """Return {segment_id: turkish_text}."""
    cleaned = _strip_code_fences(raw)
    # If model accidentally wrapped JSON in extra prose, try to find the {...} block
    if not cleaned.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            cleaned = m.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("GPT-4o returned non-JSON: %s | head=%r", e, cleaned[:200])
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
    """In-place enrich segments with `text_tr` produced by GPT-4o.
    On failure: leave existing text_tr untouched (caller should fall back).
    `source_lang` / `target_lang` are ISO-639-1 codes (zh, vi, tr, de, fr, ...).
    """
    if not segments:
        return segments
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        log.warning("EMERGENT_LLM_KEY missing — skipping GPT-4o translation")
        return segments

    system_msg = SYSTEM_PROMPT_TEMPLATE.format(
        source_language_name=_source_language_name(source_lang),
        target_language_name=_target_language_name(target_lang),
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"dubbing-translate-{uuid.uuid4()}",
        system_message=system_msg,
    ).with_model("openai", "gpt-4o")

    payload = _build_user_payload(segments)
    msg = UserMessage(text=payload)
    try:
        raw = await chat.send_message(msg)
    except Exception as e:
        log.exception("GPT-4o translation request failed: %s", e)
        return segments

    mapping = _parse_response(raw)
    if not mapping:
        log.warning("GPT-4o returned empty / unparseable response — keeping existing translations")
        return segments

    for s in segments:
        new_tr = mapping.get(s["id"])
        if new_tr:
            s["text_tr"] = new_tr
    return segments
