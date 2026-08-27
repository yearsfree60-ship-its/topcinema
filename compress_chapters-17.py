#!/usr/bin/env python3
"""
يقرأ قائمة روابط فصول (سطر لكل رابط) من متغيرات البيئة، يستخرج روابط الصور،
يحمّلها، يضغطها فعليًا بمكتبة Pillow، ويحفظها في مجلد الإخراج مع ملف
manifest.json يصف كل مانهوا وفصولها وروابط صورها النهائية.

============================== بروفايلات المواقع ==============================
- azorafly    → HTTP مباشر بدون متصفح إطلاقًا (معالجة متزامنة محدودة).
- mangatuk    → متصفح حقيقي، لقطة واحدة بدون تمرير، بدون فلترة ودجات.
- mangatime   → متصفح حقيقي + تمرير تراكمي إجباري + فلترة ودجات.
- olympustaff → متصفح حقيقي (يجتاز Cloudflare تلقائيًا)، بدون تمرير، مع فلترة
                ودجات.
- procomic    → HTTP مباشر. لا توجد وسوم <img> فعلية بالـHTML الخام إطلاقًا؛
                الصور تصل فقط عبر آخر ملاذ نصي عام (JSON/script مُضمَّن).
                تُطبَّق تصفية allowlist صارمة بنمط '/pN/' بمسار الرابط
                لاستبعاد صورة OG/SEO المصغّرة ونسخة CDN المكررة لصفحة1، مع
                فرز الصفحات برقمها الفعلي بدل ترتيب ظهورها بالنص الخام.
- auto        → السلوك العام الآمن الافتراضي.
================================================================================

============================== وضع التشخيص (DIAGNOSTIC_MODE) — موسّع ==========
يفحص كل رابط مُدخَل بخمس مراحل مستقلة (لا يُنزّل/يضغط أي فصل فعليًا):

  ① فحص HTTP خام — نفس أسلوب azorafly، لمعرفة هل الصور موجودة بالـHTML الثابت.

  ② فحص متصفح كامل — منحنى نمو عدد الصور بثلاث لحظات، مطابقة المحددات
     الحالية، فلترة الودجات، توزيع النطاقات، لقطة شاشة مرجعية.

  ③ فحص حماية السرقة (hotlink) على صورة عينة — مباشر بلا جلسة مقابل عبر
     جلسة المتصفح.

  ④ [جديد] ملف تعريف الحماية الكامل — يجمع من كل ما سبق:
     - تصنيف اسم مزوّد الحماية تحديدًا (Cloudflare/PerimeterX/DataDome/
       Imperva/Akamai/hCaptcha/reCAPTCHA/Sucuri/جدار مانع إعلانات) بمطابقة
       توقيعات نصية معروفة على HTML الثابت وعنوان/جسم صفحة المتصفح معًا.
     - رصد طلبات الشبكة الفعلية أثناء تحميل الصفحة بالمتصفح مقابل نطاقات
       معروفة لكل مزوّد — دليل مباشر أدق من مطابقة النص وحدها.
     - جدار مانع الإعلانات (إن وُجد): قياس فعلي (لا تخمين) لعدد الثواني
       حتى يصبح زر التجاوز قابلًا للضغط، ثم ضغطه وإعادة قياس عدد الصور
       بعده للتأكد من ظهور المحتوى الحقيقي.
     - اختبار إعادة استخدام الكوكيز: بعد أي تحدٍّ يحلّه المتصفح، تُجرَّب
       نفس الكوكيز بطلب HTTP عادي بدون متصفح — يجاوب: هل حل التحدي مرة
       واحدة بالمتصفح ثم HTTP سريع لكل الفصول التالية استراتيجية ممكنة؟
     - ترويسات موسّعة: retry-after, x-sucuri-id, x-datadome, x-iinfo
       (Incapsula), cf-cache-status, cf-mitigated.

  ⑤ [جديد] فحص تحديد المعدل (Rate Limiting) — عدة طلبات HTTP سريعة متتالية
     لنفس الرابط، رصد 429/403 أو ترويسة Retry-After — يفيد تحديد
     HTTP_CONCURRENCY الآمن لهذا الموقع تحديدًا بدل التخمين.

نتيجة كل هذا: بيانات خام تفصيلية فقط (لا توصية آلية مُركَّبة — لا يوجد بالكود
أي دالة تُركِّب قرار fetch_mode/do_scroll/do_widget_filter النهائي من هذه
الحقول؛ القرار يُتَّخذ يدويًا بقراءة التقرير، تحديدًا: هل static_probe يفشل
بثبات؟ هل images_at_t0 يساوي images_after_wait (لا حاجة تمرير)؟ هل
widget_excluded_count > 0 بثبات (يلزم فلتر ودجات)؟)، مع ملف JSON تفصيلي +
لقطة شاشة لكل رابط في output/diagnostics، مرفوعة كأرتيفاكت GitHub Actions
مستقل، ومدفوعة لفرع output. كما يُبنى أرشيف zip خاص بهذه التشغيلة فقط
(output/diagnostics/runs/run-<RUN_ID>.zip، راجع قسم الإضافات أدناه) برابط
raw.githubusercontent.com مباشر — يعمل تنزيله بلا تسجيل دخول، بما يشمل
أندرويد حيث تنزيل أرتيفاكت GitHub Actions غير موثوق دومًا.
================================================================================

ملاحظات تصميم عامة أخرى (تراكمت من التشخيص الفعلي عبر المحادثة):

1) لا يعتمد أي مسار متصفح على "networkidle" لاعتبار الصفحة جاهزة.
2) الحكم بنجاح/فشل تحميل صفحة يعتمد على وجود صور مستخرجة فعليًا، لا حدث goto.
3) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط (حد WebP الصارم 16383 بكسل).
4) manifest.json يُدمَج مع أحدث نسخة بعيدة، ويشمل كل نتائج التشغيلة المتراكمة
   حتى هذه اللحظة (لا الفصل الحالي وحده) لتفادي فقدان صامت لفصول سابقة.
5) استراتيجية إعادة محاولة الدفع: fetch + reset مختلط، بدل git rebase الهش.
6) الدفع التدريجي محمي بقفل asyncio.Lock واحد مشترك حتى مع HTTP بالتوازي.
7) كل فصل معزول بـtry/except في حلقة المعالجة الرئيسية.
8) لكل تشغيلة manifest مستقل خاص بها: output/runs/run-<RUN_ID>.json — لا
   يُدمَج مع الأرشيف الرئيسي ولا يؤثر عليه، والصور نفسها مشتركة بلا نسخ.
9) المطابقة بمنطق الدمج على sourceUrl/num الفعلي لا chNum المشتق (يتصادم
   لأي فصل رقمه غير عددي بحت).
10) رابط مكرر بالمدخلات يُستبعد (مهم خصوصًا مع HTTP_CONCURRENCY لمنع تعارض
    كتابة ملفات فعلي على نفس مجلد الفصل من نسختين متزامنتين).

================================== إصلاحات ====================================
[تصحيح حرج ١] عمليات git (add/read remote manifest) كانت تستخدم المسار
  الحرفي الثابت "output" بدل احترام OUTPUT_DIR القابل للتخصيص عبر متغير
  بيئة. أي تشغيلة بـOUTPUT_DIR مختلف كانت تفقد نتائجها بصمت (git لا يجد
  تغييرات لأنه يراقب مجلدًا فارغًا). الآن تُستخدم OUTPUT_DIR فعليًا،
  ومسار الدفع نسبي لمجلد GIT_COMMIT_DIR (يُتحقق من أن OUTPUT_DIR فرع من
  GIT_COMMIT_DIR وإلا يُبلَّغ الخطأ بوضوح بدل فشل صامت).
[تصحيح حرج ٢] استخراج الصور من <noscript> (بمساري HTTP والمتصفح) كان يثق
  بأول كتلة noscript تحوي أي <img> دون تحقق، فقد يخطف بكسل تتبع/تحليلات لا
  علاقة له بالمحتوى ويُسقط الاستخراج الحقيقي بصمت. الآن يُشترط عدد أدنى من
  الصور (MIN_NOSCRIPT_IMAGES) قبل اعتماد نتيجة noscript كمصدر نهائي، وإلا
  يُتابَع للطرق الأخرى (data-src / src عادي).
[تصحيح حرج ٣] عمليات git الفرعية (fetch/show/add/commit/push) لم تكن
  محمية من استثناءات غير متوقعة (git غير مثبت، GIT_COMMIT_DIR ليس
  مستودعًا، صلاحيات...) فتوقف السكربت كاملًا بدل معالجة الخطأ بلطف. الآن
  _run_git تُغلَّف بـtry/except وتُرجع نتيجة فاشلة واضحة بدل رمي استثناء.
[إضافة موقع جديد — procomic] تشخيص فعلي (JSON مرفق من المستخدم على رابط
  فصل حقيقي) كشف أن procomic.net لا يملك وسوم <img> فعلية بالـHTML الخام
  إطلاقًا (noscript/data-src/plain-src كلها صفر) — الصور تصل فقط عبر آخر
  ملاذ نصي عام بـextract_images_from_html (مسح regex على النص الخام يلتقط
  روابط JSON مُضمَّن مسبقًا، نمط شائع بتطبيقات SSR كـNext.js). كذلك فحص
  المتصفح الكامل غير موثوق هنا (191 صورة بعد التمرير، 0 منها طابق أي محدد
  محتوى معروف، وغالبيتها أيقونات واجهة procomic.net نفسه + صورة إعلان من
  s3.pubfuture.com). الاستخراج النصي العام رغم نجاحه يُرجع مزيجًا يحتاج
  تصفية: صورة OG/SEO مصغّرة واحدة (لا علاقة لها بصفحات الفصل)، ونسخة
  معاينة مكررة لصفحة1 على cdn3.procomic.net (نفس اسم الملف الأساسي، لكن
  بمسار بلا مجلد صفحة 'pN'، بعكس كل صور المحتوى الحقيقية التي تمر حصرًا
  عبر app.procomic.net/chapters/{manga}/{chapter}/pN/...). أُضيفت آلية
  allowlist عامة قابلة لإعادة الاستخدام لأي بروفايل مستقبلي مشابه
  (http_content_pattern) بدل حل مخصص صلب لـprocomic وحده — راجع
  _apply_http_content_filter و_page_number_from_url أدناه.
[تصحيح حرج ٤] عند تعارض دفع (push غير fast-forward بسبب تشغيلة GitHub
  Actions أخرى منفصلة دفعت بينما هذه التشغيلة كانت تعالج)، منطق إعادة
  المحاولة كان يعمل: fetch ثم "git reset origin/<branch>" (ينقل الفهرس
  ليطابق البعيد الجديد بلا لمس القرص إطلاقًا) ثم "git add <مجلد الإخراج
  كامل>". المشكلة: لو التشغيلة الأخرى الناجحة أضافت ملفات (runs/run-
  <معرّف آخر>.json، أو صور فصل مانهوا مختلف) غير موجودة على قرص هذه
  التشغيلة (كل تشغيلة worktree مستقل من الصفر)، فإن "git add" (يشمل رصد
  الحذف ضمنيًا منذ git 2.0) كان يعتبرها "محذوفة" من القرص ويُدرج حذفها
  بالـcommit التالي — فيُدفَع هذا الحذف فعليًا، ماحيًا بصمت نتيجة تشغيلة
  أخرى ناجحة تمامًا (لوحظ فعليًا: ملف runs/run-<id>.json لتشغيلة نجحت
  ودفعت بنجاح حسب سجلّها الخاص، اختفى لاحقًا من الفرع البعيد). محاولة
  الإصلاح الأولى قيّدت "git add" بعد reset فقط (عبر git diff --name-only
  المُلتقَط بعد أول commit)، لكنها تركت أول "git add" بكل استدعاء (قبل أي
  تعارض) بلا تقييد.
[تصحيح حرج ٥] اكتُشف أن تصحيح ٤ غير مكتمل: بعد أول تعارض يُحلّ بنجاح ضمن
  نفس التشغيلة (فصل رقم 1 مثلًا)، يصبح HEAD المحلي يطابق origin عند لحظة
  الـreset — وهو يتضمن بالفهرس ملفات تشغيلات أخرى (runs/run-<آخر>.json…)
  غائبة فعليًا عن قرص هذا الـworktree. عند اكتمال الفصل التالي (استدعاء
  جديد لـ_commit_and_push_sync عبر push_now)، أول "git add <مجلد الإخراج
  كامل>" بذلك الاستدعاء (غير المحمي بمنطق ٤، لأنه قبل أي reset في هذا
  الاستدعاء تحديدًا) يقارن القرص بهذا الفهرس "الملوَّث"، يعتبر تلك الملفات
  محذوفة، ويدفع حذفها — أحيانًا من أول محاولة push دون حتى المرور بمسار
  إعادة المحاولة، أي بصمت أشد. الإصلاح الجذري: التخلي كليًا عن أي
  "git add <مجلد>" (بأي موضع، أول إضافة أو بعد reset) واستبداله بقائمة
  مسارات صريحة (whitelist) تُبنى من بيانات التشغيلة نفسها لا من فحص فرق
  git التفاعلي: manifest.json + runs/run-<RUN_ID>.json + مجلد كل فصل
  كُتب فعليًا ضمن `results` حتى هذه اللحظة (وفي وضع التشخيص: مجلد
  diagnostics بكامله فقط). _commit_and_push_sync أصبحت تتطلب allowed_paths
  (نسبية لـOUTPUT_DIR) صراحةً من كل مستدعٍ، وتُستخدم نفس القائمة في كل
  عمليات git add بلا استثناء — أول إضافة وإعادة المحاولة بعد reset على حد
  سواء — فلا تُلمَس إطلاقًا أي مسارات لم تكتبها هذه التشغيلة، بصرف النظر
  عن حالة الفهرس بعد أي عدد من عمليات reset.
  (خطوة "دفع احتياطي نهائي" بملف الـworkflow لا تزال تستخدم "git add
  output" غير المقيّد بالكامل — إصلاحها بند منفصل لاحق).
[إضافة — أرشيف zip لتقارير التشخيص خاص بكل تشغيلة] output/diagnostics/
  يتراكم عبر التشغيلات (worktree يسحب فرع output الحالي بتاريخه كاملًا قبل
  التشغيل)، فلا هو ولا artifact الأكشن يمثلان فعليًا "هذه التشغيلة فقط" —
  فقط summary.json كان مضبوطًا هكذا. أُضيف output/diagnostics/runs/run-
  <RUN_ID>.zip (نفس نمط RUN_MANIFEST_RELPATH للفصول) يجمع حصرًا: summary.json
  + تقرير كل رابط بهذه التشغيلة + لقطتَي شاشته (الفحص الأول والثاني)، عبر
  حقل diagnostic_run_files المُسجَّل داخل كل report (لا بإعادة تخمين slug
  المبني جزئيًا على hash() العشوائي البذرة لكل عملية بايثون). الهدف رابط
  raw.githubusercontent.com مباشر بلا تسجيل دخول يُنزَّل بموثوقية على
  أندرويد، بعكس تنزيل أرتيفاكت GitHub Actions المعتمد على واجهة/جلسة الموقع
  (يبقى الأخير متاحًا كنسخة احتياطية، لم يُحذف).
[فصل بنيوي — تقسيم الملف لثلاثة] كان هذا الملف يحوي أيضًا قسم استخراج
  النص (OCR) وقسم التشخيص الموسّع كاملَين. فُصلا الآن لملفين شقيقين مستقلين
  (نفس مجلد هذا الملف تحديدًا — الـworkflow يشغّل "python compress_
  chapters.py" مباشرة بلا مسار حزمة، فالاستيراد البسيط يتطلب ذلك):
    - ocr_extraction.py  → قسم استخراج النص الإنجليزي (PaddleOCR) بالكامل.
    - diagnostics.py     → قسم التشخيص الموسّع بالكامل، ومعه 5 دوال كانت هنا
      (تاريخ التشخيص + معلومات الشبكة/TLS) لأنها لا تُستخدَم إلا منه.
  هذا الملف (compress_chapters.py) بقي هو النواة المشتركة + نقطة الدخول
  main() فقط. الاستيراد من الملفين الجديدين مؤجَّل (lazy) داخل main() نفسها
  لتفادي استيراد دائري — راجع التعليق عند نقطتَي DIAGNOSTIC_MODE/
  OCR_EXPERIMENT_MODE بالأسفل. فصل بنيوي بحت — لا تغيير سلوك.
================================================================================
"""
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import requests.adapters  # استيراد صريح — كان يعمل سابقًا فقط بأثر جانبي غير موثّق
from PIL import Image
from io import BytesIO
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# [تحسين احترافي — إخفاء بصمة المتصفح] كان يوجد سطر واحد يدوي فقط يعطّل
# navigator.webdriver، وهو غير كافٍ أمام كشف 2026 (WebGL/plugins/UA-CH
# ...). playwright-stealth (نشط الصيانة، إصدار 2.x بواجهة apply_stealth_async
# لكل context) يعالج مجموعة أوسع من إشارات الكشف دفعة واحدة. يُنشأ كائن
# واحد مشترك لتفادي إعادة بناء حمولة JS في كل فصل — راجع open_and_collect.
_STEALTH = Stealth()

# [تحسين احترافي — صيغة الإخراج] AVIF اختياري عبر IMG_FORMAT (افتراضيًا
# webp للحفاظ على التوافق والسرعة). يتطلب pillow-avif-plugin مثبّتًا
# ومستوردًا قبل أي img.save(..., format="AVIF") وإلا يفشل الحفظ بصمت
# برسالة "unknown file extension". الاستيراد هنا مشروط كي لا يفشل السكربت
# كاملًا لو IMG_FORMAT=webp والمكتبة غير مثبتة أصلًا بتلك التشغيلة.
IMG_FORMAT = os.environ.get("IMG_FORMAT", "webp").strip().lower()
if IMG_FORMAT not in ("webp", "avif"):
    print(f"⚠️ IMG_FORMAT غير معروف '{IMG_FORMAT}' — الرجوع لـwebp")
    IMG_FORMAT = "webp"
if IMG_FORMAT == "avif":
    try:
        import pillow_avif  # noqa: F401  — يسجّل مشفّر/فاكّ AVIF لدى Pillow بأثر جانبي
    except ImportError:
        print("⚠️ IMG_FORMAT=avif لكن pillow-avif-plugin غير مثبّت — الرجوع لـwebp")
        IMG_FORMAT = "webp"

def _clamp_int(raw_value: str, default: int, lo: int, hi: int, name: str) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        print(f"⚠️ قيمة غير صالحة لـ{name}='{raw_value}' — استخدام الافتراضي {default}")
        return default
    if value < lo or value > hi:
        clamped = max(lo, min(hi, value))
        print(f"⚠️ {name}={value} خارج النطاق المسموح [{lo}, {hi}] — تم ضبطه إلى {clamped}")
        return clamped
    return value


QUALITY = _clamp_int(os.environ.get("IMG_QUALITY", "25"), 25, 1, 100, "IMG_QUALITY")
MAX_WIDTH = _clamp_int(os.environ.get("IMG_MAX_WIDTH", "700"), 700, 50, 10000, "IMG_MAX_WIDTH")
CHAPTER_URLS_RAW = os.environ.get("CHAPTER_URLS", "")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
CDN_BASE = os.environ.get("CDN_BASE", "")

NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))
CONTENT_WAIT_MS = int(os.environ.get("CONTENT_WAIT_MS", "20000"))
CONTENT_POLL_MS = int(os.environ.get("CONTENT_POLL_MS", "800"))
RETRY_PER_CHAPTER = int(os.environ.get("RETRY_PER_CHAPTER", "2"))

SCROLL_MAX_STEPS = int(os.environ.get("SCROLL_MAX_STEPS", "400"))
SCROLL_STEP_WAIT_MS = int(os.environ.get("SCROLL_STEP_WAIT_MS", "350"))
SCROLL_MAX_TOTAL_SEC = int(os.environ.get("SCROLL_MAX_TOTAL_SEC", "90"))

STRICT_DOMAIN_FILTER = os.environ.get("STRICT_DOMAIN_FILTER", "0") == "1"

ENABLE_INCREMENTAL_PUSH = os.environ.get("ENABLE_INCREMENTAL_PUSH", "true").strip().lower() == "true"
GIT_COMMIT_DIR = os.environ.get("GIT_COMMIT_DIR", "").strip() or None
GIT_BRANCH = os.environ.get("GIT_BRANCH", "output").strip() or "output"

RUN_ID = os.environ.get("RUN_ID", "").strip() or f"local-{int(time.time())}"
RUN_MANIFEST_RELPATH = f"runs/run-{RUN_ID}.json"

IMG_FETCH_RETRIES = int(os.environ.get("IMG_FETCH_RETRIES", "3"))
IMG_FETCH_DELAY_MS = int(os.environ.get("IMG_FETCH_DELAY_MS", "120"))

HTTP_CONCURRENCY = _clamp_int(os.environ.get("HTTP_CONCURRENCY", "3"), 3, 1, 10, "HTTP_CONCURRENCY")

SKIP_EXISTING_CHAPTERS = os.environ.get("SKIP_EXISTING_CHAPTERS", "true").strip().lower() == "true"

DIAGNOSTIC_MODE = os.environ.get("DIAGNOSTIC_MODE", "false").strip().lower() == "true"

# [جديد — تجربة OCR] وضع منفصل تمامًا عن DIAGNOSTIC_MODE: يستخدم بروفايل
# الموقع الفعلي (SITE_PROFILE) ونفس منطق الجلب الحقيقي (get_chapter_images)
# بدل تجاهله، لكن بدل الضغط/الحفظ يُشغِّل OCR إنجليزي فقط على كل صورة خام
# ويكتب نصًا+JSON مرتبَين بدل صور. لا يلمس manifest.json ولا مجلدات الفصول
# العادية إطلاقًا — يكتب حصرًا ضمن output/ocr_experiment/.
OCR_EXPERIMENT_MODE = os.environ.get("OCR_EXPERIMENT_MODE", "false").strip().lower() == "true"

WEBP_HARD_LIMIT = 16000

# [إصلاح منطقي ج] حد أدنى لأبعاد الصورة (طول/عرض) كي تُعتبر صفحة مانهوا
# حقيقية لا صورة بديلة/حظر صغيرة — راجع _validate_image_bytes.
MIN_IMAGE_DIMENSION = _clamp_int(
    os.environ.get("MIN_IMAGE_DIMENSION", "150"), 150, 10, 2000, "MIN_IMAGE_DIMENSION"
)

# [تصحيح حرج ١] الحد الأدنى لعدد صور noscript قبل اعتمادها كمصدر نهائي —
# يمنع خطف بكسل تتبع/تحليلات وحيد داخل <noscript> لا علاقة له بالمحتوى.
MIN_NOSCRIPT_IMAGES = 2

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_HTTP_SESSION = requests.Session()
_HTTP_ADAPTER = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
_HTTP_SESSION.mount("http://", _HTTP_ADAPTER)
_HTTP_SESSION.mount("https://", _HTTP_ADAPTER)


class _NoCookiePolicy(__import__("http.cookiejar", fromlist=["DefaultCookiePolicy"]).DefaultCookiePolicy):
    """يمنع _HTTP_SESSION المشتركة من تخزين أي كوكيز واردة إطلاقًا. بدون هذا،
    كل استجابة (بما فيها فحص إعادة استخدام الكوكيز بوضع التشخيص) كانت تُراكم
    كوكيزها داخل جلسة الاتصال المشتركة — تلوّث حالة غير مقصود بين طلبات غير
    مرتبطة، ونمو غير محدود عبر تشغيلة طويلة تضم مئات الفصول. البروفايلات التي
    تستخدم fetch_mode='http' (أزورافلاي) لا تحتاج كوكيز أصلًا، فتعطيلها هنا
    آمن تمامًا ويُبقي الفائدة الحقيقية من الجلسة المشتركة (تجميع اتصالات)."""

    def set_ok(self, cookie, request):
        return False


_HTTP_SESSION.cookies.set_policy(_NoCookiePolicy())

IGNORE_PATTERN = re.compile(
    r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad|"
    r"emote|reaction|\.svg(\?|$)",
    re.I,
)

WIDGET_CONTEXT_PATTERN = re.compile(
    r"related|similar|recommend|suggest|you-may|you_may|might-like|"
    r"widget|sidebar|comment|carousel|swiper|sponsor|advert|banner-ad|"
    r"next-chap|prev-chap|also-read|readers-also|trending|popular-manga",
    re.I,
)

CONTENT_SELECTORS = [
    ".reading-content img",
    ".page-break img",
    ".text-left img",
    "#readerarea img",
    ".chapter-content img",
]

# عنوان مميز يكفي وحده كمؤشر قوي (Cloudflare يضع عنوانًا مختلفًا بوضوح)
CHALLENGE_TITLE_MARKERS = [
    "just a moment", "attention required", "access denied", "ddos protection by",
]
# عبارات جسم عامة — تحتاج عبارتين معًا لتفادي إيجابيات كاذبة على مواقع لا
# علاقة لها بـCloudflare (شفناها فعليًا مع جدار مانع إعلانات على dilar.tube)
CHALLENGE_BODY_MARKERS = [
    "checking your browser", "cf-browser-verification", "verifying you are human",
    "enable javascript and cookies",
]

# [تصحيح حرج جديد] الاكتشاف: "Attention Required! | Cloudflare" عنوان
# مشترك بين حالتين مختلفتين جذريًا — WAF/IP block (حظر نهائي، الانتظار لا
# يحلّه أبدًا) و Managed/JS Challenge (قابل للحل فعليًا بمتصفح). الاعتماد
# على CHALLENGE_TITLE_MARKERS وحدها (كما كان) لا يميّز بينهما — وهذا بالضبط
# ما حدث مع mangatek.com: انتظار 20 ثانية + إعادة تحميل على صفحة حظر نهائي
# لا يمكن حلّها بأي انتظار. عبارات الجسم أدناه أدق من العنوان المشترك.
FINAL_BLOCK_BODY_MARKERS = [
    "sorry, you have been blocked", "you have been blocked",
    "your ip address has been blocked", "access denied",
]
SOLVABLE_CHALLENGE_BODY_MARKERS = [
    "just a moment", "checking your browser", "cf-browser-verification",
    "verifying you are human", "enable javascript and cookies", "ddos protection by",
]

# [إضافة — بند 5] نطاقات ASN مراكز بيانات سحابية شائعة — لو الـrunner يعمل
# منها وصادف حظرًا نهائيًا، الأرجح أن قاعدة WAF بالموقع تحظر النطاق كاملًا
# (نمط موثَّق فعليًا، راجع تعليق _runner_network_info_sync)، لا مشكلة كود.
DATACENTER_ASN_MARKERS = [
    "microsoft", "azure", "amazon", "aws", "google", "gcp", "digitalocean",
    "oracle cloud", "linode", "akamai connected cloud", "ovh", "hetzner",
    "github", "cloudflare",
]

# نص رابط/زر "تجاوز جدار مانع الإعلانات"
ADBLOCK_WALL_TEXT_PATTERN = re.compile(
    r"continue anyway|proceed anyway|متابعة على أي حال|المتابعة على أي حال|تجاوز والمتابعة",
    re.I,
)

# ============================== توقيعات مزوّدي الحماية المعروفة ==============================
# كل توقيع: (اسم المزوّد المعروض بالتقرير، عبارات نصية تُطابَق على HTML/عنوان/جسم)
KNOWN_PROTECTION_SIGNATURES = [
    ("Cloudflare", ["just a moment", "checking your browser", "cf-browser-verification",
                     "attention required! | cloudflare", "ddos protection by cloudflare"]),
    ("Cloudflare Turnstile", ["cf-turnstile", "challenges.cloudflare.com/turnstile"]),
    ("PerimeterX / HUMAN Security", ["pardon our interruption", "px-captcha", "perimeterx", "_px3", "_pxhd"]),
    ("DataDome", ["datadome", "geo.captcha-delivery.com", "dd_cookie_test"]),
    ("Imperva / Incapsula", ["incapsula incident id", "_incapsula_resource", "incident id"]),
    ("Akamai Bot Manager", ["akamai bot manager", "_abck", "ak_bmsc"]),
    ("hCaptcha", ["hcaptcha.com", "h-captcha"]),
    ("Google reCAPTCHA", ["recaptcha.net", "g-recaptcha"]),
    ("Sucuri Firewall", ["sucuri website firewall", "access denied - sucuri"]),
    ("جدار مانع إعلانات (Adblock Wall)", ["continue anyway", "متابعة على أي حال",
                                            "disable your ad blocker", "adblock detected",
                                            "please disable adblock"]),
]

# نطاقات/مسارات شبكية معروفة لمزوّدي حماية — تُفحص على كل طلب شبكة فعلي أثناء
# تحميل الصفحة بالمتصفح (دليل مباشر أدق من مطابقة النص وحدها)
PROTECTION_VENDOR_NETWORK_PATTERNS = {
    # [تصحيح] كان هذا النمط يطابق أيضًا مسارات JSD (JavaScript Detections)
    # مثل /cdn-cgi/challenge-platform/h/b/jsd/oneshot/... — توثيق Cloudflare
    # الرسمي يؤكد أن JSD سكربت تليمتري غير مرئي يعمل على كل صفحة HTML بمواقع
    # Cloudflare بصرف النظر عن وجود تحدٍّ فعلي، فلا يدل على حماية/حظر حقيقي.
    # فُصل هنا إلى نمط منفصل عن التحدي التفاعلي الحقيقي كي لا يُنسَب لحماية
    # فعلية بالخطأ (راجع "Cloudflare Challenge (تفاعلي)" أدناه لهذا الغرض).
    "Cloudflare JSD (تليمتري عادي، غير دال على حظر)": ["/cdn-cgi/challenge-platform/h/b/jsd/"],
    "Cloudflare Challenge (تفاعلي)": ["challenges.cloudflare.com", "/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page"],
    "PerimeterX / HUMAN": ["px-cloud.net", "perimeterx.net", "client.px-cloud.net"],
    "DataDome": ["datadome.co", "geo.captcha-delivery.com"],
    "Imperva / Incapsula": ["incapsula.com", "imperva.com"],
    "Akamai Bot Manager": ["akamaized.net"],
    "hCaptcha": ["hcaptcha.com"],
    "Google reCAPTCHA": ["google.com/recaptcha", "recaptcha.net"],
}

COLLECT_IMAGES_JS = """(els, selectors) => els.map(e => {
    const u = e.getAttribute('data-src') || e.getAttribute('data-lazy-src')
        || e.getAttribute('data-original') || e.currentSrc || e.src;
    let anc = e, depth = 0, ctx = '';
    while (anc && depth < 5) {
        ctx += ' ' + (anc.className && anc.className.toString ? anc.className.toString() : '')
             + ' ' + (anc.id || '');
        anc = anc.parentElement;
        depth++;
    }
    const matched = [];
    for (const sel of selectors) {
        try { if (e.matches(sel)) matched.push(sel); } catch (err) {}
    }
    return {url: u, ctx: ctx.toLowerCase(), matched};
}).filter(x => x.url)"""


def _suggest_selectors_from_unmatched(items: list[dict]) -> list[str]:
    """[شبه مجاني] COLLECT_IMAGES_JS يجمع ctx (كلاسات/id لخمس مستويات آباء)
    لكل صورة أصلًا، لكن يُستخدم فقط لفلترة الودجات — الصور unmatched يُحفَظ
    عددها فقط بلا تفاصيل. هنا نجمّع أكثر أسماء كلاسات/id تكرارًا ضمن ctx
    الصور التي لم تطابق أي محدد من CONTENT_SELECTORS، ونستبعد التوكنات
    العامة (ودجات/إعلانات معروفة مسبقًا بـWIDGET_CONTEXT_PATTERN، وتوكنات
    شائعة جدًا وغير دالة مثل img/lazy) — اقتراح محدد CSS جاهز للصق داخل
    CONTENT_SELECTORS، بصفر آلية جديدة (إعادة استخدام ctx المُجمَّع أصلًا)."""
    GENERIC_TOKENS = {
        "img", "image", "lazy", "loaded", "loading", "src", "wp", "content",
        "post", "entry", "container", "wrap", "wrapper", "item", "list",
        "attachment", "size", "full", "aligncenter", "alignnone",
    }
    token_counts: Counter = Counter()
    for it in items:
        if it.get("matched"):
            continue
        ctx = it.get("ctx", "")
        if WIDGET_CONTEXT_PATTERN.search(ctx):
            continue
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", ctx):
            if token in GENERIC_TOKENS or token.isdigit():
                continue
            token_counts[token] += 1
    suggested = [f".{tok}" for tok, cnt in token_counts.most_common(8) if cnt >= 2]
    return suggested


def classify_protection_signatures(text: str) -> list[str]:
    """يطابق نصًا (HTML خام، أو عنوان+جسم صفحة متصفح) مقابل توقيعات مزوّدي
    الحماية المعروفة، ويرجّع أسماء كل من طابق (قد يكون أكثر من واحد)."""
    low = text.lower()
    return [name for name, sigs in KNOWN_PROTECTION_SIGNATURES if any(s in low for s in sigs)]


# ============================== بروفايلات المواقع ==============================
SITE_PROFILE = os.environ.get("SITE_PROFILE", "auto").strip().lower()

PROFILES = {
    "azorafly": {"label": "أزورافلاي", "fetch_mode": "http"},
    # [تصحيح حرج] كان do_scroll=False يفوّت غالبية صفحات كل فصل بصمت —
    # الصفحة lazy-load بالتمرير فعليًا (images_at_t0=2 مقابل حتى 15 بعد
    # التمرير، تأكّد بأربعة روابط تشخيص منفصلة). do_widget_filter=True
    # مفعّل الآن أيضًا بناءً على نفس بيانات التشخيص (استبعاد فعلي لصور
    # ودجات > 0)، دون اعتماد suggested_selectors التوليدية (راجع البند 6).
    "mangatuk": {"label": "مانجا توك", "fetch_mode": "browser", "do_scroll": True, "do_widget_filter": True},
    # [تخصيص مبني على بيانات تشخيص فعلية — run-32838569470.zip، فصلان،
    # تكرار مزدوج لكل فصل = 4 تمريرات مستقلة] selector_match_counts كانت
    # صفر/5 لكل CONTENT_SELECTORS العامة بكل الأربع تمريرات (نتيجة ثابتة لا
    # عشوائية) — الموقع Tailwind-based بلا كلاسات دلالية. suggested_selectors
    # (توليد تلقائي من ctx الصور غير المطابقة) رجّعت أساسًا توكنات Tailwind
    # عامة جدًا (.w-full/.relative/.flex/.h-auto/.block ستطابق عناصر تنقّل/
    # أزرار بكل الصفحة)، باستثناء توكنين أقل عمومية بوضوح: bg-surface-1
    # (توكن تصميم مخصص، غير افتراضي بـTailwind) وduration-300 (انتقال محدد
    # غير شائع الاستخدام على كل عنصر). أُضيفا كـextra_selectors — يُجرَّبان
    # بعد الخمسة العامة (extract_image_urls يتطلب ≥3 تطابقات قبل الثقة بأي
    # محدد، ثم يسقط تلقائيًا لمسار all_urls الحالي عند الفشل) فلا مخاطرة
    # تراجع: إما تحسين دقة حقيقي أو نفس السلوك الحالي تمامًا بلا تغيير.
    # content_wait_ms خُفِّض من الافتراضي العام 20000 إلى 8000 — القياس
    # الفعلي لـwait_for_images_elapsed_sec كان 2.41–4.83ث وبكل الأربع
    # تمريرات (لا تذبذب يُذكر)، فسقف 20ث الافتراضي زيادة غير مبرَّرة لهذا
    # الموقع تحديدًا؛ 8000 يبقي هامش أمان ~2× فوق أبطأ قياس فعلي بلا التأثير
    # على المسار الطبيعي (الذي أصلًا يخرج مبكرًا عند استقرار العدد، لا ينتظر
    # السقف الكامل) — يفيد فقط بتقليل أسوأ سيناريو انتظار عند عطل مؤقت بالموقع.
    "mangatime": {
        "label": "مانجا تايم", "fetch_mode": "browser", "do_scroll": True,
        "do_widget_filter": True,
        "extra_selectors": [".bg-surface-1 img", ".duration-300 img"],
        "content_wait_ms": 8000,
    },
    "olympustaff": {"label": "أولمبوس ستاف", "fetch_mode": "browser", "do_scroll": False, "do_widget_filter": True},
    "procomic": {
        "label": "برو كوميك",
        "fetch_mode": "http",
        # [إضافة موقع جديد] procomic لا يملك وسوم <img> فعلية بالـHTML
        # الخام (يعتمد على استخراج regex عام على نص/JSON مُضمَّن مسبقًا).
        # صور المحتوى الحقيقية تمر حصرًا عبر app.procomic.net/chapters/
        # {manga}/{chapter}/pN/... — هذا النمط allowlist صارم يستبعد تلقائيًا
        # صورة OG/SEO المصغّرة الوحيدة، ونسخة المعاينة المكررة لصفحة1 على
        # cdn3.procomic.net (بلا مجلد pN بمسارها). راجع _apply_http_content_filter.
        "http_content_pattern": r"app\.procomic\.net/chapters/.+?/p\d+/",
    },
    "auto": {"label": "تلقائي (عام)", "fetch_mode": "browser", "do_scroll": True, "do_widget_filter": True},
}


def get_profile() -> dict:
    profile = PROFILES.get(SITE_PROFILE)
    if profile is None:
        print(f"⚠️ بروفايل غير معروف '{SITE_PROFILE}' — الرجوع للبروفايل العام (auto)")
        profile = PROFILES["auto"]
    return profile


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF]+", "-", text).strip("-").lower()
    return text or "chapter"


def manga_slug_from_url(url: str) -> tuple[str, str]:
    u = urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    chapter_num = None
    chapter_part_index = None
    for i in range(len(parts) - 1, -1, -1):
        m = re.search(r"(\d+)$", parts[i])
        if m:
            chapter_num = m.group(1)
            chapter_part_index = i
            break
    STRUCTURE_WORDS = {"chapter", "chapters", "manga", "series", "read", "manhwa", "ch"}
    manga_parts = []
    for i, p in enumerate(parts):
        if i == chapter_part_index:
            continue
        if re.fullmatch(r"\d+", p):
            continue
        if p.lower() in STRUCTURE_WORDS:
            continue
        manga_parts.append(p)
    manga_name = manga_parts[-1] if manga_parts else u.hostname
    return f"{u.hostname}__{slugify(manga_name)}", (chapter_num or "0")


def dedupe(urls: list[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen and not IGNORE_PATTERN.search(u):
            seen.add(u)
            out.append(u)
    return out


# ---------------------------- مسار HTTP المباشر (azorafly / procomic) ----------------------------

def extract_images_from_html(html: str, base_url: str) -> list[str]:
    noscript_blocks = re.findall(r"<noscript>(.*?)</noscript>", html, re.I | re.S)
    found = []
    for block in noscript_blocks:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', block):
            found.append(urljoin(base_url, m.group(1)))
    found = dedupe(found)
    # [تصحيح حرج ٢] لا نثق بـnoscript إلا إذا حوى عددًا كافيًا من الصور،
    # وإلا فهو على الأرجح بكسل تتبع/تحليلات معزول لا علاقة له بمحتوى الفصل.
    if len(found) >= MIN_NOSCRIPT_IMAGES:
        return found

    data_src_found = []
    for tag_match in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = tag_match.group(0)
        u = None
        for attr in ("data-src", "data-lazy-src", "data-original"):
            m = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
            if m:
                u = m.group(1)
                break
        if not u:
            m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
            if m:
                u = m.group(1)
        if u and not u.startswith("data:"):
            data_src_found.append(urljoin(base_url, u))
    data_src_found = dedupe(data_src_found)
    if data_src_found:
        return data_src_found

    # آخر ملاذ: صور noscript حتى لو كانت أقل من الحد الأدنى، خير من لا شيء
    if found:
        return found

    plain_found = [urljoin(base_url, m.group(0)) for m in
                    re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(plain_found)


def _classify_protection_category(text: str) -> str:
    """[تصحيح حرج جديد] يميّز 'final_block' (حظر WAF/IP نهائي — الانتظار
    لا يفيد) عن 'solvable_challenge' (تحدٍّ متصفح قابل للحل) عن 'none'.
    الترتيب مقصود: عبارات الحظر النهائي أولًا (أدق دليل)، ثم عبارات التحدي
    القابل للحل، ثم رجوع للسلوك القديم (عبارتان معًا)، وأخيرًا لو تطابق
    عنوان مبهم قديم (مثل "attention required") بلا أي دليل جسم يحسم
    الاتجاه، يُصنَّف حظرًا نهائيًا كافتراضي أسلم (هذا ما رُصد فعليًا على
    mangatek.com: نفس العنوان المشترك، لكن الحالة الفعلية حظر لا تحدٍّ)."""
    if any(m in text for m in FINAL_BLOCK_BODY_MARKERS):
        return "final_block"
    if any(m in text for m in SOLVABLE_CHALLENGE_BODY_MARKERS):
        return "solvable_challenge"
    if sum(1 for m in CHALLENGE_BODY_MARKERS if m in text) >= 2:
        return "solvable_challenge"
    if any(m in text for m in CHALLENGE_TITLE_MARKERS):
        return "final_block"
    return "none"


def _classify_challenge_html(html: str) -> str:
    return _classify_protection_category(html.lower())


def _looks_like_challenge_html(html: str) -> bool:
    """[توافق خلفي] غلاف بولياني — أي كود قديم يحتاج بولياني فقط."""
    return _classify_challenge_html(html) != "none"


def _page_number_from_url(url: str) -> float:
    """يستخرج رقم صفحة الفصل من الرابط لو وُجد نمط '/pN/' الشائع (مثل
    procomic: /chapters/{manga}/{chapter}/p3/...). يُستخدَم فقط لإعادة ترتيب
    قائمة صور مستخرَجة عبر مسار fallback نصي عام لا يضمن ترتيب الصفحات
    الفعلي (يعتمد ترتيب ظهورها بالنص الخام/JSON المُضمَّن فقط). الروابط
    التي لا تطابق النمط تُدفَع لنهاية القائمة (inf) بدل كسر الفرز.
    """
    m = re.search(r"/p(\d+)/", url)
    return float(m.group(1)) if m else float("inf")


def _apply_http_content_filter(urls: list[str], profile: dict) -> list[str]:
    """[إضافة procomic] بعض المواقع تُخرِج عبر مسار HTTP المباشر صور محتوى
    حقيقية مختلطة بصور زائدة لا علاقة لها بصفحات الفصل (صورة OG/SEO مصغّرة،
    نسخة معاينة مكررة على نطاق CDN آخر...). 'http_content_pattern' الاختياري
    بالبروفايل يسمح بتحديد نمط تضمين (allowlist) صارم بدل استبعاد كل حالة
    زائدة بمنطق عام قد يخطئ على مواقع أخرى. إن لم يُطابق أي رابط النمط
    (تغيّر بنية الموقع مثلًا) نرجع للقائمة الأصلية كاملة بدل إرجاع فصل فارغ
    بصمت — فشل واضح بالخطوة التالية أفضل من فقدان صامت.
    """
    pattern = profile.get("http_content_pattern")
    if not pattern:
        return urls
    filtered = [u for u in urls if re.search(pattern, u)]
    if not filtered:
        print("  ⚠️ لم يُطابق أي رابط نمط المحتوى المتوقع لهذا البروفايل — استخدام القائمة الكاملة دون تصفية")
        return urls
    excluded = len(urls) - len(filtered)
    if excluded:
        print(f"  🧹 [procomic] استُبعدت {excluded} صورة زائدة (SEO/معاينة مكررة) بواسطة allowlist المحتوى")
    filtered.sort(key=_page_number_from_url)
    return filtered


def fetch_via_http_simple_sync(chapter_url: str, profile: dict | None = None) -> tuple[list[str], str]:
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    try:
        resp = _HTTP_SESSION.get(chapter_url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        return [], f"فشل الطلب المباشر: {e}"
    html = resp.text
    if _looks_like_challenge_html(html):
        return [], "صفحة تحقق/حماية ظهرت حتى بطلب مباشر — هذا البروفايل غير مناسب لهذا الرابط تحديدًا"
    urls = extract_images_from_html(html, chapter_url)
    if not urls:
        return [], "لم يُعثر على صور في HTML الثابت"
    if profile:
        urls = _apply_http_content_filter(urls, profile)
    return urls, ""


def _validate_image_bytes(raw_bytes: bytes) -> tuple[bool, str]:
    """[إصلاح منطقي ج] معيار ">= 500 بايت + content-type يبدأ بـimage/" وحده
    ضعيف جدًا: أنظمة حماية كثيرة ترجع 200 مع صورة صغيرة "محظور"/placeholder
    بدل رفض صريح، وتعبر هذي الصورة البديلة سقف 500 بايت بسهولة. هنا نفتح
    البايتات فعليًا بـPIL (نفس آلية compress_image) ونتحقق من أبعاد معقولة
    لصفحة مانهوا حقيقية قبل اعتبارها نجاح — تُستخدم بمسار HTTP والمتصفح معًا،
    وبالتشخيص والإنتاج معًا (نفس الدالتين تُستخدَمان بـprocess_chapter)."""
    try:
        probe = Image.open(BytesIO(raw_bytes))
        probe.verify()
    except Exception as e:
        return False, f"ليست صورة صالحة (فشل فك PIL): {e}"
    try:
        img = Image.open(BytesIO(raw_bytes))
        w, h = img.size
    except Exception as e:
        return False, f"تعذّرت قراءة أبعاد الصورة بعد التحقق: {e}"
    if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
        return False, f"أبعاد صغيرة جدًا لصفحة مانهوا حقيقية ({w}x{h}) — يُرجَّح صورة بديلة/حظر لا محتوى فعلي"
    return True, ""


def fetch_image_bytes_http_sync(img_url: str, referer: str) -> tuple[bytes | None, str | None]:
    last_reason = "سبب غير معروف"
    for attempt in range(1, IMG_FETCH_RETRIES + 1):
        try:
            resp = _HTTP_SESSION.get(img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=20)
            ctype = resp.headers.get("content-type", "")
            if resp.ok and (ctype.startswith("image/") or ctype == ""):
                if resp.content and len(resp.content) >= 500:
                    valid, why = _validate_image_bytes(resp.content)
                    if valid:
                        return resp.content, None
                    last_reason = why
                else:
                    last_reason = f"جسم الاستجابة فارغ/صغير جدًا ({len(resp.content)} بايت)"
            else:
                last_reason = f"status={resp.status_code} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < IMG_FETCH_RETRIES:
            time.sleep(0.6 * attempt)
    return None, last_reason


async def fetch_image_bytes_http(img_url: str, referer: str):
    return await asyncio.to_thread(fetch_image_bytes_http_sync, img_url, referer)


# ---------------------------- مسار المتصفح (mangatuk / mangatime / olympustaff / auto) ----------------------------

async def classify_challenge_page(page) -> str:
    """[تصحيح حرج جديد] يرجع 'final_block' / 'solvable_challenge' / 'none'
    بدل بولياني وحيد — يُستخدَم بمسار الإنتاج والتشخيص لتفادي انتظار
    5+CONTENT_WAIT_MS ثانية كاملة على صفحة حظر نهائي لا يحلّها الانتظار
    أبدًا (راجع _classify_protection_category وتعليقه أعلى الملف)."""
    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body_text = ""
        if await page.query_selector("body"):
            body_text = (await page.inner_text("body"))[:800].lower()
    except Exception:
        body_text = ""
    category = _classify_protection_category(f"{title} {body_text}")
    if category != "none":
        return category
    # [تحسين احترافي] كان مسار الإنتاج يستخدم مجموعة ماركرز عامة فقط
    # (Cloudflare أساسًا)، بينما classify_protection_signatures (يغطي
    # PerimeterX/DataDome/Imperva/Akamai/hCaptcha/reCAPTCHA/Sucuri/جدار
    # إعلانات) كان مفعّلًا بوضع التشخيص حصرًا. إعادة استخدامه هنا (بلا أي
    # آلية جديدة) يوسّع الكشف الإنتاجي بصفر تكلفة إضافية حقيقية. مزوّدون
    # عامون غير مصنَّفين نهاية/تحدٍّ صراحةً → يُعامَلون كتحدٍّ قابل للمحاولة
    # (السلوك السابق قبل هذا التصحيح، أسلم من إسقاطهم كحظر نهائي بلا دليل).
    vendors = classify_protection_signatures(f"{title} {body_text}")
    if vendors:
        print(f"  🛡️ مزوّد حماية مكتشَف: {', '.join(vendors)}")
        return "solvable_challenge"
    return "none"


async def looks_like_challenge_page(page) -> bool:
    """[توافق خلفي] غلاف بولياني فوق classify_challenge_page."""
    return await classify_challenge_page(page) != "none"


# نمط إطار Turnstile — يغطي كلا الشكلين المعروفين: الودجت المُضمَّن بنموذج
# عادي (src يحوي /turnstile/) وصفحة التحدي الكاملة (src يحوي challenges.
# cloudflare.com مباشرة، كحال starzmanga.com الذي رُصد فعليًا بالتشخيص).
TURNSTILE_IFRAME_SELECTOR = 'iframe[src*="challenges.cloudflare.com"], iframe[src*="/turnstile/"]'


# [إضافة — احتياطي تشخيصي فقط] عند غياب iframe مطابق تمامًا (حالة
# starzmanga.com الفعلية: الودجت "Verifying..." + شعار Cloudflare يظهر
# داخل body مباشرة، لا داخل iframe منفصل بصفحة "Just a moment..." هذه
# تحديدًا)، نبحث عن حاوٍ مرئي يحتمل أنه صندوق الودجت نفسه بدل الاستسلام.
# محددات عامة مقصودة (لا نص إنجليزي/عربي محدد لتفادي هشاشة الترجمة):
WIDGET_CONTAINER_FALLBACK_SELECTORS = (
    '[class*="turnstile"]', '[id*="turnstile"]',
    '[class*="challenge"]', '[id*="challenge"]',
    '[class*="cf-"]',
)


async def _find_widget_container_fallback(page):
    """[إضافة — احتياطي فقط، غير مستخدَم بالمسار الإنتاجي افتراضيًا]
    يبحث عن أول عنصر مرئي (bounding_box فعلي) يطابق أحد المحددات العامة
    أعلاه، خارج أي iframe (داخل body الصفحة الرئيسية مباشرة). لا يفترض
    أنه الودجت الصحيح بالضرورة — مجرد أفضل تخمين متاح حين يغيب iframe
    الفعلي، ويُسجَّل صراحة كـ"fallback" بنتيجة النقر ليُميَّز عن نقرة
    iframe حقيقية عند المراجعة."""
    for sel in WIDGET_CONTAINER_FALLBACK_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if not el:
                continue
            box = await el.bounding_box()
            if box and box["width"] >= 5 and box["height"] >= 5:
                return el, box
        except Exception:
            continue
    return None, None


async def attempt_click_turnstile_checkbox(
    page, iframe_timeout_ms: int = 8000, try_widget_fallback: bool = False
) -> dict:
    """[إضافة — حل Turnstile بالنقر المجاني، بلا أي خدمة خارجية مدفوعة]
    محاولة أفضل جهد فقط — النجاح غير مضمون إطلاقًا، خصوصًا من IP مركز
    بيانات (GitHub Actions runner راجع runner_network_info بالتقارير: مثلًا
    AS8075 Microsoft/Azure) — راجع نقاش المحادثة: الاختبارات الفعلية
    المنشورة عام 2026 تُظهر Playwright عادي + stealth على IP مركز بيانات
    ينجح بنسبة منخفضة جدًا مقابل Turnstile التفاعلي تحديدًا (بعكس التحدي
    الصامت البسيط الذي كان يُحل بالانتظار وحده، راجع olympustaff سابقًا).

    Cloudflare لا يوثّق بنية DOM الداخلية لإطار Turnstile رسميًا (وقد
    تتغيّر بلا إشعار)، فالنقر هنا بإحداثيات فأرة محسوبة من bounding_box
    الإطار نفسه (لا محددات CSS داخلية هشة، ولا إحداثيات ثابتة مفترضة
    لحجم نافذة معيّن) — مربع النقر التفاعلي بمعظم تنسيقات Turnstile
    الحالية قرب الحافة اليسرى للإطار، لا منتصف عرضه (باقي الإطار نص
    "Verify you are human" فقط بلا تفاعل).

    iframe_timeout_ms: مهلة البحث عن iframe (افتراضيًا 8000 كسلوك الإنتاج
    الأصلي بلا تغيير — يُخفَّض بوضع التشخيص الممتد لأن الانتظار الصافي
    الطويل يسبقه أصلًا فلا حاجة لمهلة طويلة إضافية هنا).
    try_widget_fallback: افتراضيًا False (سلوك الإنتاج الحالي بلا أي
    تغيير) — يُفعَّل فقط بوضع التشخيص الممتد. لو True ولم يُعثر على
    iframe، يُجرَّب _find_widget_container_fallback كبديل.

    يُعيد قاموسًا تشخيصيًا خامًا فقط (iframe_found/clicked/error/
    click_method) — لا حكمًا نهائيًا على نجاح الحل؛ المستدعي يُعيد
    classify_challenge_page بعد الانتظار وإعادة التحميل ليقرر فعليًا هل
    انحل التحدي."""
    result = {"iframe_found": False, "clicked": False, "error": None, "click_method": "none"}
    box = None
    try:
        iframe_el = await page.wait_for_selector(
            TURNSTILE_IFRAME_SELECTOR, timeout=iframe_timeout_ms, state="attached"
        )
        result["iframe_found"] = True
        box = await iframe_el.bounding_box()
        if not box or box["width"] < 5 or box["height"] < 5:
            result["error"] = "إطار Turnstile موجود لكن بلا أبعاد مرئية (bounding_box فارغ/مخفي)"
            box = None
        else:
            result["click_method"] = "iframe"
    except Exception as e:
        result["error"] = f"لم يُعثر على إطار Turnstile خلال {iframe_timeout_ms}ms: {e}"

    if box is None and try_widget_fallback:
        _, fallback_box = await _find_widget_container_fallback(page)
        if fallback_box:
            box = fallback_box
            result["click_method"] = "widget_container_fallback"
            result["error"] = None
        elif not result["iframe_found"]:
            result["error"] = (result["error"] or "") + " — لا حاوٍ احتياطي مرئي أيضًا"

    if box is None:
        return result

    try:
        click_x = box["x"] + 30
        click_y = box["y"] + box["height"] / 2
        # [نمط سلوكي] نقرة فورية عند ظهور الإطار مباشرة إشارة آلية شائعة
        # بأنظمة الحماية السلوكية — تأخير عشوائي + حركة فأرة تقريبية قبل
        # النقرة الفعلية بدل قفزة مباشرة لإحداثي واحد.
        await page.wait_for_timeout(random.randint(700, 1900))
        try:
            await page.mouse.move(max(click_x - 15, 0), max(click_y - 8, 0), steps=6)
            await page.wait_for_timeout(random.randint(80, 220))
        except Exception:
            pass
        await page.mouse.click(click_x, click_y)
        result["clicked"] = True
    except Exception as e:
        result["error"] = f"فشل النقر: {e}"
    return result


# [إضافة — تشخيص ممتد فقط، لا يُستخدَم بالمسار الإنتاجي open_and_collect]
# ينفّذ بالضبط التسلسل المتفق عليه: انتظار صافٍ (بلا نقر/reload) حتى
# EXTENDED_WAIT_MAX_SEC، فقط لو لم ينحل التحدي خلاله تبدأ 3 محاولات نقر
# بفاصل 5 ثوانٍ بين كل محاولة، ثم reload أخير + فحص نهائي.
EXTENDED_WAIT_MAX_SEC = 60
EXTENDED_WAIT_POLL_SEC = 2
EXTENDED_CLICK_ATTEMPTS = 3
EXTENDED_CLICK_GAP_SEC = 5


async def probe_challenge_with_extended_wait(page) -> dict:
    """[إضافة — تشخيص ممتد] يُستدعى فقط من browser_probe التشخيصي حين
    protection_category == 'solvable_challenge'. لا يلمس open_and_collect
    الإنتاجي إطلاقًا.

    المرحلة أ — انتظار صافٍ: استطلاع classify_challenge_page كل
    EXTENDED_WAIT_POLL_SEC حتى EXTENDED_WAIT_MAX_SEC، بلا أي نقر أو
    reload — يختبر رقميًا هل يكفي الصبر وحده (فرضية المستخدم) بمعزل تام
    عن فرضية حظر سمعة IP عند الحافة.

    المرحلة ب — 3 نقرات فقط لو لم ينحل التحدي خلال كامل مهلة الانتظار
    الصافي: كل محاولة تجرب iframe الحقيقي أولًا (مهلة قصيرة 3 ثوانٍ، لأن
    الانتظار الصافي الطويل غطّى الاحتمال الأكبر لظهوره) ثم fallback صندوق
    الودجت المرئي (raise عند غيابه أيضًا). فاصل 5 ثوانٍ بين كل محاولة
    ونظيرتها (لا قبل الأولى)."""
    probe = {
        "pure_wait": {
            "max_wait_sec": EXTENDED_WAIT_MAX_SEC, "poll_interval_sec": EXTENDED_WAIT_POLL_SEC,
            "resolved_during_pure_wait": False, "elapsed_until_resolved_sec": None,
            "final_category_after_wait": None,
        },
        "click_attempts": [],
        "final_after_reload": {
            "attempted": False, "category": None, "resolved": None, "error": None,
        },
    }

    # --- المرحلة أ: انتظار صافٍ فقط ---
    _wait_start = time.monotonic()
    elapsed = 0.0
    category = await classify_challenge_page(page)
    while elapsed < EXTENDED_WAIT_MAX_SEC:
        if category != "solvable_challenge":
            probe["pure_wait"]["resolved_during_pure_wait"] = True
            probe["pure_wait"]["elapsed_until_resolved_sec"] = round(elapsed, 1)
            break
        await page.wait_for_timeout(int(EXTENDED_WAIT_POLL_SEC * 1000))
        elapsed = time.monotonic() - _wait_start
        category = await classify_challenge_page(page)
    probe["pure_wait"]["final_category_after_wait"] = category

    if category != "solvable_challenge":
        # انحل بالانتظار الصافي وحده — فرضية المستخدم صحيحة هنا، لا داعي
        # لأي نقر إطلاقًا.
        return probe

    # --- المرحلة ب: 3 نقرات، فاصل 5 ثوانٍ بين كل واحدة، بعد الانتظار فقط ---
    for i in range(EXTENDED_CLICK_ATTEMPTS):
        if i > 0:
            await page.wait_for_timeout(int(EXTENDED_CLICK_GAP_SEC * 1000))
        click_result = await attempt_click_turnstile_checkbox(
            page, iframe_timeout_ms=3000, try_widget_fallback=True
        )
        click_result["attempt_number"] = i + 1
        probe["click_attempts"].append(click_result)
        # لو انحل التحدي فورًا بعد نقرة، لا داعي لمتابعة النقرات الباقية
        current = await classify_challenge_page(page)
        if current != "solvable_challenge":
            break

    # --- reload أخير + فحص نهائي (يطابق منطق الإنتاج الحالي بعد النقر) ---
    probe["final_after_reload"]["attempted"] = True
    try:
        await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
        final_category = await classify_challenge_page(page)
        probe["final_after_reload"]["category"] = final_category
        probe["final_after_reload"]["resolved"] = final_category == "none"
    except Exception as e:
        probe["final_after_reload"]["error"] = f"فشلت إعادة التحميل الأخيرة: {e}"
        probe["final_after_reload"]["resolved"] = False

    return probe


async def count_real_images(page) -> int:
    try:
        return await page.eval_on_selector_all(
            "img",
            """els => els.filter(e => {
                const u = e.getAttribute('data-src') || e.getAttribute('data-lazy-src')
                    || e.getAttribute('data-original') || e.currentSrc || e.src || '';
                return u.length > 10 && !u.startsWith('data:');
            }).length"""
        )
    except Exception:
        return 0


async def wait_for_real_images(page, max_wait_ms: int, poll_ms: int) -> int:
    elapsed = 0
    last_count = -1
    stable_rounds = 0
    while elapsed < max_wait_ms:
        count = await count_real_images(page)
        if count > 0 and count == last_count:
            stable_rounds += 1
            if stable_rounds >= 2:
                return count
        else:
            stable_rounds = 0
        last_count = count
        await page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return max(last_count, 0)


async def dismiss_adblock_wall_timed(page, max_wait_ms: int = 45000) -> dict:
    """نسخة تشخيصية من كاشف/متجاوِز جدار مانع الإعلانات: تقيس فعليًا (لا
    تخمين) كم ثانية استغرق الزر ليصبح مرئيًا وغير معطّل، بدل انتظار مدة
    ثابتة. تُستخدَم بوضع التشخيص فقط لقياس القيمة الحقيقية لكل موقع."""
    result = {"detected": False, "became_ready_after_sec": None, "clicked": False,
              "button_snippet": None, "timed_out": False}
    try:
        locator = page.get_by_text(ADBLOCK_WALL_TEXT_PATTERN)
        if await locator.count() == 0:
            return result
        result["detected"] = True
        target = locator.first
        try:
            result["button_snippet"] = (await target.evaluate("el => el.outerHTML"))[:300]
        except Exception:
            pass

        start = time.monotonic()
        elapsed_ms, poll_ms, ready = 0, 1000, False
        while elapsed_ms < max_wait_ms:
            try:
                if await target.is_visible() and await target.is_enabled():
                    ready = True
                    break
            except Exception:
                pass
            await page.wait_for_timeout(poll_ms)
            elapsed_ms += poll_ms
        result["became_ready_after_sec"] = round(time.monotonic() - start, 1)
        result["timed_out"] = not ready

        try:
            await target.click(timeout=3000)
            result["clicked"] = True
        except Exception:
            try:
                await target.evaluate("el => el.click()")
                result["clicked"] = True
            except Exception:
                result["clicked"] = False
        await page.wait_for_timeout(1200)
    except Exception as e:
        result["error"] = str(e)
    return result


async def collect_images_while_scrolling(page, content_selectors: list[str], scroll_meta: dict | None = None) -> list[dict]:
    # [إضافة — البند 4] scroll_meta اختياري: لو مُرِّر dict، يُملأ في مكانه
    # بعدد جولات التمرير الفعلية وسبب التوقف — كي يميّز التشخيص "توقف مبكر
    # لاستقرار محتوى" عن "وصول السقف الزمني" عن "تذبذب حماية حقيقي محتمل"
    # (راجع consistency_diffs بين تشغيلتين، البند 3 بتوصية التشخيص). بلا
    # تغيير أي سلوك أو توقيع بالمسار الإنتاجي (extract_image_urls لا يمرره).
    if scroll_meta is not None:
        scroll_meta.update({
            "rounds_completed": 0, "stop_reason": "max_steps_reached",
            "content_stable_rounds_required": 4,
        })
    seen: dict[str, dict] = {}

    def merge(items):
        for it in items:
            u = it.get("url")
            if not u:
                continue
            if u not in seen:
                seen[u] = {"ctx": it.get("ctx", ""), "matched": set(it.get("matched", []))}
            else:
                seen[u]["matched"].update(it.get("matched", []))

    def content_matched_count() -> int:
        return sum(1 for v in seen.values() if v["matched"])

    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await page.wait_for_timeout(300)

    start = time.monotonic()
    stable_rounds = 0
    content_stable_rounds = 0
    last_content_count = -1
    CONTENT_STABLE_ROUNDS_REQUIRED = 4
    round_num = 0
    for _ in range(SCROLL_MAX_STEPS):
        round_num += 1
        if scroll_meta is not None:
            scroll_meta["rounds_completed"] = round_num
        if time.monotonic() - start > SCROLL_MAX_TOTAL_SEC:
            print(f"  ⏱️ توقف التمرير عند السقف الزمني ({SCROLL_MAX_TOTAL_SEC}ث) — استخدام ما جُمع حتى الآن")
            if scroll_meta is not None:
                scroll_meta["stop_reason"] = "time_limit"
            break
        try:
            items = await page.eval_on_selector_all("img", COLLECT_IMAGES_JS, content_selectors)
        except Exception:
            items = []
        before = len(seen)
        merge(items)
        grew = len(seen) > before

        cur_content = content_matched_count()
        if cur_content > 0 and cur_content == last_content_count:
            content_stable_rounds += 1
        else:
            content_stable_rounds = 0
        last_content_count = cur_content

        try:
            reached_bottom = await page.evaluate(
                "(window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 50)"
            )
        except Exception:
            reached_bottom = True

        if reached_bottom and not grew:
            stable_rounds += 1
            if stable_rounds >= 2:
                if scroll_meta is not None:
                    scroll_meta["stop_reason"] = "stable_no_growth_at_bottom"
                break
        else:
            stable_rounds = 0

        if content_stable_rounds >= CONTENT_STABLE_ROUNDS_REQUIRED:
            print(f"  ⏱️ استقرت صور محتوى القراءة الفعلية ({cur_content}) — إيقاف التمرير مبكرًا")
            if scroll_meta is not None:
                scroll_meta["stop_reason"] = "content_stable_early_stop"
            break

        if not reached_bottom:
            try:
                # [تحسين احترافي] كسر ثابت التمرير (0.85 دومًا) بنسبة عشوائية
                # ضمن مدى معقول — الأنماط الثابتة تمامًا مؤشر كشف سلوكي
                # شائع لدى أنظمة الحماية المتقدمة (DataDome/PerimeterX)،
                # بصرف النظر عن نجاح تمويه navigator.webdriver.
                fraction = random.uniform(0.6, 0.95)
                await page.evaluate(f"window.scrollBy(0, Math.round(window.innerHeight * {fraction}))")
            except Exception:
                pass
        # نفس المنطق: تأخير مُهتزّ بدل SCROLL_STEP_WAIT_MS الثابت حرفيًا.
        jitter_ms = int(SCROLL_STEP_WAIT_MS * random.uniform(0.75, 1.4))
        await page.wait_for_timeout(jitter_ms)

    for pos_expr in ["document.body.scrollHeight", "0"]:
        try:
            await page.evaluate(f"window.scrollTo(0, {pos_expr})")
        except Exception:
            pass
        await page.wait_for_timeout(400)
        try:
            items = await page.eval_on_selector_all("img", COLLECT_IMAGES_JS, content_selectors)
            merge(items)
        except Exception:
            pass

    return [{"url": u, "ctx": v["ctx"], "matched": v["matched"]} for u, v in seen.items()]


async def snapshot_images(page, content_selectors: list[str]) -> list[dict]:
    try:
        items = await page.eval_on_selector_all("img", COLLECT_IMAGES_JS, content_selectors)
    except Exception:
        items = []
    return [{"url": it["url"], "ctx": it.get("ctx", ""), "matched": set(it.get("matched", []))}
            for it in items if it.get("url")]


def _filter_widget_context(items: list[dict]) -> list[dict]:
    kept, excluded_widget = [], 0
    for item in items:
        if WIDGET_CONTEXT_PATTERN.search(item.get("ctx", "")):
            excluded_widget += 1
            continue
        kept.append(item)
    if excluded_widget:
        print(f"  🧹 استُبعدت {excluded_widget} صورة بسبب سياق ودجت (مقترح/مشابه/إعلان...)")
    return kept


def _apply_domain_filter(urls: list[str]) -> list[str]:
    if not STRICT_DOMAIN_FILTER or len(urls) < 4:
        return urls
    domains = [urlparse(u).hostname for u in urls]
    majority_domain, _ = Counter(domains).most_common(1)[0]
    before = len(urls)
    urls = [u for u in urls if urlparse(u).hostname == majority_domain]
    if len(urls) != before:
        print(f"  🌐 استُبعدت {before - len(urls)} صورة من نطاق مختلف عن {majority_domain}")
    return urls


async def extract_image_urls(page, base_url: str, do_scroll: bool, do_widget_filter: bool, selectors: list[str] | None = None) -> list[str]:
    # [إضافة — المرحلة ج] selectors اختياري (extra_selectors من بروفايل
    # الموقع، مدموجة مسبقًا بواسطة المستدعي) — الافتراض CONTENT_SELECTORS
    # العامة كما كان دومًا، بلا تغيير سلوك لأي بروفايل موجود لا يحدد الحقل.
    selectors = selectors or CONTENT_SELECTORS
    try:
        items = await (collect_images_while_scrolling(page, selectors) if do_scroll
                       else snapshot_images(page, selectors))
    except Exception:
        items = []

    filtered = _filter_widget_context(items) if do_widget_filter else items

    if filtered:
        for selector in selectors:
            matched_urls = dedupe([
                urljoin(base_url, item["url"])
                for item in filtered
                if selector in item["matched"]
            ])
            if len(matched_urls) >= 3:
                return _apply_domain_filter(matched_urls)

        all_urls = dedupe([urljoin(base_url, item["url"]) for item in filtered])
        if all_urls:
            return _apply_domain_filter(all_urls)

    # [تصحيح حرج ٢] نفس منطق الحد الأدنى: لا نثق بـnoscript بمتصفح إلا إذا
    # حوى عددًا كافيًا من الصور، وإلا نتابع لآخر ملاذ (مسح HTML الخام للصفحة).
    noscript_imgs = await page.eval_on_selector_all("noscript", "els => els.map(e => e.innerHTML)")
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    found = dedupe(found)
    if len(found) >= MIN_NOSCRIPT_IMAGES:
        return found

    html = await page.content()
    plain_found = [urljoin(base_url, m.group(0)) for m in
                    re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    plain_found = dedupe(plain_found)
    if plain_found:
        return plain_found

    # آخر ملاذ: صور noscript حتى لو أقل من الحد الأدنى، خير من لا شيء
    return found


async def fetch_image_bytes(context, img_url: str, referer: str):
    last_reason = "سبب غير معروف"
    for attempt in range(1, IMG_FETCH_RETRIES + 1):
        try:
            resp = await context.request.get(
                img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=20000,
            )
            ctype = resp.headers.get("content-type", "")
            if resp.ok and (ctype.startswith("image/") or ctype == ""):
                body = await resp.body()
                if body and len(body) >= 500:
                    valid, why = await asyncio.to_thread(_validate_image_bytes, body)
                    if valid:
                        return body, None
                    last_reason = why
                else:
                    last_reason = f"جسم الاستجابة فارغ/صغير جدًا ({len(body) if body else 0} بايت)"
            else:
                last_reason = f"status={resp.status} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < IMG_FETCH_RETRIES:
            await asyncio.sleep(0.6 * attempt)
    return None, last_reason


async def open_and_collect(browser, chapter_url: str, attempt: int, profile: dict):
    context = await browser.new_context(
        user_agent=UA, viewport={"width": 1280, "height": 1000}, locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    # [تحسين احترافي] استبدال الترقيع اليدوي الوحيد (navigator.webdriver
    # فقط) بحمولة stealth كاملة (WebGL/plugins/chrome.runtime/UA-CH...) —
    # راجع تعريف _STEALTH أعلى الملف لسبب الاختيار.
    # [إضافة — المرحلة ج] do_stealth اختياري بالبروفايل (افتراضه True كسلوك
    # الإنتاج الحالي بلا تغيير) — يُعطَّل فقط لو التشخيص أثبت رقميًا لهذا
    # الموقع تحديدًا أن stealth لا يغيّر شيئًا (راجع stealth_comparison).
    if profile.get("do_stealth", True):
        await _STEALTH.apply_stealth_async(context)
    page = await context.new_page()

    navigated = False
    wait_strategy = "domcontentloaded" if attempt == 1 else "load"
    try:
        await page.goto(chapter_url, wait_until=wait_strategy, timeout=NAV_TIMEOUT_MS)
        navigated = True
    except Exception as e:
        print(f"  ⚠️ تعذّر تحميل الصفحة ({wait_strategy}): {e}")

    # [تصحيح حرج جديد — Fail-fast] يتتبّع صراحة هل استقرت الحالة على حظر
    # نهائي (سواء من أول فحص، أو بعد إعادة تحميل تحدٍّ قابل للحل) — يُستخدَم
    # أدناه لتخطي CONTENT_WAIT_MS كاملة أيضًا، لا فقط انتظار الـ5 ثوانٍ.
    final_block_confirmed = False
    if navigated:
        category = await classify_challenge_page(page)
        if category == "final_block":
            # حظر WAF/IP نهائي: لا فائدة إطلاقًا من انتظار 5 ثوانٍ + إعادة
            # تحميل + CONTENT_WAIT_MS كاملة (كانت تُهدَر بالكامل على
            # mangatek.com رغم استحالة الحل بالانتظار).
            print("  🚫 حظر نهائي (WAF/IP block) مكتشَف — تخطي الانتظار وإعادة التحميل، لا يمكن حله بالانتظار")
            final_block_confirmed = True
        elif category == "solvable_challenge":
            print("  🛡️ تحدٍّ متصفح قابل للحل (Cloudflare أو ما شابه) — محاولة نقر مربع Turnstile (حل مجاني، غير مضمون)...")
            click_result = await attempt_click_turnstile_checkbox(page)
            if click_result["clicked"]:
                print("  🖱️ نُقر مربع Turnstile — انتظار معالجة الخادم للنقرة قبل إعادة التحميل...")
            elif click_result["iframe_found"]:
                print(f"  ⚠️ إطار Turnstile موجود لكن تعذّر تحديد مربع نقر صالح: {click_result['error']}")
            else:
                print(f"  ℹ️ لا إطار Turnstile تفاعلي ظاهر (غالبًا فحص صامت يُحل بالانتظار وحده): {click_result['error']}")
            await page.wait_for_timeout(5000)
            try:
                await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
                # [إصلاح منطقي أ] لا نفترض أن الreload حلّ التحدي — نعيد الفحص
                # فعليًا بعده مباشرة (أغلب تحديات Cloudflare JS تنحل تلقائيًا
                # خلال الانتظار، لكن ليس كلها).
                still = await classify_challenge_page(page)
                if still == "none":
                    print("  ✅ التحدي انحل بعد إعادة التحميل")
                elif still == "final_block":
                    print("  🚫 اتضح بعد إعادة التحميل أنها صفحة حظر نهائي — لا فائدة من محاولات إضافية")
                    final_block_confirmed = True
                else:
                    print("  ⚠️ التحدي ما زال ظاهرًا بعد إعادة التحميل")
            except Exception as e:
                print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")

    # [إضافة — المرحلة ج] content_wait_ms اختياري بالبروفايل (افتراضه
    # CONTENT_WAIT_MS العام كما كان دومًا) — يسمح بمهلة انتظار مبنية على
    # منحنى استقرار فعلي مقاس لهذا الموقع تحديدًا بدل 20 ثانية ثابتة للجميع.
    # [تصحيح حرج جديد — Fail-fast] لو تأكّد حظر نهائي أعلاه، لا معنى
    # لاستطلاع CONTENT_WAIT_MS كاملة أيضًا — لن تظهر أي صورة محتوى حقيقية
    # على صفحة حظر نهائي مهما طال الانتظار.
    if final_block_confirmed:
        found_count = 0
        print("  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): 0 (تخطي الانتظار — حظر نهائي مؤكَّد)")
    else:
        content_wait_ms = profile.get("content_wait_ms", CONTENT_WAIT_MS)
        found_count = await wait_for_real_images(page, content_wait_ms, CONTENT_POLL_MS)
        print(f"  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): {found_count}")

    t0 = time.monotonic()
    do_scroll = profile.get("do_scroll", True)
    do_widget_filter = profile.get("do_widget_filter", True)
    # [إضافة — المرحلة ج] extra_selectors اختياري بالبروفايل — تُدمَج مع
    # CONTENT_SELECTORS العامة (بلا تكرار) بدل استبدالها، فلا تُفقَد صور
    # تُطابق محددات المحتوى المعروفة أصلًا.
    extra_selectors = [s for s in profile.get("extra_selectors", []) if s not in CONTENT_SELECTORS]
    selectors = CONTENT_SELECTORS + extra_selectors if extra_selectors else CONTENT_SELECTORS
    image_urls = await extract_image_urls(page, chapter_url, do_scroll, do_widget_filter, selectors)
    print(f"  ⏱️ زمن الاستخراج: {time.monotonic() - t0:.1f}ث")
    await page.close()

    if not image_urls:
        await context.close()
        reason = "لم يتم تحميل الصفحة أصلًا (انتهت المهلة)" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        return None, [], reason
    if not navigated:
        print("  ℹ️ ملاحظة: حدث goto لم يُطلَق (انتهت مهلته) لكن المحتوى الحقيقي كان قد اكتمل فعليًا — نُكمل به")
    print(f"  📊 إجمالي الصور: {len(image_urls)}")
    return context, image_urls, ""


# ---------------------------- منطق مشترك (يعمل مهما كان المسار) ----------------------------

def compress_image(raw_bytes: bytes, max_width: int, quality: int, img_format: str = "webp") -> bytes:
    img = Image.open(BytesIO(raw_bytes))

    if img.mode == "P":
        img = img.convert("RGBA") if "transparency" in img.info else img.convert("RGB")
    elif img.mode == "CMYK":
        img = img.convert("RGB")
    elif img.mode == "LA":
        img = img.convert("RGBA")

    scale = 1.0
    if img.width > max_width:
        scale = min(scale, max_width / img.width)
    if img.width * scale > WEBP_HARD_LIMIT:
        scale = min(scale, WEBP_HARD_LIMIT / img.width)
    if img.height * scale > WEBP_HARD_LIMIT:
        scale = min(scale, WEBP_HARD_LIMIT / img.height)

    if scale < 1.0:
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    out = BytesIO()
    if img_format == "avif":
        # [تحسين احترافي] AVIF أصغر حجمًا بشكل ملموس من WEBP لصفحات ملونة/
        # متدرجة (الأنسب لغالب صفحات المانهوا) لكن ترميزه أبطأ بعشرات
        # المرات — مقبول هنا لأن الضغط يحدث مرة واحدة عند التشغيل، لا وقت
        # عرض فعلي. img.mode بعد التحويلات أعلاه دومًا RGB/RGBA، متوافق مع
        # مشفّر libavif.
        img.save(out, format="AVIF", quality=quality)
    else:
        img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def build_run_manifest(results: list) -> dict:
    return merge_manifest_dict({}, results)


# [تصحيح حرج ٣] _run_git الآن لا يرمي استثناءً أبدًا: أي فشل (git غير
# مثبت، مسار غير موجود، صلاحيات...) يُحوَّل لـCompletedProcess وهمي بكود
# رجوع غير صفري ورسالة خطأ واضحة بدل إيقاف السكربت بالكامل.
def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    except Exception as e:
        return subprocess.CompletedProcess(
            args=["git"] + args, returncode=1, stdout="", stderr=f"تعذّر تشغيل git: {e}"
        )


# [تصحيح حرج ١] مسار output النسبي داخل مستودع git يجب أن يعكس OUTPUT_DIR
# الفعلي، لا اسمًا ثابتًا. نحسبه مرة واحدة ونتحقق أنه فرع فعلي من
# GIT_COMMIT_DIR، وإلا نُبلِّغ بوضوح بدل فشل صامت لاحقًا.
def _compute_git_relative_output_dir(commit_dir: str) -> str | None:
    try:
        commit_root = Path(commit_dir).resolve()
        output_abs = OUTPUT_DIR.resolve()
        rel = output_abs.relative_to(commit_root)
        return str(rel).replace(os.sep, "/")
    except Exception:
        print(
            f"⚠️ OUTPUT_DIR ({OUTPUT_DIR}) ليس فرعًا من GIT_COMMIT_DIR ({commit_dir}) — "
            "لن تعمل عمليات git (add/read remote manifest) بشكل صحيح على هذا المسار"
        )
        return None


def _read_remote_manifest_sync(commit_dir: str, branch: str) -> dict | None:
    git_rel_output = _compute_git_relative_output_dir(commit_dir)
    if git_rel_output is None:
        return None
    fetch = _run_git(["fetch", "origin", branch], commit_dir)
    if fetch.returncode != 0:
        print(f"  ⚠️ فشل git fetch: {fetch.stderr.strip()[:200]}")
        return None
    show = _run_git(["show", f"origin/{branch}:{git_rel_output}/manifest.json"], commit_dir)
    if show.returncode != 0:
        return None
    try:
        return json.loads(show.stdout)
    except Exception:
        return None


def merge_manifest_dict(base: dict, results: list) -> dict:
    manifest = {"manga": {k: {**v, "chapters": list(v.get("chapters", []))}
                           for k, v in (base or {}).get("manga", {}).items()}}
    for r in results:
        mid = r["manga_id"]
        entry = manifest["manga"].setdefault(mid, {"name": mid.split("__", 1)[-1].replace("-", " "), "chapters": []})
        chNum = float(r["chapter_num"]) if re.match(r"^\d+(\.\d+)?$", r["chapter_num"]) else 0
        images_cdn = [f"{CDN_BASE}/{p}" for p in r["image_paths"]] if CDN_BASE else r["image_paths"]
        new_chapter = {
            "label": f"الفصل {r['chapter_num']}", "num": r["chapter_num"], "chNum": chNum,
            "sourceUrl": r["source_url"], "images": images_cdn,
        }
        replaced = False
        for idx, ch in enumerate(entry["chapters"]):
            existing_num = ch.get("num")
            if existing_num is not None:
                if existing_num == r["chapter_num"]:
                    entry["chapters"][idx] = new_chapter
                    replaced = True
                    break
            else:
                if ch.get("chNum") == chNum:
                    entry["chapters"][idx] = new_chapter
                    replaced = True
                    break
        if not replaced:
            entry["chapters"].append(new_chapter)

    for mid in manifest["manga"]:
        manifest["manga"][mid]["chapters"].sort(key=lambda c: (c["chNum"], str(c.get("num", ""))))
    return manifest


def _commit_and_push_sync(
    commit_dir: str, branch: str, message: str, allowed_paths: list[str], max_attempts: int = 5
) -> tuple[bool, str]:
    """
    [تصحيح حرج ٥] allowed_paths إلزامية الآن: قائمة مسارات نسبية لـ
    OUTPUT_DIR (مثل "manifest.json"، "runs/run-123.json"،
    "manga-id/ch-5") تحدد صراحةً ما هذه التشغيلة مخوّلة إضافته/دفعه.
    تُستخدم نفس القائمة حرفيًا في كل استدعاء git add بهذه الدالة — أول
    إضافة وأي إضافة لاحقة بعد reset — ولا يوجد أي "git add <مجلد>" شامل
    في أي موضع. هذا يمنع جذريًا حذف ملفات تشغيلات أخرى محتملة الوجود
    بالفهرس بعد reset (راجع تصحيح ٤ و٥ بترويسة الملف لتفاصيل السيناريو).
    """
    # [تصحيح حرج ١] نستخدم مسار OUTPUT_DIR الفعلي المحسوب نسبيًا لمستودع
    # git، بدل الاسم الحرفي الثابت "output" الذي كان يتجاهل تخصيص
    # OUTPUT_DIR بالكامل ويسبب فقدان نتائج صامتًا.
    git_rel_output = _compute_git_relative_output_dir(commit_dir)
    if git_rel_output is None:
        return False, f"OUTPUT_DIR ({OUTPUT_DIR}) ليس داخل GIT_COMMIT_DIR ({commit_dir}) — تعذّر تحديد مسار الدفع"

    if not allowed_paths:
        return True, "لا توجد مسارات مصرّح بها لهذه التشغيلة (لا شيء لإضافته)"

    # إزالة أي تكرار مع الحفاظ على الترتيب — تكرار مسار بنفس git add غير
    # ضار فعليًا، لكن الأنظف تفاديه.
    add_paths = list(dict.fromkeys(f"{git_rel_output}/{p}" for p in allowed_paths))

    add = _run_git(["add", "--"] + add_paths, commit_dir)
    if add.returncode != 0:
        return False, f"git add فشل: {add.stderr.strip()[:200]}"
    diff = _run_git(["diff", "--cached", "--quiet"], commit_dir)
    if diff.returncode == 0:
        return True, "لا تغييرات جديدة (تخطي الدفع)"
    commit = _run_git(["commit", "-m", message], commit_dir)
    if commit.returncode != 0:
        return False, f"git commit فشل: {commit.stderr.strip()[:200]}"

    for attempt in range(1, max_attempts + 1):
        push = _run_git(["push", "origin", f"HEAD:{branch}"], commit_dir)
        if push.returncode == 0:
            return True, "تم الدفع"
        # "git reset origin/<branch>" (مختلط) ينقل الفهرس ليطابق أحدث
        # نسخة بعيدة، بلا لمس قرص هذه التشغيلة إطلاقًا. لو الفهرس الجديد
        # يحوي ملفات تشغيلات أخرى غير موجودة على هذا القرص، فإن تقييد
        # الإضافة على add_paths حصرًا (بدل أي "git add <مجلد>") يضمن عدم
        # اعتبارها "محذوفة" ودفع حذفها بالخطأ.
        _run_git(["fetch", "origin", branch], commit_dir)
        _run_git(["reset", f"origin/{branch}"], commit_dir)
        _run_git(["add", "--"] + add_paths, commit_dir)
        diff2 = _run_git(["diff", "--cached", "--quiet"], commit_dir)
        if diff2.returncode == 0:
            return True, "أصبحت التغييرات مطابقة لأحدث نسخة على البعيد أصلًا"
        _run_git(["commit", "-m", message], commit_dir)
        time.sleep(attempt * 2)
    return False, "فشل الدفع بعد عدة محاولات (سيُعالجه الدفع الاحتياطي النهائي بالـ workflow إن وُجد)"


async def push_now(message: str, allowed_paths: list[str]) -> None:
    if not ENABLE_INCREMENTAL_PUSH or not GIT_COMMIT_DIR:
        return
    ok, msg = await asyncio.to_thread(_commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, message, allowed_paths)
    print(f"  {'✅' if ok else '⚠️'} دفع: {msg}")


def _owned_chapter_paths(results: list) -> list[str]:
    """
    [تصحيح حرج ٥] يبني قائمة المسارات (نسبية لـOUTPUT_DIR) التي هذه
    التشغيلة كتبتها فعليًا حتى هذه اللحظة: manifest.json + ملف manifest
    الخاص بهذه التشغيلة + مجلد كل فصل مضغوط ضمن results. يُستخدم كـ
    allowed_paths في كل استدعاء دفع بالمسار العادي (غير التشخيصي)، بدل
    الاعتماد على فحص فرق git التفاعلي بعد كل commit.
    """
    paths = ["manifest.json", RUN_MANIFEST_RELPATH]
    for r in results:
        paths.append(f"{r['manga_id']}/ch-{r['chapter_num']}")
    return list(dict.fromkeys(paths))


async def get_chapter_images(browser, chapter_url: str, profile: dict):
    fetch_mode = profile.get("fetch_mode", "browser")
    if fetch_mode == "http":
        fail_reason = ""
        for attempt in range(1, RETRY_PER_CHAPTER + 1):
            if attempt > 1:
                delay = 1.5 * attempt
                print(f"  🔁 إعادة محاولة طلب مباشر #{attempt} (بعد {delay:.1f}ث)")
                await asyncio.sleep(delay)
            image_urls, fail_reason = await asyncio.to_thread(fetch_via_http_simple_sync, chapter_url, profile)
            if image_urls:
                return None, image_urls, ""
        return None, [], fail_reason

    context, image_urls, fail_reason = None, [], ""
    for attempt in range(1, RETRY_PER_CHAPTER + 1):
        if attempt > 1:
            print(f"  🔁 إعادة محاولة #{attempt}")
        context, image_urls, fail_reason = await open_and_collect(browser, chapter_url, attempt, profile)
        if image_urls:
            break
    return context, image_urls, fail_reason


async def process_chapter(browser, chapter_url: str, index: int, total: int, profile: dict):
    print(f"[{index}/{total}] فتح: {chapter_url} — بروفايل: {profile['label']}")

    context, image_urls, fail_reason = await get_chapter_images(browser, chapter_url, profile)

    if not image_urls:
        print(f"  ❌ {fail_reason or 'لم يُعثر على صور في هذا الفصل'}")
        return None

    manga_id, chapter_num = manga_slug_from_url(chapter_url)
    chapter_dir = OUTPUT_DIR / manga_id / f"ch-{chapter_num}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    fetch_mode = profile.get("fetch_mode", "browser")

    async def download(img_url: str):
        if fetch_mode == "http":
            return await fetch_image_bytes_http(img_url, chapter_url)
        return await fetch_image_bytes(context, img_url, chapter_url)

    saved_paths = []
    failed_indices = []
    for i, img_url in enumerate(image_urls, start=1):
        raw, reason = await download(img_url)
        if not raw:
            print(f"  ⚠️ فشلت صورة {i}: {reason} — الرابط: {img_url}")
            failed_indices.append(i)
            continue
        try:
            compressed = compress_image(raw, MAX_WIDTH, QUALITY, IMG_FORMAT)
            filename = f"{i:03d}.{IMG_FORMAT}"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            print(f"  ✅ {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
        except Exception as e:
            print(f"  ⚠️ فشلت صورة {i} أثناء الضغط: {e} — الرابط: {img_url}")
        await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

    if failed_indices:
        print(f"  🔁 إعادة محاولة نهائية لـ {len(failed_indices)} صورة فشلت...")
        still_failed = []
        for i in failed_indices:
            img_url = image_urls[i - 1]
            raw, reason = await download(img_url)
            if raw:
                try:
                    compressed = compress_image(raw, MAX_WIDTH, QUALITY, IMG_FORMAT)
                    filename = f"{i:03d}.{IMG_FORMAT}"
                    (chapter_dir / filename).write_bytes(compressed)
                    saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
                    print(f"  ✅ (إعادة محاولة) {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
                except Exception as e:
                    print(f"  ⚠️ فشلت صورة {i} أثناء الضغط بعد إعادة المحاولة: {e} — الرابط: {img_url}")
                    still_failed.append(i)
            else:
                print(f"  ⚠️ فشلت صورة {i} نهائيًا: {reason} — الرابط: {img_url}")
                still_failed.append(i)
            await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)
        if still_failed:
            print(f"  ❌ تعذّر تحميل {len(still_failed)} صورة نهائيًا: {still_failed}")

    if context:
        await context.close()

    if not saved_paths:
        return None

    return {"manga_id": manga_id, "chapter_num": chapter_num, "source_url": chapter_url, "image_paths": saved_paths}


async def main():
    raw_urls = [u for u in re.split(r'[\s,،؛;]+', CHAPTER_URLS_RAW.strip()) if u.startswith('http')]

    seen, chapter_urls, dup_count = set(), [], 0
    for u in raw_urls:
        if u in seen:
            dup_count += 1
            continue
        seen.add(u)
        chapter_urls.append(u)

    print(f"📋 تم استخراج {len(chapter_urls)} رابط صالح من المدخلات" + (f" (استُبعد {dup_count} مكرر)" if dup_count else "") + ":")
    for u in chapter_urls:
        print(f"   - {u}")
    if not chapter_urls:
        print("لا توجد روابط فصول في المدخلات (CHAPTER_URLS فارغة)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if DIAGNOSTIC_MODE:
        # [استيراد مؤجَّل عمدًا] diagnostics.py يستورد من هذا الملف (compress_
        # chapters) عدة دوال/ثوابت مشتركة عند تحميله — لو كان هذا الاستيراد
        # على مستوى الملف (أعلى compress_chapters.py) لحدث استيراد دائري
        # (كل ملف يحاول تحميل الآخر أثناء تحميله هو). بتأجيله لحظة الاستدعاء
        # الفعلي هنا، تكون وحدة compress_chapters قد اكتملت تهيئتها بالكامل
        # في sys.modules أولًا، فيعمل "from compress_chapters import ..." من
        # داخل diagnostics.py بلا أي مشكلة.
        from diagnostics import run_diagnostic_mode
        await run_diagnostic_mode(chapter_urls)
        return

    if OCR_EXPERIMENT_MODE:
        # [استيراد مؤجَّل] نفس سبب diagnostics أعلاه تمامًا — راجع التعليق هناك.
        from ocr_extraction import run_ocr_experiment_mode
        await run_ocr_experiment_mode(chapter_urls)
        return

    profile = get_profile()
    print(f"⚙️ بروفايل الموقع: {profile['label']} ({SITE_PROFILE})")

    fetch_mode = profile.get("fetch_mode", "browser")

    print(f"⚙️ الدفع التدريجي: {'مفعّل' if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR else 'مُعطَّل (دفعة واحدة بالنهاية)'}")
    print(f"⚙️ فلترة النطاق الصارمة: {'مفعّلة' if STRICT_DOMAIN_FILTER else 'مُعطَّلة'}")
    if fetch_mode == "http":
        print(f"⚙️ التوازي (HTTP فقط): {HTTP_CONCURRENCY} فصل بالتوازي")

    existing_keys: set[tuple[str, str]] = set()
    if GIT_COMMIT_DIR and SKIP_EXISTING_CHAPTERS:
        remote_manifest = await asyncio.to_thread(_read_remote_manifest_sync, GIT_COMMIT_DIR, GIT_BRANCH)
        if remote_manifest:
            for mid, entry in remote_manifest.get("manga", {}).items():
                for ch in entry.get("chapters", []):
                    num = ch.get("num")
                    if num is not None and ch.get("images"):
                        existing_keys.add((mid, num))
        if existing_keys:
            print(f"⚙️ تخطي الفصول الموجودة مسبقًا: مفعّل ({len(existing_keys)} فصل محفوظ حاليًا على فرع {GIT_BRANCH})")

    to_process: list[tuple[int, str]] = []
    skipped_urls: list[str] = []
    for i, url in enumerate(chapter_urls, start=1):
        if existing_keys:
            mid, cnum = manga_slug_from_url(url)
            if (mid, cnum) in existing_keys:
                skipped_urls.append(url)
                continue
        to_process.append((i, url))

    if skipped_urls:
        print(f"⏭️ تخطي {len(skipped_urls)} فصل موجود مسبقًا:")
        for u in skipped_urls:
            print(f"   - {u}")

    results: list = []
    failed_urls: list[str] = []
    git_lock = asyncio.Lock()

    async def handle_result(url, result):
        if result is None:
            failed_urls.append(url)
            return
        results.append(result)
        run_manifest_path = OUTPUT_DIR / RUN_MANIFEST_RELPATH
        run_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        run_manifest_path.write_text(
            json.dumps(build_run_manifest(results), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR:
            async with git_lock:
                remote = await asyncio.to_thread(_read_remote_manifest_sync, GIT_COMMIT_DIR, GIT_BRANCH)
                merged = merge_manifest_dict(remote or {}, results)
                (OUTPUT_DIR / "manifest.json").write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                await push_now(
                    f"إضافة {result['manga_id']} - الفصل {result['chapter_num']}",
                    _owned_chapter_paths(results),
                )

    async def run_chapter_safe(browser, url, index, total, profile):
        try:
            return await process_chapter(browser, url, index, total, profile)
        except Exception as e:
            print(f"[{index}/{total}] ❌ خطأ غير متوقع أثناء معالجة الفصل: {e}")
            return None

    total = len(chapter_urls)
    if fetch_mode == "http":
        print("🚀 بروفايل HTTP مباشر — لن يُطلَق متصفح Chromium لهذه التشغيلة")
        sem = asyncio.Semaphore(HTTP_CONCURRENCY)

        async def bounded(index, url):
            async with sem:
                r = await run_chapter_safe(None, url, index, total, profile)
                await handle_result(url, r)

        await asyncio.gather(*[bounded(i, url) for i, url in to_process])
    else:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            for i, url in to_process:
                r = await run_chapter_safe(browser, url, i, total, profile)
                await handle_result(url, r)
            await browser.close()

    # [إصلاح — استعادة كتلة مفقودة] هذا الدفع النهائي شبكة أمان: يغطي حالة
    # تعطيل الدفع التدريجي (دفعة واحدة بالنهاية) أو أي فصل لم يُدفَع لسبب
    # ما أثناء المعالجة. نفس allowed_paths المبني من results (لا "git add
    # <مجلد>" شامل إطلاقًا) — راجع _owned_chapter_paths وتصحيح ٥ بترويسة
    # الملف لسبب هذا التقييد تحديدًا.
    if GIT_COMMIT_DIR:
        ok, msg = await asyncio.to_thread(
            _commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH,
            f"دفع نهائي - {len(results)} فصل", _owned_chapter_paths(results),
        )
        print(f"{'✅' if ok else '⚠️'} الدفع النهائي: {msg}")

    print("\n" + "=" * 50)
    print("📊 ملخص التشغيلة")
    print(f"  ✅ نجح: {len(results)} فصل")
    if skipped_urls:
        print(f"  ⏭️ تم تخطيه (موجود مسبقًا): {len(skipped_urls)} فصل")
    if failed_urls:
        print(f"  ❌ فشل: {len(failed_urls)} فصل")
        for u in failed_urls:
            print(f"     - {u}")
    print(f"manifest.json جاهز في {OUTPUT_DIR}/manifest.json")
    print(f"🔗 manifest خاص بهذه التشغيلة فقط: {OUTPUT_DIR}/{RUN_MANIFEST_RELPATH}")
    print("=" * 50)

    if failed_urls and len(results) == 0 and len(skipped_urls) == 0:
        print("🚫 فشلت كل الفصول — التحقق من صحة الروابط/البروفايل المختار مطلوب")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
