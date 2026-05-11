"""
HVAC / klima / soğutma / tamir / elektronik / mekanik terim sözlüğü.
GPT-4o çevirisi tutarsız davranırsa Türkçe çıktı içinde
yanlış kalıp varsa düzeltir. Kaynak dil bağımsızdır
(post-process Türkçe metnin içinde tarama).

GLOSSARY_TR_FIX: Türkçe çıktıdaki yaygın HATALI kalıpları doğru kalıba çevirir.
"""

# Common mistranslations of HVAC / repair / electrical terms in Turkish that
# slip through translators. Keys = wrong/odd, values = correct canonical Turkish.
# All are case-insensitive whole-word replacements where possible.
GLOSSARY_TR_FIX = {
    # HVAC
    "hava klimatizatör": "klima",
    "klima aleti": "klima",
    "klima cihazı": "klima",
    "sıkıştırıcı": "kompresör",
    "yoğunlaştırıcı": "kondenser",
    "buharlaştırıcı": "evaporatör",
    "genişleme valfı": "genleşme valfi",
    "kılcal tüp": "kılcal boru",
    "kuru filtre": "filtre drayer",
    "kurutucu filtre": "filtre drayer",
    "soğutucu sıvı": "soğutucu akışkan",
    "soğutucu madde": "soğutucu akışkan",
    "soğutucu gaz": "soğutucu akışkan",
    "soğutkan": "soğutucu akışkan",
    "buz dolabı": "buzdolabı",
    "buz makinesi": "buz makinesi",  # keep
    "donanma": "soğutma",
    "vakumlama": "vakum çekme",
    "vakum çekmek": "vakum çekme",
    "şarj etme gazı": "gaz şarjı",
    "gaz şarj etmek": "gaz şarjı yapmak",
    "gaz doldurma": "gaz şarjı",
    "gas dolumu": "gaz şarjı",
    "freon": "soğutucu akışkan",
    "manifold ölçer": "manometre",
    "basınç ölçer": "manometre",
    "kaçak testi": "sızdırmazlık testi",

    # Electrical
    "ana levha": "ana kart",
    "ana tahta": "ana kart",
    "anakart": "ana kart",
    "kapasitör": "kondansatör",
    "kondansör": "kondansatör",
    "kondansator": "kondansatör",
    "konaktör": "kontaktör",
    "rölaj": "röle",
    "sigortacı": "sigorta",
    "elektrik akımı": "akım",
    "elektrik voltajı": "voltaj",
    "topraklama hattı": "toprak hattı",
    "kısa devre yapmak": "kısa devre yapmak",  # keep
    "voltmetre": "voltmetre",   # keep
    "avo metre": "avometre",
    "çoklu metre": "multimetre",
    "evrensel ölçer": "multimetre",

    # Mechanical / appliance
    "rulmanlar": "rulmanlar",   # keep
    "yatak": "rulman",          # context-dependent; only fix if clearly bearing
    # ⚠ "yatak" left as-is intentionally — fixing could break valid "yatak (bed)"
    "fan motoru": "fan motoru",
    "vantilatör": "fan",
    "pervane": "fan",
    "kayış": "kayış",
    "yağlama maddesi": "yağ",
    "tornavidalama": "vidalama",

    # General units / format
    "voltlar": "volt",
    "amperler": "amper",
    "wattlar": "watt",
}


def apply_glossary(zh_text: str, tr_text: str) -> str:
    """Post-process Turkish translation to fix common mistranslations of
    HVAC / repair / electrical terms.

    Args:
        zh_text: original source-language text (unused — kept for backward compat).
        tr_text: GPT-4o or fallback translator output in Turkish.
    Returns:
        Corrected Turkish text.
    """
    if not tr_text:
        return tr_text
    out = tr_text
    # Case-sensitive simple replace — generally safer for Turkish
    # (avoids damaging vowel harmony in suffixes).
    for wrong, correct in GLOSSARY_TR_FIX.items():
        if wrong in out:
            out = out.replace(wrong, correct)
        # Capitalized first-letter form
        wrong_cap = wrong[:1].upper() + wrong[1:]
        if wrong_cap in out:
            out = out.replace(wrong_cap, correct[:1].upper() + correct[1:])
    return out
