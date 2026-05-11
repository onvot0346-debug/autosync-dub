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


SYSTEM_PROMPT_TEMPLATE = """You are a professional simultaneous-interpretation translator from {source_language_name} to Turkish, specialized in video dubbing for technical / repair / HVAC content.

You will receive an array of transcribed segments from a {source_language_name} video. Each segment has:
  - id: integer
  - start: seconds (float)
  - end: seconds (float)
  - text_src: the original {source_language_name} (may contain ASR / transcription errors — fix them using context!)

Your task: produce a fluent, natural, high-quality Turkish translation suitable for spoken voice-over.

CRITICAL RULES:
1. **Use the WHOLE transcript as context.** Disambiguate words and fix obvious ASR mistakes using surrounding context.

2. **DOMAIN — HVAC / AC repair / refrigeration / appliance repair / electronics / mechanics.**
   Translate the following kinds of terms with their CANONICAL Turkish equivalents:

   • HVAC / Klima:
     air conditioner / 空调 / điều hòa / エアコン / 에어컨 → klima
     refrigerator / 冰箱 / tủ lạnh / 冷蔵庫 / 냉장고 → buzdolabı
     refrigerant / 制冷剂 / 雪种 / chất làm lạnh / 冷媒 / 냉매 → soğutucu akışkan (gaz)
     R22 / R32 / R410A / R134a → keep as-is (gas codes)
     compressor / 压缩机 / máy nén / コンプレッサー / 압축기 → kompresör
     condenser / 冷凝器 / bộ ngưng tụ / 凝縮器 / 응축기 → kondenser (kondansatör değil!)
     evaporator / 蒸发器 / dàn bay hơi / 蒸発器 / 증발기 → evaporatör
     expansion valve / 膨胀阀 / van tiết lưu / 膨張弁 / 팽창밸브 → genleşme valfi
     capillary tube / 毛细管 / ống mao dẫn / キャピラリー / 모세관 → kılcal boru
     filter drier / 干燥过滤器 / phin lọc / フィルタードライヤー → filtre drayer
     copper pipe / 铜管 / ống đồng / 銅管 / 동관 → bakır boru
     gas charge / 加雪种 / 加氟 / nạp gas / ガスチャージ → gaz şarjı / gaz dolumu
     vacuum / vacuuming / 抽真空 / hút chân không / 真空引き → vakum (çekmek)
     manifold gauge / 表压 / đồng hồ áp suất / マニホールド → manometre / manifold
     leak / leak test / 漏氟 / 漏 / rò rỉ / 漏れ / 누설 → kaçak / sızıntı testi
     vacuum pump / 真空泵 / máy hút chân không / 真空ポンプ → vakum pompası
     flare / 喇叭口 / loe ống / フレア → rakor (flare) / havşalama

   • Electrical / repair:
     PCB / mainboard / 主板 / bo mạch / 基板 / 메인보드 → ana kart (PCB)
     capacitor / 电容 / tụ điện / コンデンサ / 콘덴서 → kondansatör
     resistor / 电阻 → direnç
     fuse / 保险丝 / cầu chì / ヒューズ → sigorta
     contactor / 接触器 / công tắc tơ / コンタクタ → kontaktör
     relay / 继电器 / rơ le / リレー → röle
     multimeter / 万用表 / đồng hồ vạn năng / テスター → multimetre / avometre
     voltage / 电压 / điện áp / 電圧 / 전압 → voltaj (gerilim)
     current / 电流 / dòng điện / 電流 / 전류 → akım
     resistance / 电阻 / điện trở / 抵抗 → direnç (Ω)
     ground / earth / 接地 / tiếp đất / アース → toprak / topraklama
     short circuit / 短路 / chập điện / ショート → kısa devre

   • Mechanical / appliance:
     motor / 电机 / mô tơ → motor / elektrik motoru
     fan / 风机 / 风扇 / quạt / ファン / 팬 → fan
     bearing / 轴承 / bạc đạn / ベアリング / 베어링 → rulman
     screw / 螺丝 → vida; bolt / 螺栓 → cıvata
     gasket / 垫片 / gioăng / パッキン → conta
     washing machine / 洗衣机 / máy giặt → çamaşır makinesi
     water heater / 热水器 → şofben / termosifon

3. **Match speaking duration.** Each Turkish sentence's character count should be close to the spoken duration; don't add filler.
4. **Natural Turkish.** Idiomatic, grammatically correct (vowel harmony, agglutination), proper punctuation, repair-shop register.
5. **Numbers, units, model codes:** keep as-is (e.g. "R32", "220V", "5A", "1.5 ton").
6. **Brand / part numbers / people / places:** keep original spelling unless a well-known Turkish form exists.
7. **Output JSON ONLY.** No prose. No markdown. No code fences.

OUTPUT FORMAT (return EXACTLY this JSON structure):
{{
  "segments": [
    {{"id": 0, "text_tr": "..."}},
    {{"id": 1, "text_tr": "..."}},
    ...
  ]
}}

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


async def translate_with_gpt4o(segments: List[Dict], source_lang: str = "auto") -> List[Dict]:
    """In-place enrich segments with `text_tr` produced by GPT-4o.
    On failure: leave existing text_tr untouched (caller should fall back).
    `source_lang` is an ISO-639-1 code (zh, vi, en, ...) or "auto".
    """
    if not segments:
        return segments
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        log.warning("EMERGENT_LLM_KEY missing — skipping GPT-4o translation")
        return segments

    system_msg = SYSTEM_PROMPT_TEMPLATE.format(
        source_language_name=_source_language_name(source_lang)
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
