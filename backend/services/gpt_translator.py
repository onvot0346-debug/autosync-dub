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


SYSTEM_PROMPT = """You are a professional simultaneous-interpretation translator for Chinese (Mandarin) to Turkish video dubbing.

You will receive an array of transcribed segments from a Chinese video. Each segment has:
  - id: integer
  - start: seconds (float)
  - end: seconds (float)
  - text_zh: the original Chinese (may contain ASR / transcription errors — fix them using context!)

Your task: produce a fluent, natural, high-quality Turkish translation suitable for spoken voice-over.

CRITICAL RULES:
1. **Use the WHOLE transcript as context.** Disambiguate words, fix obvious ASR mistakes (e.g. 事件 vs 世界 — pick the meaning that fits the surrounding context).
2. **Preserve technical / engineering terminology.** Use canonical Turkish equivalents:
   工程师→mühendis, 算法→algoritma, 数据库→veritabanı, 神经网络→sinir ağı,
   人工智能→yapay zeka, 机械工程→makine mühendisliği, 电气工程→elektrik mühendisliği,
   软件→yazılım, 服务器→sunucu, 传感器→sensör, 电压→voltaj, 扭矩→tork,
   公差→tolerans, 螺栓→cıvata, 焊接→kaynak, 混凝土→beton, etc.
3. **Match speaking duration.** Keep each Turkish sentence's character count within ±25% of what would naturally be spoken in the original duration. Don't add filler; trim where Turkish is more compact.
4. **Natural Turkish.** Use idiomatic phrasing, correct grammar (vowel harmony, agglutination), proper punctuation. Avoid robotic / literal translations.
5. **Tone:** professional, clear, suitable for narration (educational / engineering / vlog content).
6. **Numbers & units:** keep numbers; convert units only if the original says so. Use Turkish number formatting.
7. **Output JSON ONLY.** No prose. No markdown. No code fences.

OUTPUT FORMAT (return EXACTLY this JSON structure):
{
  "segments": [
    {"id": 0, "text_tr": "..."},
    {"id": 1, "text_tr": "..."},
    ...
  ]
}

If a segment is empty or noise, set text_tr to "".
"""


def _build_user_payload(segments: List[Dict]) -> str:
    """Compact JSON payload to feed into GPT-4o."""
    minimal = [
        {"id": s["id"], "start": round(s["start"], 2), "end": round(s["end"], 2),
         "text_zh": s["text_zh"]}
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


async def translate_with_gpt4o(segments: List[Dict]) -> List[Dict]:
    """In-place enrich segments with `text_tr` produced by GPT-4o.
    On failure: leave existing text_tr untouched (caller should fall back)."""
    if not segments:
        return segments
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        log.warning("EMERGENT_LLM_KEY missing — skipping GPT-4o translation")
        return segments

    chat = LlmChat(
        api_key=api_key,
        session_id=f"dubbing-translate-{uuid.uuid4()}",
        system_message=SYSTEM_PROMPT,
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
