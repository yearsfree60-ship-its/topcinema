#!/usr/bin/env python3
"""
وحدة الترجمة السياقية الاحترافية (EN→AR) — تُستورَد فقط من ocr_extraction.py
(استيراد مؤجَّل lazy داخل الدالة المستدعية، بنفس نمط استيراد paddleocr هناك،
كي لا تُثقل أي تشغيلة لا تحتاج الترجمة بزمن استيراد/فشل استيراد غير ضروري).

[قرار معماري — بعد بحث فعلي مقارن] المحرك: Gemini، لا DeepL/Google Translate
التقليدي. السبب موثَّق فعليًا بتوثيق DeepL الرسمي نفسه: معامل "context" عندهم
مصمَّم حصرًا لحل غموض كلمة مفردة (جنس نحوي، عدد)، وينص التوثيق صراحة أنه
"غير مصمَّم" لتعليمات نبرة/شخصية بأسلوب الـLLM. حوار المانهوا يحتاج بالضبط
هذا النوع من الفهم (من يتكلم، بأي نبرة، اتساق اسم الشخصية عبر الفصل) — وهذا
مؤكَّد بحالة استخدام فعلية موثَّقة من Anthropic نفسها (Orange، منصّة توزيع
مانجا، تستخدم Claude لهذا التحديد وتُحافظ على نبرة كل شخصية وتترجم المؤثرات
الصوتية بدقة) وبأدوات مفتوحة المصدر متعددة لترجمة المانجا/المانهوا تحوّلت
كلها لمحرك LLM بدل الترجمة الآلية التقليدية.

مزوّد LLM: Gemini تحديدًا (لا Claude/GPT) — بقرار صريح من المستخدم: لا ميزانية
متاحة (Claude API ليس له باقة مجانية إطلاقًا)، وGemini وحده يوفر باقة مجانية
سخية فعليًا (حتى 1000-1500 طلب/يوم حسب النموذج) تكفي بسهولة لأي تشغيلة واقعية
بهذا المشروع (حتى 79 فصل بتشغيلة واحدة كما رُصد سابقًا بلوجات المشروع، بما أن
كل فصل = نداء واحد فقط لا نداء لكل صفحة، راجع أدناه).

النموذج: gemini-3.1-flash-lite تحديدًا (قابل للتغيير عبر GEMINI_TRANSLATION_MODEL)
— بحث فعلي (منتصف سبتمبر 2026): عائلة Gemini 2.5 بالكامل (وفيها
gemini-2.5-flash-lite المرشّح المجاني المعتاد) مُجدوَلة للإيقاف الكامل بتاريخ
16 أكتوبر 2026 — قريب جدًا من تاريخ اليوم، فاختيارها كافتراضي كان سيُعطّل
الميزة تلقائيًا خلال أسابيع بلا تدخل. gemini-3.1-flash-lite هو البديل المستقر
رسميًا (GA منذ 7 مايو 2026، بلا تاريخ إيقاف معلَن)، بنافذة سياق مليون token
(تكفي فصلًا كاملًا بسهولة بنداء واحد) ومُخرجات مُقيَّدة (structured output عبر
response_schema) مدعومة رسميًا — يضمن عودة الترجمة كمصفوفة مطابقة تمامًا
(نفس العدد، نفس ترتيب page/index) بلا حاجة لتحليل نص حر عرضة للخطأ.

[قرار معماري ثانٍ] نداء Gemini واحد لكل **فصل كامل**، لا لكل صفحة/جملة —
بحث فعلي بتوثيق DeepL نفسه (خارج نطاق اختيار المحرك، لكن المبدأ عام): "أدرج
كل السياق الممكن بنداء واحد، لا تُقسِّم النص لعدة نداءات" — نفس المبدأ أقوى مع
LLM: ترجمة كل صفحة بنداء منفصل تُخاطر باسم الشخصية X يُترجَم بصيغة مختلفة
بالصفحة 5 عنها بالصفحة 1 (نفس مشكلة توثَّقت فعليًا بمصدر بحثي عن ترجمة كتب
كاملة بـLLM: "Elara" تتحوّل لـ"Elena" لاحقًا بلا ذاكرة). نداء واحد للفصل كامل
يحافظ على الاتساق عبره، وأوفر بكثير بعدد الطلبات مقابل سقف Gemini اليومي
(RPD) — فصل من 79 يعني 79 نداء لا مئات.
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

# ============================== إعدادات عامة (قابلة للتعديل عبر متغيرات بيئة) ==============================

TRANSLATE_ENABLED = os.environ.get("TRANSLATE_TO_ARABIC", "true").strip().lower() in ("1", "true", "yes")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# [بند — بحث فعلي بتاريخه أعلاه] GA مستقر بلا تاريخ إيقاف معلَن، خلافًا
# لعائلة 2.5 (إيقاف 16 أكتوبر 2026) أو 2.0 (مُتوقَّفة فعليًا أصلًا).
# [الافتراضي] gemini-3.5-flash-lite: مستقر وموصى به رسميًا للمشاريع الجديدة، أسرع وأفضل جودة من 3.1-flash-lite.
# يُختار من حقل translation_model بالـworkflow (الفارغ/غير المضبوط ← الافتراضي).
GEMINI_MODEL_NAME = (os.environ.get("GEMINI_TRANSLATION_MODEL") or "gemini-3.5-flash-lite").strip()
# [تحفّظي عمدًا] الباقة المجانية الموثَّقة لنماذج Flash-Lite تصل حتى 15
# RPM فعليًا بمصادر بحثية متعددة، لكن القيمة الافتراضية هنا أقل تحفّظًا
# لهامش أمان (تغيّرات محتملة بالحدود بين المزوّد ونماذجه، ولا حاجة فعلية
# لأقصى سرعة هنا أصلًا — نداء واحد فقط لكل فصل، لا لكل صفحة).
GEMINI_RPM_LIMIT = max(1, int(os.environ.get("GEMINI_RPM_LIMIT", "15")))
# [تسريع] مستوى "التفكير" الداخلي للنموذج: low يكفي لترجمة حوار سياقية ويقصّ زمن التوليد كثيرًا؛
# "default" = إعداد النموذج الأصلي. يُتجاهَل تلقائيًا (مرة واحدة) لو رفضه الـAPI/الإصدار.
GEMINI_THINKING_LEVEL = os.environ.get("GEMINI_THINKING_LEVEL", "low").strip().lower()
# [تسريع] فصل طويل يُقسَّم لدفعات تُترجَم بالتوازي (كل دفعة تأخذ سياق آخر جمل الدفعة السابقة
# للاتساق)؛ الفصول العادية (<= الحد) تبقى بنداء واحد كاملًا كما كانت.
GEMINI_CHUNK_SIZE = max(40, int(os.environ.get("GEMINI_CHUNK_SIZE", "140")))
# [إزالة العلامة المائية/اسم الموقع] اسم الموقع يظهر عادةً بكل صفحة تقريبًا ويلتقطه OCR كجملة فيُترجَم ويتكرر بملف
# الترجمة. تُحذَف هذه الجمل قبل الترجمة ومن الملفات الناتجة: (أ) تلقائيًا — جملة قصيرة (≤4 كلمات) تتكرر (بتطابق
# يتسامح مع التباسات OCR الشائعة) بـ≥55% من صفحات الفصل وبـ≥5 صفحات، أو نص يشبه نطاق موقع (www/.com/…) يتكرر بصفحتين فأكثر؛ (ب) يدويًا
# عبر WATERMARK_TEXTS (نصوص مفصولة بفاصلة، تُحذَف أي جملة تحتويها بعد التطبيع). WATERMARK_FILTER=0 للتعطيل.
WATERMARK_FILTER = os.environ.get("WATERMARK_FILTER", "1").strip().lower() not in ("0", "false", "no", "off")
WATERMARK_TEXTS = [t.strip() for t in re.split(r"[,،;\n]+", os.environ.get("WATERMARK_TEXTS", "")) if t.strip()]
_use_thinking = True
_rate_lock = None
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))

_warned_no_key = False
_gemini_client = None
_last_call_ts = 0.0  # time.monotonic() — لضبط التباعد الأدنى بين النداءات (RPM)

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-\.]+")


def _safe_glossary_filename(manga_id: str) -> str:
    """تنظيف بسيط لاسم ملف الـglossary — manga_id عادة معرّف slug آمن أصلًا
    (يأتي من manga_slug_from_url بـcompress_chapters.py)، هذا احتياط إضافي
    فقط، لا إعادة تنفيذ لمنطق sanitize الكامل بـocr_extraction.py (تفاديًا
    لاستيراد دائري — راجع ترويسة الملف)."""
    cleaned = _FILENAME_SAFE_RE.sub("_", manga_id or "unknown").strip("_")
    return cleaned or "unknown"


def translation_active() -> bool:
    """يُفحَص مرة واحدة فعليًا قبل أي محاولة ترجمة — لو التفعيل مطفأ أو
    المفتاح غير مضبوط، تُطفَأ الترجمة لكامل التشغيلة بصمت (تحذير واحد فقط
    لا يتكرر لكل فصل)، والفصل يُحفَظ بنصه الإنجليزي وحده كسابقًا — فشل/تعطّل
    الترجمة لا يُسقط أي فصل ولا يوقف التشغيلة، تمامًا بنفس فلسفة عزل الأخطاء
    المتبعة بباقي هذا المشروع."""
    global _warned_no_key
    if not TRANSLATE_ENABLED:
        return False
    if not GEMINI_API_KEY:
        if not _warned_no_key:
            print(
                "⚠️ [ترجمة] TRANSLATE_TO_ARABIC مفعّل لكن GEMINI_API_KEY غير "
                "مضبوط بأسرار المستودع — الترجمة معطّلة لهذه التشغيلة كاملة "
                "(سيُحفَظ النص الإنجليزي فقط، بلا أي تأثير على باقي الميزات)"
            )
            _warned_no_key = True
        return False
    return True


def _get_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


# ============================== الـglossary (قاموس أسماء الشخصيات) ==============================
# [قرار المستخدم] يُحفَظ بالمستودع (فرع output، داخل ocr_experiment — نفس
# المسار المصرَّح به فعليًا بـallowed_paths لكل استدعاء _commit_and_push_sync
# الحالي، فلا حاجة لتعديل تلك القائمة إطلاقًا) لضمان اتساق الأسماء عبر فصول/
# تشغيلات متعددة. ملف واحد لكل manga_id (لا ملف مشترك بين كل الأعمال).

def _glossary_path(output_dir: Path, manga_id: str) -> Path:
    d = output_dir / "ocr_experiment" / "glossary"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe_glossary_filename(manga_id)}.json"


def _load_glossary(output_dir: Path, manga_id: str) -> dict:
    path = _glossary_path(output_dir, manga_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"  ⚠️ [ترجمة] تعذّرت قراءة glossary الحالي ({path.name}): {e} — سيُعاد بناؤه من الصفر")
    return {}


def _save_glossary(output_dir: Path, manga_id: str, glossary: dict) -> None:
    path = _glossary_path(output_dir, manga_id)
    path.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


# ============================== بناء الطلب ومخطط الإخراج المُقيَّد ==============================

# [بحث فعلي — توثيق Gemini الرسمي] response_schema يقبل مجموعة فرعية من
# OpenAPI 3.0 Schema — لا خصائص ديناميكية حرة (لهذا glossary_additions
# مصفوفة {name_en, name_ar} لا كائن بمفاتيح حرة).
_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "translations": {
            "type": "ARRAY",
            "description": "عنصر ترجمة واحد لكل عنصر إدخال بالضبط، بنفس page وindex",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page": {"type": "INTEGER"},
                    "index": {"type": "INTEGER"},
                    "text_ar": {"type": "STRING"},
                },
                "required": ["page", "index", "text_ar"],
            },
        },
        "glossary_additions": {
            "type": "ARRAY",
            "description": "أي اسم شخصية/علم جديد لم يكن ضمن glossary المُرفَق، بترجمته العربية الثابتة المقترَحة",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name_en": {"type": "STRING"},
                    "name_ar": {"type": "STRING"},
                },
                "required": ["name_en", "name_ar"],
            },
        },
    },
    "required": ["translations", "glossary_additions"],
}

_SYSTEM_INSTRUCTION = (
    "أنت مترجم أدبي محترف متخصّص بترجمة حوار المانهوا/المانجا من الإنجليزية "
    "(نص مُستخرَج عبر OCR من فصل، الأصل كوري/صيني مترجَم للإنجليزية أصلًا قبل "
    "استخراجه) إلى العربية الفصحى المعاصرة السلسة المناسبة لحوار القصص "
    "المصوَّرة. ليست ترجمة حرفية جافة — حافظ على نبرة كل شخصية ومشاعرها "
    "وسياق المشهد، وفسِّر المؤثرات الصوتية النصية بما يناسب السياق العربي "
    "(لا نقلها حرفيًا صوتيًا). التزم حرفيًا بأي اسم شخصية ضمن قائمة المصطلحات "
    "المعتمدة (glossary) المرفقة أدناه إن وُجدت — لا تُغيِّر ترجمته أبدًا. أي "
    "اسم علم/شخصية جديد لم يظهر بالقائمة، اقترح له ترجمة عربية ثابتة واحدة "
    "والتزم بها طوال هذا الفصل، وأضِفه لقائمة glossary_additions. أعد بالضبط "
    "عنصر ترجمة واحد لكل عنصر إدخال، محتفظًا تمامًا بنفس قيمتي page وindex "
    "كما وردتا — بلا حذف أي عنصر أو دمج عناصر أو إضافة عناصر غير موجودة "
    "بالإدخال."
)


_WM_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)
_WM_DOMAIN_RE = re.compile(r"(www\.|https?:|\.(com|net|org|to|io|me|co|cc|xyz|site|top|app|info)\b)", re.IGNORECASE)


_WM_OCR_CONFUSIONS = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "8": "b"})


def _wm_norm(text: str) -> str:
    """تطبيع للمقارنة: حروف/أرقام صغيرة بلا رموز، مع توحيد التباسات OCR الشائعة (0↔O، 1/I↔L، 5↔S، 8↔B) فتتطابق
    "AZ0RAFLY" و"AZORAFLY" تمامًا — بلا تطابق تقريبي عام، كي لا تُدمَج جمل حوار مختلفة بحرف واحد (Line 1/Line 2)."""
    return _WM_NORM_RE.sub("", (text or "").lower()).replace("rn", "m").replace("vv", "w").translate(_WM_OCR_CONFUSIONS)


def _strip_watermarks(pages: list[dict]) -> tuple[list[dict], int]:
    """يحذف جمل العلامة المائية/اسم الموقع (راجع تعليق WATERMARK_FILTER). يُعيد (pages جديدة، عدد المحذوف)؛
    بنية الصفحات محفوظة (صفحة تفرغ جملها تبقى بقائمة جمل فارغة)."""
    if not WATERMARK_FILTER:
        return pages, 0
    manual = [_wm_norm(t) for t in WATERMARK_TEXTS if len(_wm_norm(t)) >= 3]
    # تجميع الجمل المتشابهة (تسامح مع أخطاء OCR) وعدّ الصفحات المختلفة لكل مجموعة
    clusters: list[dict] = []   # {"rep": norm, "pages": set, "domain": bool}
    by_rep: dict[str, dict] = {}
    page_count = sum(1 for p in pages if p.get("sentences"))
    for pe in pages:
        for sent in pe.get("sentences", []):
            raw = sent.get("text", "")
            n = _wm_norm(raw)
            if len(n) < 3 or len(raw.split()) > 4:
                continue
            c = by_rep.get(n)
            if c is None:
                c = by_rep[n] = {"rep": n, "pages": set(), "domain": False}
                clusters.append(c)
            c["pages"].add(pe["page"])
            c["domain"] = c["domain"] or bool(_WM_DOMAIN_RE.search(raw))
    min_pages = max(5, int(0.55 * page_count + 0.999))
    wm_reps = {c["rep"] for c in clusters
               if len(c["pages"]) >= min_pages or (c["domain"] and len(c["pages"]) >= 2)}

    def is_wm(text: str) -> bool:
        n = _wm_norm(text)
        if len(n) < 3:
            return False
        if any(m in n for m in manual):
            return True
        if len(text.split()) > 4:
            return False
        return n in wm_reps

    removed = 0
    out: list[dict] = []
    for pe in pages:
        kept = []
        for sent in pe.get("sentences", []):
            if is_wm(sent.get("text", "")):
                removed += 1
            else:
                kept.append(sent)
        out.append({**pe, "sentences": kept})
    if removed and wm_reps:
        print(f"  🧽 [ترجمة] حُذفت {removed} جملة علامة مائية/اسم موقع متكرر: {sorted(set(wm_reps))[:5]}")
    elif removed:
        print(f"  🧽 [ترجمة] حُذفت {removed} جملة علامة مائية (حسب WATERMARK_TEXTS)")
    return out, removed


def _flatten_chapter_sentences(pages: list[dict]) -> list[dict]:
    """يُحوِّل بنية pages (page_json الحالية: [{page, sentences:[{text,...}]}])
    إلى قائمة مسطَّحة [{page, index, text}] — index هنا 1-based ضمن صفحته
    (يطابق تمامًا رقم الجملة المُستخدَم فعليًا بـformat_ocr_page_text
    الحالية، "NNN-M")، فلا نظام ترقيم جديد يحتاج تعلّمًا منفصلًا."""
    items: list[dict] = []
    for page_entry in pages:
        page_num = page_entry["page"]
        for idx, sentence in enumerate(page_entry.get("sentences", []), start=1):
            items.append({"page": page_num, "index": idx, "text": sentence["text"]})
    return items


def _build_prompt(items: list[dict], glossary: dict, context_before: list[dict] | None = None) -> str:
    glossary_block = (
        "\n".join(f"- {en} → {ar}" for en, ar in sorted(glossary.items()))
        if glossary else "(لا يوجد glossary سابق لهذا العمل بعد — هذا أول فصل يُترجَم له)"
    )
    items_json = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    ctx = ""
    if context_before:
        ctx = ("سياق سابق من نفس الفصل (للفهم والاتساق فقط — لا تترجمه ولا تُدرجه بالمخرجات):\n"
               + json.dumps(context_before, ensure_ascii=False, separators=(",", ":")) + "\n\n")
    return (
        f"قائمة المصطلحات المعتمدة (glossary) لهذا العمل:\n{glossary_block}\n\n{ctx}"
        f"ترجم كل عنصر بالمصفوفة التالية (كل عنصر جملة واحدة من نفس الفصل، "
        f"بترتيب الصفحات والقراءة الصحيح):\n{items_json}"
    )


# ============================== التباعد الزمني (RPM) وإعادة المحاولة ==============================

async def _respect_rate_limit() -> None:
    """يحجز موعد النداء بقفل (آمن للنداءات المتوازية): أول نداء بلا انتظار، والتالي بعد 60/RPM ثانية."""
    global _last_call_ts, _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    min_interval = 60.0 / GEMINI_RPM_LIMIT
    async with _rate_lock:
        now = time.monotonic()
        wait = (_last_call_ts + min_interval) - now
        _last_call_ts = max(now, _last_call_ts + min_interval)
    if wait > 0:
        await asyncio.sleep(wait)


async def _call_gemini_with_retry(prompt: str) -> dict | None:
    from google.genai import types

    global _use_thinking
    client = _get_client()
    last_err: Exception | None = None
    attempt = 0
    while attempt < GEMINI_MAX_RETRIES:
        attempt += 1
        await _respect_rate_limit()
        try:
            kw = dict(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                temperature=0.3,
            )
            if _use_thinking and GEMINI_THINKING_LEVEL not in ("", "default"):
                kw["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(**kw),
            )
            return json.loads(response.text)
        except Exception as e:
            last_err = e
            msg = str(e)
            if _use_thinking and "thinking" in msg.lower():
                _use_thinking = False   # الإصدار/النموذج لا يدعم الإعداد ← تعطيله وإعادة المحاولة فورًا
                print("  ⚠️ [ترجمة] thinking_level غير مدعوم هنا — إعادة المحاولة بالإعداد الافتراضي")
                attempt -= 1
                continue
            # [بحث فعلي] 429 / RESOURCE_EXHAUSTED هو خطأ تجاوز الحدود
            # الموثَّق بتوثيق Gemini الرسمي — يستحق انتظارًا أطول من أي
            # خطأ عابر آخر (شبكة، انقطاع لحظي) قبل إعادة المحاولة.
            is_rate_limit = ("429" in msg) or ("RESOURCE_EXHAUSTED" in msg) or ("rate limit" in msg.lower())
            backoff = (2 ** attempt) * (5 if is_rate_limit else 1)
            print(
                f"  ⚠️ [ترجمة] محاولة {attempt}/{GEMINI_MAX_RETRIES} فشلت "
                f"({msg[:150]}) — إعادة محاولة بعد {backoff}ث"
            )
            if attempt < GEMINI_MAX_RETRIES:
                await asyncio.sleep(backoff)
    print(f"  ❌ [ترجمة] فشلت ترجمة هذا الفصل نهائيًا بعد {GEMINI_MAX_RETRIES} محاولات: {last_err}")
    return None


# ============================== نقطة الدخول الرئيسية ==============================

def _format_text_ar_txt(manga_title: str, chapter_num: str, translated_pages: list[dict]) -> str:
    lines = [f"# {manga_title} — الفصل {chapter_num}", ""]
    for page_entry in translated_pages:
        lines.append(f"Page {page_entry['page']:03d}")
        for idx, s in enumerate(page_entry.get("sentences", []), start=1):
            lines.append(f"{page_entry['page']:03d}-{idx}. {s['text']}")
            lines.append(f"  الترجمة: {s.get('text_ar', '⚠️ لم تُترجَم')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def translate_chapter_to_arabic(chapter_result: dict, output_dir: Path, out_dir: Path) -> list[Path]:
    """نقطة الدخول الوحيدة المستدعاة من ocr_extraction.py (استيراد مؤجَّل).
    تُترجَم كل جمل الفصل بنداء Gemini واحد (راجع تبرير هذا القرار بترويسة
    الملف)، وتُكتَب text_ar.json (نفس بنية pages + text_ar لكل جملة) و
    text_ar.txt (نص مقروء إنجليزي+عربي). يُحدَّث glossary العمل ويُحفَظ.

    فشل تام (تعطّل الميزة، تجاوز إعادة المحاولات، استجابة غير صالحة) يُعيد
    قائمة فارغة بصمت مع تحذير مطبوع — لا استثناء يصعد، ولا تأثير على نجاح
    الفصل نفسه (يبقى محفوظًا بنصه الإنجليزي فقط)، تمامًا بنفس فلسفة عزل
    الأخطاء لكل صفحة/فصل المتّبعة ببقية هذا الملف."""
    if not translation_active():
        return []

    pages, _wm_removed = _strip_watermarks(chapter_result.get("pages") or [])
    items = _flatten_chapter_sentences(pages)
    if not items:
        return []

    manga_id = chapter_result["manga_id"]
    chapter_num = chapter_result["chapter_num"]
    manga_title = chapter_result.get("manga_title") or manga_id

    glossary = _load_glossary(output_dir, manga_id)

    n_chunks = -(-len(items) // GEMINI_CHUNK_SIZE)
    size = -(-len(items) // n_chunks)
    chunks = [items[i:i + size] for i in range(0, len(items), size)]
    print(f"  🌐 [ترجمة] إرسال {len(items)} جملة لـGemini ({GEMINI_MODEL_NAME}) — الفصل {chapter_num}"
          + (f" ({len(chunks)} دفعات متوازية)" if len(chunks) > 1 else ""))
    prompts = [_build_prompt(c, glossary, context_before=(chunks[k - 1][-4:] if k else None))
               for k, c in enumerate(chunks)]
    results = await asyncio.gather(*[_call_gemini_with_retry(pr) for pr in prompts])
    if any(r is None for r in results):
        return []   # أي دفعة فاشلة ← الفصل كله لطابور إعادة المحاولة (لا ترجمة ناقصة صامتة)
    result = {"translations": [t for r in results for t in (r.get("translations") or [])],
              "glossary_additions": [a for r in results for a in (r.get("glossary_additions") or [])]}

    translations = result.get("translations") or []
    by_key = {(t["page"], t["index"]): t.get("text_ar", "") for t in translations if "page" in t and "index" in t}

    missing = 0
    translated_pages: list[dict] = []
    for page_entry in pages:
        page_num = page_entry["page"]
        new_sentences = []
        for idx, sentence in enumerate(page_entry.get("sentences", []), start=1):
            text_ar = by_key.get((page_num, idx), "")
            if not text_ar:
                missing += 1
            new_sentences.append({**sentence, "text_ar": text_ar})
        translated_pages.append({"page": page_num,
                                 **({"image_id": page_entry["image_id"]} if page_entry.get("image_id") is not None else {}),
                                 "sentences": new_sentences})
    if missing:
        print(f"  ⚠️ [ترجمة] {missing}/{len(items)} جملة لم تعد بترجمة من Gemini (بقيت فارغة بالمخرجات)")

    # دمج glossary_additions — الاسم الموجود مسبقًا لا يُستبدَل أبدًا (أول
    # اعتماد يفوز، لضمان الاتساق عبر فصول متعددة حتى لو النموذج اقترح صياغة
    # مختلفة بفصل لاحق لنفس الاسم).
    additions = result.get("glossary_additions") or []
    added_count = 0
    for a in additions:
        name_en = (a.get("name_en") or "").strip()
        name_ar = (a.get("name_ar") or "").strip()
        if name_en and name_ar and name_en not in glossary:
            glossary[name_en] = name_ar
            added_count += 1
    if added_count:
        _save_glossary(output_dir, manga_id, glossary)
        print(f"  📖 [ترجمة] أُضيف {added_count} اسم جديد لـglossary ({manga_id})")

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "text_ar.json"
    txt_path = out_dir / "text_ar.txt"
    json_payload = {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "manga_title": manga_title,
        "translation_model": GEMINI_MODEL_NAME,
        "pages": translated_pages,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(_format_text_ar_txt(manga_title, chapter_num, translated_pages), encoding="utf-8")

    print(f"  ✅ [ترجمة] فصل {chapter_num} تُرجم ({len(items) - missing}/{len(items)} جملة)")
    return [json_path, txt_path]
