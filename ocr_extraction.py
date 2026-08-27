#!/usr/bin/env python3
"""
قسم استخراج النص الإنجليزي (OCR) — فُصل من compress_chapters.py الأساسي
(كان سابقًا "المرحلة ١: تجربة OCR الإنجليزي"، الأسطر ~1755-2262 من النسخة
الأحادية v19) إلى ملف مستقل بطلب صريح لتنظيم الكود.

هذا الملف يُستورَد فقط من compress_chapters.py (استيراد مؤجَّل داخل main()
تحديدًا، لا على مستوى الملف — لتفادي استيراد دائري لأن هذا الملف نفسه
يستورد من compress_chapters عدة دوال/ثوابت مشتركة أدناه). لا يُشغَّل هذا
الملف مباشرةً بأي سيناريو إنتاجي.

الاعتماديات على compress_chapters.py (النواة المشتركة):
- get_profile, get_chapter_images, manga_slug_from_url — جلب الفصل بنفس
  منطق الإنتاج الفعلي (بروفايل الموقع كاملًا)، لا إعادة تنفيذ.
- fetch_image_bytes_http, fetch_image_bytes — تحميل بايتات الصورة الخام
  (HTTP مباشر / متصفح، حسب fetch_mode البروفايل).
- _commit_and_push_sync — دفع نتائج تجربة OCR لفرع الإخراج.
- OUTPUT_DIR, RUN_ID, GIT_COMMIT_DIR, GIT_BRANCH, IMG_FETCH_DELAY_MS,
  SITE_PROFILE — ثوابت بيئة/تشغيلة مشتركة.
"""
import asyncio
import json
import os
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

from compress_chapters import (
    GIT_BRANCH,
    GIT_COMMIT_DIR,
    IMG_FETCH_DELAY_MS,
    OUTPUT_DIR,
    RUN_ID,
    SITE_PROFILE,
    _commit_and_push_sync,
    fetch_image_bytes,
    fetch_image_bytes_http,
    get_chapter_images,
    get_profile,
    manga_slug_from_url,
)


# ============================== المرحلة ١: تجربة OCR الإنجليزي ==============================
# [تجريبي — لا يزال يحتاج ضبط عتباته على فصل حقيقي] يعيد استخدام get_chapter_images
# (نفس منطق الجلب المستخدم بالإنتاج فعليًا، بروفايل الموقع كاملًا) بدل إعادة
# تنفيذه، ويعمل حصرًا على raw bytes الخام قبل أي ضغط. محرك OCR: PaddleOCR
# (lang="en") — اختير بعد بحث فعلي 2026 بديل EasyOCR/Tesseract: استهلاك
# ذاكرة أقل واستيقاظ بارد أسرع على CPU (مهم لأن كل تشغيلة Actions تبدأ من
# صفر)، وكاشف نص أعمّ (DBNet) أنسب لنص متفرق على صورة طويلة من كاشف
# Tesseract المصمَّم لمستند منتظم. الاستيراد داخل الدالة (lazy) كي لا تفشل
# التشغيلات العادية (ضغط/تشخيص) لو لم تُثبَّت المكتبة أصلًا.

_PADDLEOCR_ENGINE = None  # يُهيَّأ مرة واحدة فقط — تحميل النماذج ثقيل نسبيًا
_PADDLEOCR_MKLDNN_FALLBACK_DONE = False  # يمنع تكرار إعادة التهيئة أكثر من مرة

# [تصحيح — PIR/oneDNN] النص الحرفي الذي يظهر في NotImplementedError عند خلل
# ConvertPirAttribute2RuntimeAttribute (issue #77340 على مستودع Paddle
# الرسمي). يُستخدَم كفحص نصي دقيق لا except عام، حتى لا نُخفي أخطاء أخرى
# فعلية تحت غطاء "fallback".
_PIR_ONEDNN_ERROR_MARKER = "ConvertPirAttribute2RuntimeAttribute"

# [جديد — تحديد صريح لسعة كاش oneDNN] الافتراضي الداخلي لمحرك Paddle هو 10
# نواة (kernel) مخزَّنة بالذاكرة الأصلية (native memory، خارج نطاق GC
# بايثون). صفحات ويبتون هنا بارتفاع مختلف كليًا كل صفحة تقريبًا (شريط طويل
# متغيّر)، فكل شكل (shape) جديد يُجبر oneDNN على بناء/تخزين نواة إضافية —
# تتراكم عبر الفصل الواحد بلا سقف، وهو ما يفسّر تسريب ذاكرة موثَّق بمحرك
# Paddle عبر إصدارات متعددة (PaddlePaddle issues #7823 / #11639 / #25506)
# مستقلًا عن استهلاك الذاكرة الطبيعي للنموذج نفسه. قيمة صغيرة هنا تمنع
# التراكم غير المحدود مقابل كلفة زمنية بسيطة (إعادة بناء نواة أحيانًا)، بلا
# أي فقد بالدقة. قابلة للتجربة عبر متغير بيئة بنفس نمط بقية ثوابت OCR هنا.
OCR_MKLDNN_CACHE_CAPACITY = int(os.environ.get("OCR_MKLDNN_CACHE_CAPACITY", "2"))

# [جديد — بند (3) من خطة الإصلاح: إعادة بناء دورية للمحرك] حتى مع سعة كاش
# oneDNN محدودة (أعلاه) وتطبيع شكل الصورة (أدناه)، لا ضمان مطلق أن كل
# تراكم ذاكرة أصلية (native memory) داخل محرك Paddle قد رُصِد ومُعولِج —
# هذا وقائي دوري لا يعتمد على حدوث خطأ فعلي أولًا (بعكس احتياطيات PIR/
# std::exception أدناه، وهي رد فعل بعد وقوع الخلل). كل N صفحة ضمن الفصل
# الواحد يُعاد بناء المحرك من الصفر فيتحرر أي تراكم متبقٍ، بكلفة زمنية
# صغيرة (إعادة تحميل نموذج مرة كل N صفحة، لا كل صفحة).
OCR_ENGINE_REBUILD_EVERY_N_PAGES = int(os.environ.get("OCR_ENGINE_REBUILD_EVERY_N_PAGES", "15"))

# [جديد — بند (2) من خطة الإصلاح: تطبيع شكل الصورة قبل predict()] صفحات
# ويبتون هنا بارتفاع مختلف كليًا كل صفحة تقريبًا (شريط طويل متغيّر من
# ~12700 إلى ~13500px بالعينة الفعلية المفحوصة) — حتى مع سعة كاش صغيرة
# (OCR_MKLDNN_CACHE_CAPACITY)، كل شكل جديد لا يزال يُجبر oneDNN على بناء
# نواة إضافية قبل أن يُطرَد شيء من الكاش أصلًا. الحل الجذري لا الجانبي:
# تقسيم أي صورة أطول من OCR_TILE_HEIGHT إلى بلاطات ثابتة الارتفاع تمامًا
# (حشو أبيض للبلاطة الأخيرة الأقصر فقط، لا تصغير/تكبير فعلي يفقد دقة
# النص)، وحشو العرض إلى OCR_TILE_WIDTH الثابت كذلك. الناتج: نفس الشكل
# تقريبًا (OCR_TILE_HEIGHT × OCR_TILE_WIDTH) لكل استدعاء predict() بصرف
# النظر عن أبعاد الصفحة الأصلية، فيقل تجدد نوى oneDNN جذريًا بدل الاعتماد
# فقط على سقف الكاش. تراكب رأسي صغير (OCR_TILE_OVERLAP) بين البلاطات
# المتتالية يمنع قص سطر نص تمامًا عند حد البلاطة، مع إزالة الصناديق شبه
# المكررة الناتجة عن هذا التراكب بعد الدمج (_dedupe_overlap_boxes أدناه).
# [ملاحظة معايرة] لم يُختبَر بعد على تشغيلة حقيقية داخل بيئة GitHub Actions
# الفعلية (لا شبكة/GPU متاحة هنا لتشغيل PaddleOCR فعليًا) — القيم
# الافتراضية معقولة هندسيًا لكن ينبغي تأكيدها على فصل حقيقي طويل قبل
# الاعتماد الكامل، تمامًا كتحذير jsquash السابق بمشروع منظّم النصوص.
OCR_TILE_HEIGHT = int(os.environ.get("OCR_TILE_HEIGHT", "3000"))
OCR_TILE_OVERLAP = int(os.environ.get("OCR_TILE_OVERLAP", "80"))
OCR_TILE_WIDTH = int(os.environ.get("OCR_TILE_WIDTH", "800"))
_OCR_WIDTH_WARNED = False  # يمنع تكرار تحذير العرض الأوسع من المتوقَّع لكل صفحة


def _build_paddleocr_engine(enable_mkldnn: bool):
    from paddleocr import PaddleOCR
    # [تصحيح — PaddleOCR 3.x] show_log أُزيلت كليًا (كانت تُسبِّب
    # "Unknown argument: show_log" فعليًا)، وuse_angle_cls اسمها الجديد
    # use_textline_orientation. تُعطَّل هنا كل النماذج الفرعية غير
    # الضرورية لحالتنا (اتجاه المستند/فك التقوّس/اتجاه السطر) — الصور
    # نص ويبتون مستقيم قياسي، تسريع بلا فقد دقة متوقَّع.
    # [تصحيح — احتياطي PIR/oneDNN] enable_mkldnn=True هو الافتراضي الآمن
    # الآن (paddleocr==3.2.0 + paddlepaddle==3.1.1 مثبَّتان صراحة، يسبقان
    # خلل PIR/oneDNN تمامًا) ويحافظ على تسريع oneDNN الكامل. enable_mkldnn
    # لا يُعطَّل افتراضيًا أبدًا لأنه موثَّق (issue #17955) أنه يستهلك ~43GB
    # رام على إصدارات 3.x الحديثة — رانر GitHub Actions القياسي يملك 7GB
    # فقط، فتعطيله دومًا يعني استبدال خطأ فوري بخطأ OOM صامت أسوأ. يُعطَّل
    # فقط كخطوة احتياطية لمرة واحدة عند حدوث الخلل فعليًا (انظر أدناه).
    return PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=enable_mkldnn,
        mkldnn_cache_capacity=OCR_MKLDNN_CACHE_CAPACITY,
    )


def _get_paddleocr_engine():
    global _PADDLEOCR_ENGINE
    if _PADDLEOCR_ENGINE is None:
        _PADDLEOCR_ENGINE = _build_paddleocr_engine(enable_mkldnn=True)
    return _PADDLEOCR_ENGINE


def _reinit_paddleocr_engine(enable_mkldnn: bool):
    """[احتياطي عام — يُستدعى لكل حدوث، لا مرة واحدة فقط] يعيد بناء محرك
    PaddleOCR من الصفر بنفس إعداد mkldnn المُمرَّر. الفائدة هنا ليست
    الالتفاف حول خلل PIR المحدَّد (انظر الدالة المخصَّصة أدناه)، بل تحرير
    الذاكرة الأصلية (native memory) المتراكمة داخل المحرك نفسه — نوى oneDNN
    المخزَّنة تُفقَد كليًا عند بناء كائن PaddleOCR جديد. لا تُعطِّل mkldnn هنا
    دائمًا (بعكس الاحتياطي المخصَّص لخلل PIR) لأن التراكم أصلًا محدود الآن
    بـOCR_MKLDNN_CACHE_CAPACITY، فلا داعٍ للتضحية بتسريع oneDNN الكامل لمجرد
    إعادة بناء دورية."""
    global _PADDLEOCR_ENGINE
    _PADDLEOCR_ENGINE = _build_paddleocr_engine(enable_mkldnn=enable_mkldnn)
    return _PADDLEOCR_ENGINE


def _reinit_paddleocr_engine_without_mkldnn():
    """[احتياطي — مرة واحدة فقط] يُستدعى حصرًا عند رصد نص الخلل
    ConvertPirAttribute2RuntimeAttribute تحديدًا. يعيد تهيئة المحرك
    بـenable_mkldnn=False ويسجّل تحذيرًا عربيًا واضحًا في اللوج كي يُلاحَظ
    لو تكرر (يعني أن التثبيت المثبَّت لم يعد يطابق الافتراض الموثَّق)."""
    global _PADDLEOCR_ENGINE, _PADDLEOCR_MKLDNN_FALLBACK_DONE
    print(
        "⚠️ [OCR احتياطي] رُصد خلل PIR/oneDNN "
        f"({_PIR_ONEDNN_ERROR_MARKER}) رغم الإصدارات المثبَّتة المتوقَّعة — "
        "إعادة تهيئة محرك PaddleOCR بـenable_mkldnn=False (مرة واحدة). "
        "إن تكرر هذا التحذير بشكل متكرر، فالتثبيت الفعلي لم يعد يطابق "
        "paddleocr==3.2.0 / paddlepaddle==3.1.1 الموثَّقين كآمنين."
    )
    _PADDLEOCR_ENGINE = _build_paddleocr_engine(enable_mkldnn=False)
    _PADDLEOCR_MKLDNN_FALLBACK_DONE = True
    return _PADDLEOCR_ENGINE


def _tile_image_fixed_shape(img: "Image.Image") -> list[tuple["Image.Image", int]]:
    """[بند 2] يُرجع قائمة (بلاطة PNG، y_offset الأصلي) بشكل ثابت تقريبًا
    (OCR_TILE_HEIGHT × عرض القماشة) لكل بلاطة. صورة أقصر من/تساوي
    OCR_TILE_HEIGHT تُحشى لبلاطة واحدة كاملة الارتفاع (تبقى الفائدة: شكل
    ثابت متطابق مع بقية الصفحات بدل ارتفاعها الفعلي المتفاوت). عرض أضيق من
    OCR_TILE_WIDTH يُحشى بأبيض يمينًا (لا تمديد محتوى فعلي)؛ عرض أوسع
    (نادر لموقع بعرض مصدر أكبر) يُترك بعرضه الفعلي كاملًا مع تحذير لمرة
    واحدة فقط — أفضل من فقد نص حقيقي بالقص."""
    global _OCR_WIDTH_WARNED
    width, height = img.size
    if width > OCR_TILE_WIDTH and not _OCR_WIDTH_WARNED:
        print(
            f"  ⚠️ [OCR تطبيع] عرض صفحة ({width}px) أكبر من OCR_TILE_WIDTH "
            f"({OCR_TILE_WIDTH}px) — لا حشو لهذه الحالة، الشكل سيبقى متغيرًا "
            "جزئيًا لهذا الموقع تحديدًا (فكرة: رفع OCR_TILE_WIDTH عبر متغير بيئة)"
        )
        _OCR_WIDTH_WARNED = True
    canvas_width = max(width, OCR_TILE_WIDTH)

    step = OCR_TILE_HEIGHT - OCR_TILE_OVERLAP
    if step <= 0:
        raise ValueError("OCR_TILE_OVERLAP يجب أن يكون أصغر من OCR_TILE_HEIGHT")

    tiles: list[tuple["Image.Image", int]] = []
    y = 0
    while True:
        tile = Image.new("RGB", (canvas_width, OCR_TILE_HEIGHT), (255, 255, 255))
        crop = img.crop((0, y, width, min(y + OCR_TILE_HEIGHT, height)))
        tile.paste(crop, (0, 0))
        tiles.append((tile, y))
        if y + OCR_TILE_HEIGHT >= height:
            break
        y += step
    return tiles


def _dedupe_overlap_boxes(items: list[dict]) -> list[dict]:
    """[بند 2] يُزيل الصناديق شبه المكررة الناتجة عن نص وقع بمنطقة التراكب
    بين بلاطتين متتاليتين (اكتُشف مرتين بنص متطابق تمامًا وإحداثيات y/x
    قريبة جدًا بعد تعويض y_offset). يُبقي على النسخة الأعلى ثقة (confidence)
    فقط. لا يُشغَّل إطلاقًا لو بلاطة واحدة فقط (لا تراكب ممكن أصلًا)."""
    items_sorted = sorted(items, key=lambda it: (_bbox_top(it["bbox"]), _bbox_left(it["bbox"])))
    kept: list[dict] = []
    for it in items_sorted:
        dup_idx = None
        for idx, k in enumerate(kept[-6:], start=max(0, len(kept) - 6)):
            same_text = it["text"].strip() == k["text"].strip()
            close_y = abs(_bbox_top(it["bbox"]) - _bbox_top(k["bbox"])) < 40
            close_x = abs(_bbox_left(it["bbox"]) - _bbox_left(k["bbox"])) < 40
            if same_text and close_y and close_x:
                dup_idx = idx
                break
        if dup_idx is None:
            kept.append(it)
        elif it["confidence"] > kept[dup_idx]["confidence"]:
            kept[dup_idx] = it
    return kept


def _predict_with_engine_fallback(tmp_path: str):
    """[استُخرِج من ocr_extract_english_sync كي يُعاد استخدامه لكل بلاطة على
    حدة بعد بند (2)، بدل مرة واحدة للصورة الكاملة] نفس منطق احتياطي PIR/
    oneDNN واستثناء C++ الفارغ دون أي تغيير سلوكي."""
    global _PADDLEOCR_ENGINE
    engine = _get_paddleocr_engine()
    generic_attempts = 0
    while True:
        try:
            return engine.predict(tmp_path)
        except NotImplementedError as e:
            if _PIR_ONEDNN_ERROR_MARKER not in str(e) or _PADDLEOCR_MKLDNN_FALLBACK_DONE:
                raise
            engine = _reinit_paddleocr_engine_without_mkldnn()
            continue
        except Exception as e:
            if str(e).strip() or generic_attempts >= 1:
                raise
            generic_attempts += 1
            print(
                "  ⚠️ [OCR احتياطي] استثناء C++ فارغ (str(e) فارغ) — "
                "على الأرجح تراكم ذاكرة أصلية (oneDNN) وسط الفصل. "
                "إعادة بناء محرك PaddleOCR ومحاولة هذه البلاطة مرة أخرى."
            )
            engine = _reinit_paddleocr_engine(
                enable_mkldnn=not _PADDLEOCR_MKLDNN_FALLBACK_DONE
            )
            continue


def _current_rss_mb() -> float | None:
    """[بند 5] RSS الحالية للعملية بالميغابايت — للتحقق التجريبي الفعلي من
    فرضية تراكم الذاكرة على تشغيلة حقيقية، لا تخمينًا. المسار الأساسي
    /proc/self/status (دقيق، لحظي، بلا أي اعتماد جديد — لينكس هو بيئة رانر
    GitHub Actions فعليًا هنا). احتياطي resource.getrusage لو تعذّر المسار
    الأول (تنبيه: ru_maxrss هو الذروة التراكمية لا القيمة اللحظية على أغلب
    الأنظمة، فلن ينخفض بين صفحة وأخرى — يُستخدم فقط كملاذ أخير، ويُفضَّل عدم
    الاعتماد عليه لقراءة "قبل/بعد" دقيقة)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return None


def ocr_extract_english_sync(raw_bytes: bytes) -> list[dict]:
    """يُشغَّل عبر asyncio.to_thread. يُرجع صناديق نص خام بلا فرز/تجميع بعد:
    كل عنصر {bbox: [xmin,ymin,xmax,ymax], text: str, confidence: float}.
    [بند 2] الصورة تُقسَّم أولًا لبلاطات ثابتة الشكل (_tile_image_fixed_shape)
    بدل تمرير الصفحة كاملة بارتفاعها المتفاوت — كل بلاطة تُكتَب كملف مؤقت
    منفصل ويُمرَّر مساره لـpredict() (يطابق مسار الاستخدام الموثَّق رسميًا
    بـPaddleOCR 3.x)، وإحداثيات y لكل صندوق ناتج تُعوَّض بـy_offset البلاطة
    لتبقى الإحداثيات النهائية بمرجعية الصفحة الأصلية الكاملة كما كانت."""
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    tiles = _tile_image_fixed_shape(img)

    all_items: list[dict] = []
    for tile_img, y_offset in tiles:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            tile_img.save(tmp_path, format="PNG")
            result = _predict_with_engine_fallback(tmp_path)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        if not result:
            continue
        res = result[0]
        texts = res.get("rec_texts") or []
        scores = res.get("rec_scores") or []
        boxes = res.get("rec_boxes")
        if boxes is None:
            continue
        for text, score, box in zip(texts, scores, boxes):
            text = (text or "").strip()
            if not text:
                continue
            xmin, ymin, xmax, ymax = [float(v) for v in box]
            all_items.append({
                "bbox": [xmin, ymin + y_offset, xmax, ymax + y_offset],
                "text": text,
                "confidence": float(score),
            })

    return _dedupe_overlap_boxes(all_items) if len(tiles) > 1 else all_items


def _bbox_top(bbox) -> float:
    return bbox[1]

def _bbox_bottom(bbox) -> float:
    return bbox[3]

def _bbox_left(bbox) -> float:
    return bbox[0]


# [قابل للتعديل بعد تجربة على فصل حقيقي] عتبة تجميع الأسطر المتتالية رأسيًا
# ضمن نفس البند (تقريب هندسي لحدود الفقاعة — لا يوجد كاشف فقاعات فعلي هنا)
OCR_CLUSTER_GAP_RATIO = float(os.environ.get("OCR_CLUSTER_GAP_RATIO", "0.6"))
# فرق أفقي أقصى (بكسل) بين بداية سطرين ليُعتبَرا نفس العمود/الفقاعة تقريبًا
OCR_CLUSTER_X_TOLERANCE = int(os.environ.get("OCR_CLUSTER_X_TOLERANCE", "400"))
# صناديق بأقل من هذا عدد أحرف أبجدية تُعلَّم كمرشح مؤثر صوتي/رمز — لا تُحذَف،
# فقط تُعلَّم [sfx?] ليراجعها المستخدم (حذف صامت = فقدان بيانات غير مقبول)
OCR_SFX_MIN_LETTERS = int(os.environ.get("OCR_SFX_MIN_LETTERS", "3"))


def group_ocr_lines_into_sentences(items: list[dict]) -> list[dict]:
    """يفرز الصناديق (أعلى فأسفل أولًا، يسار فيمين لحل تعادل نفس السطر تقريبًا
    — مناسب لشريط ويبتون عمودي مستمر)، ثم يُجمِّع الأسطر المتتالية القريبة
    رأسيًا والمتقاربة أفقيًا كبند واحد. كل بند ناتج:
    {text: str, confidence: float (أدنى ثقة ضمن البند), sfx_suspect: bool}."""
    boxes = sorted(items, key=lambda it: (_bbox_top(it["bbox"]), _bbox_left(it["bbox"])))
    groups: list[list[dict]] = []
    for it in boxes:
        placed = False
        if groups:
            last = groups[-1][-1]
            gap = _bbox_top(it["bbox"]) - _bbox_bottom(last["bbox"])
            line_h = (_bbox_bottom(last["bbox"]) - _bbox_top(last["bbox"])) or 1
            x_close = abs(_bbox_left(it["bbox"]) - _bbox_left(last["bbox"])) <= OCR_CLUSTER_X_TOLERANCE
            if gap <= line_h * OCR_CLUSTER_GAP_RATIO and x_close:
                groups[-1].append(it)
                placed = True
        if not placed:
            groups.append([it])

    sentences = []
    for g in groups:
        text = " ".join(x["text"] for x in g)
        conf = min(x["confidence"] for x in g)
        letters = sum(c.isalpha() for c in text)
        sentences.append({"text": text, "confidence": round(conf, 3), "sfx_suspect": letters < OCR_SFX_MIN_LETTERS})
    return sentences


def format_ocr_page_text(page_num: int, sentences: list[dict]) -> str:
    """نفس بنية ملف الترجمة النموذجي المرجعي: 'Page NNN' ثم 'NNN-M. <text>'،
    مع وسم [sfx?] بدل حذف صامت لما يُشتبه أنه مؤثر صوتي/رمز."""
    lines = [f"Page {page_num:03d}"]
    idx = 0
    for s in sentences:
        idx += 1
        tag = " [sfx?]" if s["sfx_suspect"] else ""
        lines.append(f"{page_num:03d}-{idx}. {s['text']}{tag}")
    return "\n".join(lines)


async def ocr_process_chapter(browser, chapter_url: str, index: int, total: int, profile: dict) -> dict | None:
    """مرآة لـprocess_chapter لكن بدل compress_image+حفظ صورة: OCR على raw
    مباشرة (أبدًا على نسخة مضغوطة). يعيد استخدام get_chapter_images كاملة —
    نفس بروفايل الموقع ونفس منطق إعادة المحاولة المستخدم بالإنتاج الفعلي."""
    print(f"[{index}/{total}] 🔤 تجربة OCR: {chapter_url} — بروفايل: {profile['label']}")

    context, image_urls, fail_reason = await get_chapter_images(browser, chapter_url, profile)
    if not image_urls:
        print(f"  ❌ {fail_reason or 'لم يُعثر على صور في هذا الفصل'}")
        return None

    manga_id, chapter_num = manga_slug_from_url(chapter_url)
    fetch_mode = profile.get("fetch_mode", "browser")

    async def download(img_url: str):
        if fetch_mode == "http":
            return await fetch_image_bytes_http(img_url, chapter_url)
        return await fetch_image_bytes(context, img_url, chapter_url)

    page_texts: list[str] = []
    page_json: list[dict] = []
    # [بند 3] عداد صفحات منذ آخر إعادة بناء للمحرك — يُصفَّر كل فصل جديد
    # (الدالة نفسها تُستدعى مرة لكل فصل)، لا عبر التشغيلة كاملة.
    pages_since_rebuild = 0
    for i, img_url in enumerate(image_urls, start=1):
        raw, reason = await download(img_url)
        if not raw:
            print(f"  ⚠️ فشل تحميل صفحة {i} للـOCR: {reason}")
            continue
        # [بند 5] قياس RSS فعلي قبل/بعد كل صفحة — تحقق تجريبي من فرضية
        # تراكم الذاكرة، لا تخمين. None بصمت لو تعذّر القياس (بيئة لا تدعم
        # /proc أو resource) كي لا يُعطَّل OCR نفسه بسبب فشل قياس جانبي.
        rss_before = _current_rss_mb()
        try:
            items = await asyncio.to_thread(ocr_extract_english_sync, raw)
            sentences = group_ocr_lines_into_sentences(items)
            page_texts.append(format_ocr_page_text(i, sentences))
            page_json.append({"page": i, "sentences": sentences})
            sfx_count = sum(1 for s in sentences if s["sfx_suspect"])
            rss_after = _current_rss_mb()
            rss_note = (
                f" | RSS: {rss_before:.0f}→{rss_after:.0f}MB (Δ{rss_after - rss_before:+.0f})"
                if rss_before is not None and rss_after is not None else ""
            )
            print(f"  ✅ صفحة {i}/{len(image_urls)} — {len(sentences)} بند نص ({sfx_count} مُعلَّم [sfx?]){rss_note}")
        except Exception as e:
            rss_after = _current_rss_mb()
            rss_note = f" | RSS عند الفشل: {rss_after:.0f}MB" if rss_after is not None else ""
            print(f"  ⚠️ فشل OCR للصفحة {i}: {e}{rss_note}")

        # [بند 3] إعادة بناء وقائية دورية — تحرّر أي تراكم ذاكرة أصلية
        # متبقٍ بصرف النظر عن نجاح/فشل الصفحة الحالية، فتُحتسَب الصفحات
        # الفاشلة أيضًا ضمن العداد (نفس تكلفة الاستدعاء على المحرك).
        pages_since_rebuild += 1
        if pages_since_rebuild >= OCR_ENGINE_REBUILD_EVERY_N_PAGES:
            print(
                f"  🔄 [OCR وقائي] إعادة بناء محرك PaddleOCR بعد "
                f"{pages_since_rebuild} صفحة (تحرير ذاكرة أصلية دوري، بند 3)"
            )
            await asyncio.to_thread(
                _reinit_paddleocr_engine, not _PADDLEOCR_MKLDNN_FALLBACK_DONE
            )
            pages_since_rebuild = 0

        await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

    if context:
        await context.close()

    if not page_texts:
        return None

    return {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "source_url": chapter_url,
        "chapter_slug": f"{manga_id}__ch-{chapter_num}",
        "text": "\n\n".join(page_texts),
        "pages": page_json,
    }


async def run_ocr_experiment_mode(chapter_urls: list[str]) -> None:
    print("🔤 المرحلة ١: تجربة استخراج النص الإنجليزي (OCR) — لن يُضغط أو يُحفَظ أي صورة، النتيجة نص+JSON فقط")
    profile = get_profile()
    print(f"⚙️ بروفايل الموقع: {profile['label']} ({SITE_PROFILE})")
    fetch_mode = profile.get("fetch_mode", "browser")

    ocr_dir = OUTPUT_DIR / "ocr_experiment"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    total = len(chapter_urls)
    results: list = []

    async def run_one(browser, i, url):
        try:
            return await ocr_process_chapter(browser, url, i, total, profile)
        except Exception as e:
            print(f"[{i}/{total}] ❌ خطأ غير متوقع أثناء تجربة OCR: {e}")
            return None

    if fetch_mode == "http":
        print("🚀 بروفايل HTTP مباشر — لن يُطلَق متصفح Chromium لهذه التشغيلة")
        for i, url in enumerate(chapter_urls, start=1):
            r = await run_one(None, i, url)
            if r:
                results.append(r)
    else:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            for i, url in enumerate(chapter_urls, start=1):
                r = await run_one(browser, i, url)
                if r:
                    results.append(r)
            await browser.close()

    files_written: list[Path] = []
    for r in results:
        out_dir = ocr_dir / r["chapter_slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        txt_path = out_dir / "text_en.txt"
        json_path = out_dir / "text_en.json"
        txt_path.write_text(r["text"], encoding="utf-8")
        json_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        files_written += [txt_path, json_path]

    run_zip_relpath = f"ocr_experiment/runs/run-{RUN_ID}.zip"
    run_zip_path = OUTPUT_DIR / run_zip_relpath
    run_zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_ok, zipped_count = True, 0
    try:
        with zipfile.ZipFile(run_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in files_written:
                if fp.is_file():
                    zf.write(fp, arcname=fp.relative_to(ocr_dir))
                    zipped_count += 1
    except Exception as e:
        zip_ok = False
        print(f"⚠️ تعذّر إنشاء zip تجربة OCR: {e}")

    if zip_ok:
        print(f"🗜️ أُنشئ أرشيف zip خاص بهذه التشغيلة فقط ({zipped_count} ملف): {run_zip_relpath}")

    if GIT_COMMIT_DIR:
        # يكتب حصرًا ضمن ocr_experiment/ — نفس فلسفة تقييد allowed_paths
        # المستخدمة بوضع التشخيص، لا يلمس manifest.json أو مجلدات الفصول
        ok, msg = await asyncio.to_thread(
            _commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH,
            f"تجربة OCR — {len(results)} فصل", ["ocr_experiment"],
        )
        print(f"{'✅' if ok else '⚠️'} دفع نتائج تجربة OCR: {msg}")

    print("\n" + "=" * 50)
    print(f"✅ اكتملت تجربة OCR لـ {len(results)}/{total} فصل")
    if len(results) < total:
        print(f"  ❌ فشل: {total - len(results)} فصل (راجع الرسائل أعلاه)")
    print(f"📁 النتائج محليًا في: {ocr_dir}")
    if zip_ok:
        print(f"🔗 أرشيف zip خاص بهذه التشغيلة فقط (نص+JSON لكل فصل): {OUTPUT_DIR}/{run_zip_relpath}")
    print("⚠️ تذكير: هذه تجربة — راجع البنود المُعلَّمة [sfx?] والتجميع قبل اعتماد الناتج نهائيًا")
    print("=" * 50)


