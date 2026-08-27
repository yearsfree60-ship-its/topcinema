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
- HTTP_CONCURRENCY — [جديد] نفس ثابت التوازي المستخدَم فعليًا بمسار
  الإنتاج الرئيسي (process_chapter بمسار HTTP)، يُعاد استخدامه هنا حرفيًا
  لتقييد عدد الفصول التي تُنزَّل صورها بالتوازي — راجع بند (1) أدناه.

[جديد — بند (1) من تحليل التسريع الفعلي] هذا الملف كان تسلسليًا بالكامل
سابقًا (فصل، ثم صفحاته، كلٌّ بانتظار الآخر). الآن: مسار HTTP يُشغِّل عدة
منتِجين (فصول، مقيَّدون بـHTTP_CONCURRENCY تمامًا كمسار الإنتاج) يُنزِّلون
الصور بالتوازي على حلقة asyncio، بينما مستهلك OCR واحد مشترك (يبقى على
خيط PaddleOCR المخصَّص الوحيد — لا تغيير على إصلاح أمان الخيوط) يسحب أي
صفحة جاهزة فور توفرها من أي فصل عبر asyncio.Queue. الفائدة: زمن الشبكة
لكل الفصول يتداخل مع زمن OCR (CPU) بدل أن يُضاف إليه تسلسليًا. مسار
المتصفح (غير HTTP) يبقى تسلسليًا بين الفصول (يطابق قيد مسار الإنتاج نفسه
بمعالجة الفصول بالمتصفح)، لكن يستخدم نفس تقنية منتِج/مستهلِك على مستوى
صفحات الفصل الواحد (تحميل الصفحة التالية يتداخل مع OCR الصفحة الحالية).
"""
import asyncio
import json
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

from compress_chapters import (
    GIT_BRANCH,
    GIT_COMMIT_DIR,
    HTTP_CONCURRENCY,
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

# [جديد — إصلاح جذري لعطل OCR المتناوب فصلًا-كاملًا، مؤكَّد ببحث خارجي فعلي:
# GitHub PaddlePaddle/PaddleOCR issue #16238 (يطابق حرفيًا "RuntimeError:
# std::exception" المرصود بلوجات هذا المشروع فعليًا) وتقارير مشابهة
# (#16362 / #16950 / #16196) ومناقشة #14567 (segfault فعلي مع
# ThreadPoolExecutor بأكثر من عامل خيط)] محرك الاستدلال الأصلي لـPaddle
# (predictor.run() بلغة C++) غير آمن عبر الخيوط: أول استدعاء predict() من
# خيط OS يبني/يهيّئ حالة داخلية مرتبطة بذلك الخيط تحديدًا، وأي استدعاء لاحق
# من خيط مختلف يفشل بـstd::exception. asyncio.to_thread (المستخدَم سابقًا
# بهذا الملف) يستخدم مجمَّع الخيوط الافتراضي لبايثون (عدة عمّال محتملين، لا
# ضمان أي خيط يُستخدَم لكل نداء) — وهذا يفسّر فعليًا التناوب "فصل ينجح
# بالكامل ثم الفصل التالي يفشل بالكامل من صفحته الأولى" المرصود بتشغيلة
# pickmeupgacha.com (79 فصل): لحظة وقوع أول predict() على خيط مختلف عن خيط
# التهيئة الأول، يفشل كل predict() لاحق يقع على ذلك الخيط بلا استثناء.
# الحل الموثَّق مجتمعيًا (مشروع rust-paddle-ocr المتخصص بأمان الخيوط لمحرك
# Paddle نفسه): تخصيص خيط واحد فقط يملك المحرك حصريًا طوال عمر البرنامج،
# وكل الطلبات تمر له عبر طابور/منفِّذ واحد — لا مجمَّع متعدد العمّال أبدًا.
# max_workers=1 هنا يضمن حرفيًا أن كل استدعاء OCR طوال التشغيلة الكاملة (كل
# الـ79 فصل) يقع فعليًا على نفس خيط OS الذي بُني عليه _PADDLEOCR_ENGINE أول
# مرة، بصرف النظر عن نشاط حلقة asyncio الأخرى (تحميل صور HTTP، النوم بين
# الصفحات...). يُبنى مرة واحدة على مستوى الوحدة (module-level) لا لكل فصل،
# كي يبقى نفس الخيط طوال التشغيلة كاملة، ويُغلَق صراحة بنهاية
# run_ocr_experiment_mode عبر _shutdown_ocr_thread().
_OCR_THREAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="paddleocr-single-thread"
)


async def _run_on_ocr_thread(func, *args):
    """يُشغِّل func (مزامَنة/blocking) حصرًا على خيط OCR المخصَّص الوحيد أعلاه،
    بدل asyncio.to_thread (مجمَّع افتراضي متعدد العمّال). يُستخدَم لكل نداء
    له علاقة بمحرك PaddleOCR (predict مباشرة أو إعادة بنائه) — أبدًا
    asyncio.to_thread مباشرة لأي من هذه العمليات، حفاظًا على ثبات الخيط."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_OCR_THREAD_EXECUTOR, func, *args)


def _shutdown_ocr_thread() -> None:
    """يُغلق منفِّذ خيط OCR المخصَّص بلطف بنهاية التشغيلة (تحرير الخيط ومحرك
    Paddle المحمَّل بذاكرته). لا يُستدعى بين الفصول — الاستمرارية على نفس
    الخيط طوال التشغيلة هي بيت القصيد من هذا الإصلاح."""
    _OCR_THREAD_EXECUTOR.shutdown(wait=True, cancel_futures=False)

# [تصحيح — PIR/oneDNN] النص الحرفي الذي يظهر في NotImplementedError عند خلل
# ConvertPirAttribute2RuntimeAttribute (issue #77340 على مستودع Paddle
# الرسمي). يُستخدَم كفحص نصي دقيق لا except عام، حتى لا نُخفي أخطاء أخرى
# فعلية تحت غطاء "fallback".
_PIR_ONEDNN_ERROR_MARKER = "ConvertPirAttribute2RuntimeAttribute"

# [جديد — طبقة أمان ثانية، تكمِّل الإصلاح الجذري بخيط OCR المخصَّص أعلاه
# (_OCR_THREAD_EXECUTOR)، لا تُغني عنه] رسائل تعطّل أصلي (native crash)
# معروفة موثَّقة فعليًا بمستودع PaddlePaddle/PaddleOCR الرسمي (issues
# #16238 / #16362 / #16950 / #16196) لأعطال متعددة الأسباب المحتملة داخل
# محرك C++ (تزامن خيطي، تراكم ذاكرة oneDNN...) — رسالتها **غير فارغة**
# خلافًا لاستثناء C++ الفارغ المُعالَج سابقًا، لذا لم تكن تُلتقَط إطلاقًا
# بالشرط القديم (`if str(e).strip(): raise`). يُطابَق هنا نص الرسالة حصرًا
# (لا Exception عام كامل) كي لا نُخفي أخطاء منطقية حقيقية أخرى (رابط صورة
# تالف، صيغة PNG غير صالحة...) تحت غطاء "fallback".
# [جديد — رُفِع من محاولة واحدة فقط بعد رصد فعلي بتشغيلة حقيقية: صفحتان
# متتاليتان (11 و12 من فصل 12 صفحة) فشلتا رغم إعادة البناء+محاولة واحدة،
# ما يعني أن محاولة واحدة لا تكفي دومًا (سواء لأن إعادة بناء المحرك
# يحتاج أكثر من مرة أحيانًا، أو لأن سببًا آخر غير عابر يتكرر). قابل
# للتعديل عبر متغير بيئة بنفس نمط بقية ثوابت الملف.
OCR_ENGINE_CRASH_MAX_RETRIES = int(os.environ.get("OCR_ENGINE_CRASH_MAX_RETRIES", "3"))
_NATIVE_ENGINE_CRASH_MARKERS = ("std::exception", "Unknown exception", "static Infer fail")

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

# [جديد — بند (1)] الحد الأقصى لعدد الصفحات "الجاهزة لكن لم تُستهلَك بعد"
# المسموح تراكمها بطابور التحميل/OCR المشترك، لكل مسار (HTTP متعدد الفصول
# أو المتصفح أحادي الفصل). صفحات ويبتون خام قد تكون عدة ميغابايت لكل
# صفحة — بلا سقف، لو تجاوزت سرعة التنزيل سرعة OCR (متوقَّع، لأن OCR على
# خيط واحد فقط) قد تتراكم عشرات الصفحات بالذاكرة بلا داعٍ. القيمة
# الافتراضية مرتبطة بـHTTP_CONCURRENCY (ضعف عدد الفصول المتوازية تقريبًا،
# كهامش تخزين مؤقت معقول) بدل رقم ثابت اعتباطي.
OCR_DOWNLOAD_QUEUE_SIZE = int(
    os.environ.get("OCR_DOWNLOAD_QUEUE_SIZE", str(max(2, HTTP_CONCURRENCY * 2)))
)


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


def _predict_with_engine_fallback(tmp_paths: list[str], diag: dict | None = None):
    """[عُدِّلت — بند (4) من تحليل التسريع: تجميع بلاطات] كانت تُستدعى لكل
    بلاطة على حدة (tmp_path مفرد)؛ الآن tmp_paths قائمة مسارات كل بلاطات
    الصفحة الواحدة، تُمرَّر لـpredict() بنداء واحد فقط (توثيق PaddleOCR
    الرسمي يؤكد أن input يقبل قائمة مسارات، وتُرجَع نتيجة واحدة لكل عنصر
    بنفس الترتيب) — يقلل overhead عبور حدود Python↔C++ لكل صفحة من (عدد
    البلاطات) نداء إلى نداء واحد، خصوصًا مؤثِّر بالصفحات الطويلة (4-5
    بلاطات). باقي منطق الاحتياط (PIR/oneDNN، تعطّل أصلي عام، إعادة
    المحاولة) بلا تغيير جوهري، يُعاد تطبيقه على الدفعة كاملة عند الفشل
    (لا بلاطة مفردة) — مقبول لأن أي فشل من هذا النوع مرتبط أصلًا بحالة
    المحرك نفسه (خيط/ذاكرة) لا بمحتوى بلاطة بعينها. خط الدفاع الأول
    الفعلي يبقى تشغيل كل نداءات predict() حصرًا على خيط OS المخصَّص
    (_OCR_THREAD_EXECUTOR بأعلى الملف)."""
    global _PADDLEOCR_ENGINE
    engine = _get_paddleocr_engine()
    generic_attempts = 0
    diag_str = (
        f" | تشخيص: صفحة#{diag.get('page_index')} "
        f"({diag.get('page_width')}×{diag.get('page_height')}px) — "
        f"{diag.get('tile_count')} بلاطة بدفعة واحدة، شكل أول بلاطة "
        f"{diag.get('tile_shape')}"
        if diag else ""
    )
    while True:
        try:
            return engine.predict(tmp_paths)
        except NotImplementedError as e:
            if _PIR_ONEDNN_ERROR_MARKER not in str(e) or _PADDLEOCR_MKLDNN_FALLBACK_DONE:
                raise
            engine = _reinit_paddleocr_engine_without_mkldnn()
            continue
        except Exception as e:
            msg = str(e).strip()
            is_known_native_crash = (not msg) or any(marker in msg for marker in _NATIVE_ENGINE_CRASH_MARKERS)
            if not is_known_native_crash or generic_attempts >= OCR_ENGINE_CRASH_MAX_RETRIES:
                if is_known_native_crash:
                    print(
                        f"  ❌ [OCR تشخيص فشل نهائي] استنفدت {generic_attempts} "
                        f"محاولة إعادة بناء لخطأ ({msg or 'رسالة فارغة'}){diag_str}"
                    )
                raise
            generic_attempts += 1
            print(
                f"  ⚠️ [OCR احتياطي] محاولة {generic_attempts}/{OCR_ENGINE_CRASH_MAX_RETRIES} — "
                f"استثناء محرك أصلي ({msg or 'رسالة فارغة'}){diag_str} — "
                "إعادة بناء محرك PaddleOCR ومحاولة دفعة هذه الصفحة مرة أخرى."
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


def ocr_extract_english_sync(raw_bytes: bytes, page_index: int | None = None) -> list[dict]:
    """يُشغَّل عبر _run_on_ocr_thread (خيط OCR المخصَّص). يُرجع صناديق نص خام
    بلا فرز/تجميع بعد: كل عنصر {bbox: [xmin,ymin,xmax,ymax], text: str,
    confidence: float}. [بند 2] الصورة تُقسَّم أولًا لبلاطات ثابتة الشكل
    (_tile_image_fixed_shape) بدل تمرير الصفحة كاملة بارتفاعها المتفاوت.
    [بند 4] كل بلاطات الصفحة تُكتَب كملفات مؤقتة أولًا، ثم تُمرَّر كقائمة
    مسارات واحدة لـpredict() بنداء واحد فقط (بدل نداء منفصل لكل بلاطة) —
    راجع توثيق _predict_with_engine_fallback. إحداثيات y لكل صندوق ناتج
    تُعوَّض بـy_offset البلاطة المطابقة (results[i] يقابل tiles[i] بنفس
    الترتيب) لتبقى الإحداثيات النهائية بمرجعية الصفحة الأصلية الكاملة كما
    كانت. page_index (اختياري، لأغراض التشخيص فقط) يُمرَّر لـ
    _predict_with_engine_fallback مع أبعاد الصفحة الفعلية — يظهر تلقائيًا
    برسائل الفشل بلا أي تغيير بمنطق الاستخراج نفسه."""
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    page_width, page_height = img.size
    tiles = _tile_image_fixed_shape(img)
    tile_count = len(tiles)

    tmp_paths: list[str] = []
    try:
        for tile_img, _y_offset in tiles:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            tile_img.save(tmp_path, format="PNG")
            tmp_paths.append(tmp_path)

        diag = {
            "page_index": page_index,
            "page_width": page_width,
            "page_height": page_height,
            "tile_count": tile_count,
            "tile_shape": f"{tiles[0][0].width}×{tiles[0][0].height}" if tiles else "-",
        }
        results = _predict_with_engine_fallback(tmp_paths, diag)
    finally:
        for p in tmp_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    if not results:
        return []

    all_items: list[dict] = []
    for (tile_img, y_offset), res in zip(tiles, results):
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


async def _ocr_handle_page(
    label: str,
    page_num: int,
    raw: bytes | None,
    reason: str | None,
    total_pages,
    page_texts: list,
    page_json: list,
    pages_since_rebuild: int,
) -> int:
    """[جديد — بند (1)] معالجة OCR لصفحة واحدة جاهزة (raw bytes مُنزَّلة
    مسبقًا)، مُستخرَجة كدالة مشتركة يستدعيها كل من مسار HTTP متعدد الفصول
    (_ocr_http_consumer) ومسار المتصفح أحادي الفصل (ocr_process_chapter) —
    نفس منطق المعالجة والتشخيص واحد فقط، لا نسختان منفصلتان قد تنحرفان.
    يُستدعى دومًا بترتيب page_num الصحيح تصاعديًا (يضمنه كل من المنتِج
    الواحد لكل فصل ونظام FIFO للطابور)، فـpage_texts.append/page_json.append
    تبقيان بالترتيب الصحيح بلا حاجة لفرز لاحق. pages_since_rebuild يُمرَّر
    ذهابًا وإيابًا صراحةً (بدل متغير عمومي) — بمسار HTTP يُمرَّره المستدعي
    كعدّاد **عام لكل التشغيلة** (لا لكل فصل) لأن إعادة البناء الوقائي [بند
    3] مرتبطة بتراكم الذاكرة الأصلية لمحرك OCR نفسه (خيط واحد مشترك بين كل
    الفصول الآن)، لا بحدود فصل بعينه — تغيير مقصود عن السلوك الأصلي (كان
    يُصفَّر كل فصل جديد) أصبح غير متماسك بعد أن صار الاستهلاك متداخلًا بين
    عدة فصول."""
    if not raw:
        print(f"  ⚠️ فشل تحميل {label} صفحة {page_num}: {reason}")
        return pages_since_rebuild

    rss_before = _current_rss_mb()
    try:
        items = await _run_on_ocr_thread(ocr_extract_english_sync, raw, page_num)
        sentences = group_ocr_lines_into_sentences(items)
        page_texts.append(format_ocr_page_text(page_num, sentences))
        page_json.append({"page": page_num, "sentences": sentences})
        sfx_count = sum(1 for s in sentences if s["sfx_suspect"])
        rss_after = _current_rss_mb()
        rss_note = (
            f" | RSS: {rss_before:.0f}→{rss_after:.0f}MB (Δ{rss_after - rss_before:+.0f})"
            if rss_before is not None and rss_after is not None else ""
        )
        print(f"  ✅ {label} صفحة {page_num}/{total_pages} — {len(sentences)} بند نص ({sfx_count} مُعلَّم [sfx?]){rss_note}")
    except Exception as e:
        rss_after = _current_rss_mb()
        rss_note = f" | RSS عند الفشل: {rss_after:.0f}MB" if rss_after is not None else ""
        print(f"  ⚠️ فشل OCR لـ{label} صفحة {page_num}: {e}{rss_note}")

    # [بند 3] إعادة بناء وقائية دورية — تحرّر أي تراكم ذاكرة أصلية متبقٍ
    # بصرف النظر عن نجاح/فشل الصفحة الحالية، فتُحتسَب الصفحات الفاشلة أيضًا
    # ضمن العداد (نفس تكلفة الاستدعاء على المحرك).
    pages_since_rebuild += 1
    if pages_since_rebuild >= OCR_ENGINE_REBUILD_EVERY_N_PAGES:
        print(
            f"  🔄 [OCR وقائي] إعادة بناء محرك PaddleOCR بعد "
            f"{pages_since_rebuild} صفحة (تحرير ذاكرة أصلية دوري، بند 3)"
        )
        await _run_on_ocr_thread(
            _reinit_paddleocr_engine, not _PADDLEOCR_MKLDNN_FALLBACK_DONE
        )
        pages_since_rebuild = 0
    return pages_since_rebuild


async def ocr_process_chapter(browser, chapter_url: str, index: int, total: int, profile: dict) -> dict | None:
    """مرآة لـprocess_chapter لكن بدل compress_image+حفظ صورة: OCR على raw
    مباشرة (أبدًا على نسخة مضغوطة). يعيد استخدام get_chapter_images كاملة —
    نفس بروفايل الموقع ونفس منطق إعادة المحاولة المستخدم بالإنتاج الفعلي.
    [جديد — بند (1)، مسار المتصفح] يُستخدَم فقط عندما fetch_mode != "http"
    (المتصفح يبقى تسلسليًا بين الفصول — يطابق قيد process_chapter بمسار
    الإنتاج نفسه لهذا المسار، لا Semaphore/gather هناك أيضًا لمعالجة
    الفصول بالمتصفح). لكن **داخل** الفصل الواحد: منتِج يُنزِّل الصفحات
    بالتتابع (يحترم IMG_FETCH_DELAY_MS كما كان) بينما مستهلك مستقل (على
    خيط asyncio نفسه، لا خيط OS إضافي) يستهلك عبر asyncio.Queue — بينما
    المستهلك ينتظر predict() على خيط OCR المخصَّص، المنتِج يواصل تحميل
    الصفحة التالية على حلقة asyncio الرئيسية، فيتداخل زمن الشبكة مع زمن
    OCR بدل انتظار تسلسلي صرف."""
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
    total_pages = len(image_urls)
    label = f"[{index}/{total}]"

    queue: asyncio.Queue = asyncio.Queue(maxsize=OCR_DOWNLOAD_QUEUE_SIZE)

    async def producer():
        for i, img_url in enumerate(image_urls, start=1):
            raw, reason = await download(img_url)
            await queue.put((i, raw, reason))
            await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

    async def consumer():
        pages_since_rebuild = 0
        for _ in range(total_pages):
            i, raw, reason = await queue.get()
            pages_since_rebuild = await _ocr_handle_page(
                label, i, raw, reason, total_pages, page_texts, page_json, pages_since_rebuild,
            )

    producer_task = asyncio.create_task(producer())
    await consumer()
    # المستهلك استهلك بالضبط total_pages عنصر، فالمنتِج انتهى فعليًا هنا —
    # هذا await لا ينتظر عمليًا، فقط يُعيد رفع أي استثناء غير متوقَّع من
    # المنتِج (مثلًا تحميل صورة رمى استثناءً لم يُلتقَط داخل download نفسه)
    # بدل ابتلاعه صامتًا بمهمة خلفية منسية.
    await producer_task

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


async def _ocr_http_chapter_producer(
    sem: asyncio.Semaphore, queue: asyncio.Queue, index: int, url: str, total: int, profile: dict,
) -> None:
    """[جديد — بند (1)، مسار HTTP] منتِج واحد لكل فصل، مقيَّد بـHTTP_CONCURRENCY
    عبر sem (نفس نمط process_chapter بمسار الإنتاج الرئيسي — راجع
    asyncio.Semaphore(HTTP_CONCURRENCY) هناك). يجلب قائمة صور الفصل أولًا،
    ثم يُنزِّل صفحاته بالتتابع (يحترم IMG_FETCH_DELAY_MS كسابقًا) ويدفع كل
    صفحة جاهزة فورًا لطابور OCR المشترك بدل انتظار استهلاكها — عدة منتِجين
    (حتى HTTP_CONCURRENCY فصل) يعملون بالتوازي فعليًا على حلقة asyncio
    الواحدة. get_chapter_images بمسار HTTP لا تُرجع context أبدًا (مؤكَّد من
    كود compress_chapters.py — يُعيد None صراحة لهذا المسار)، فلا حاجة
    لإغلاقه هنا خلافًا لمسار المتصفح."""
    async with sem:
        try:
            _context, image_urls, fail_reason = await get_chapter_images(None, url, profile)
        except Exception as e:
            print(f"[{index}/{total}] ❌ خطأ غير متوقع أثناء جلب صور الفصل: {e}")
            await queue.put(("ERROR", index, None, None))
            return

        if not image_urls:
            print(f"[{index}/{total}] ❌ {fail_reason or 'لم يُعثر على صور في هذا الفصل'}")
            await queue.put(("ERROR", index, None, None))
            return

        manga_id, chapter_num = manga_slug_from_url(url)
        print(f"[{index}/{total}] 🔤 تجربة OCR: {url} — بروفايل: {profile['label']} ({len(image_urls)} صفحة)")

        for i, img_url in enumerate(image_urls, start=1):
            raw, reason = await fetch_image_bytes_http(img_url, url)
            await queue.put(("PAGE", index, i, (raw, reason)))
            await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

        await queue.put(("DONE", index, len(image_urls), {
            "manga_id": manga_id,
            "chapter_num": chapter_num,
            "source_url": url,
            "chapter_slug": f"{manga_id}__ch-{chapter_num}",
        }))


async def _ocr_http_consumer(queue: asyncio.Queue, total_chapters: int) -> list:
    """[جديد — بند (1)، مسار HTTP] المستهلك الوحيد المشترك بين كل الفصول —
    يسحب أي عنصر جاهز فور توفره بصرف النظر عن الفصل الذي جاء منه، ويُشغِّل
    OCR حصرًا على خيط PaddleOCR المخصَّص (_run_on_ocr_thread، بلا تغيير على
    إصلاح أمان الخيوط). بينما هذا الاستدعاء ينتظر predict() على الخيط
    المخصَّص، منتِجو الفصول الأخرى (حتى HTTP_CONCURRENCY بالتوازي) يواصلون
    التحميل على حلقة asyncio الرئيسية — زمن الشبكة الكلي لكل الفصول يتداخل
    مع زمن OCR بدل أن يُضاف إليه تسلسليًا. ترتيب صفحات كل فصل على حدة
    مضمون رغم التداخل بين الفصول: كل منتِج فصل يدفع صفحاته للطابور المشترك
    بترتيب تصاعدي، وطابور FIFO يحافظ على الترتيب النسبي لعناصر أي مصدر
    واحد حتى مع تداخل مصادر أخرى بينها. ينتهي بالضبط عندما يصل DONE/ERROR
    من كل فصل — وبما أن كل منتِج يدفع DONE/ERROR بعد كل صفحاته دومًا (لا
    قبلها)، وصول هذه الإشارة لآخر فصل متبقٍ يعني حتمًا استهلاك كل صفحاته
    فعليًا قبلها."""
    chapters: dict[int, dict] = {}
    finalized: dict[int, dict | None] = {}
    remaining_producers = total_chapters
    pages_since_rebuild = 0  # عدّاد عام للتشغيلة كاملة — راجع تعليق _ocr_handle_page

    def acc(idx: int) -> dict:
        return chapters.setdefault(idx, {
            "page_texts": [], "page_json": [], "meta": None, "total_pages": None, "n_done": 0,
        })

    def maybe_finalize(idx: int) -> None:
        c = chapters.get(idx)
        if c is None or c["meta"] is None or c["total_pages"] is None:
            return
        if c["n_done"] < c["total_pages"]:
            return
        if c["page_texts"]:
            finalized[idx] = {
                **c["meta"],
                "text": "\n\n".join(c["page_texts"]),
                "pages": c["page_json"],
            }
        else:
            finalized[idx] = None
        del chapters[idx]

    while remaining_producers > 0:
        kind, index, a, b = await queue.get()
        if kind == "ERROR":
            remaining_producers -= 1
            finalized.setdefault(index, None)
            continue
        if kind == "DONE":
            c = acc(index)
            c["total_pages"] = a
            c["meta"] = b
            remaining_producers -= 1
            maybe_finalize(index)
            continue
        # kind == "PAGE"
        c = acc(index)
        page_num = a
        raw, reason = b
        label = f"فصل#{index}"
        pages_since_rebuild = await _ocr_handle_page(
            label, page_num, raw, reason, c["total_pages"] or "?",
            c["page_texts"], c["page_json"], pages_since_rebuild,
        )
        c["n_done"] += 1
        maybe_finalize(index)

    return [finalized[i] for i in sorted(finalized) if finalized[i] is not None]


async def run_ocr_experiment_mode(chapter_urls: list[str]) -> None:
    print("🔤 المرحلة ١: تجربة استخراج النص الإنجليزي (OCR) — لن يُضغط أو يُحفَظ أي صورة، النتيجة نص+JSON فقط")
    profile = get_profile()
    print(f"⚙️ بروفايل الموقع: {profile['label']} ({SITE_PROFILE})")
    fetch_mode = profile.get("fetch_mode", "browser")

    ocr_dir = OUTPUT_DIR / "ocr_experiment"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    total = len(chapter_urls)
    results: list = []

    try:
        if fetch_mode == "http":
            # [بند 1] منتِجون متعددون (فصول، مقيَّدون بـHTTP_CONCURRENCY —
            # نفس نمط مسار الإنتاج الرئيسي) + مستهلك OCR واحد مشترك، عوضًا
            # عن التسلسل الكامل السابق (فصل، ثم التالي، بلا أي تزامن).
            print("🚀 بروفايل HTTP مباشر — لن يُطلَق متصفح Chromium لهذه التشغيلة")
            print(
                f"⚙️ [بند 1] تحميل حتى {HTTP_CONCURRENCY} فصل بالتوازي، "
                f"مستهلك OCR واحد مشترك (سعة طابور: {OCR_DOWNLOAD_QUEUE_SIZE})"
            )
            queue: asyncio.Queue = asyncio.Queue(maxsize=OCR_DOWNLOAD_QUEUE_SIZE)
            sem = asyncio.Semaphore(HTTP_CONCURRENCY)
            producer_tasks = [
                asyncio.create_task(_ocr_http_chapter_producer(sem, queue, i, url, total, profile))
                for i, url in enumerate(chapter_urls, start=1)
            ]
            consumer_task = asyncio.create_task(_ocr_http_consumer(queue, total))
            await asyncio.gather(*producer_tasks)
            results = await consumer_task
        else:
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
                for i, url in enumerate(chapter_urls, start=1):
                    try:
                        r = await ocr_process_chapter(browser, url, i, total, profile)
                    except Exception as e:
                        print(f"[{i}/{total}] ❌ خطأ غير متوقع أثناء تجربة OCR: {e}")
                        r = None
                    if r:
                        results.append(r)
                await browser.close()
    finally:
        # [جديد] إغلاق خيط OCR المخصَّص فور انتهاء آخر استخدام فعلي له —
        # كل معالجة الفصول (وبالتالي كل نداءات predict) انتهت هنا، وما
        # تبقى (كتابة ملفات/zip/دفع git) لا علاقة له بمحرك OCR إطلاقًا.
        # finally يضمن الإغلاق حتى لو استُثنِي خطأ غير متوقَّع.
        _shutdown_ocr_thread()

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
