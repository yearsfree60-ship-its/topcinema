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
================================================================================
"""
import asyncio
import json
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import requests.adapters  # استيراد صريح — كان يعمل سابقًا فقط بأثر جانبي غير موثّق
import requests.cookies   # لاستخدام RequestsCookieJar في فحص إعادة استخدام الكوكيز
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
def _read_remote_text_sync(commit_dir: str, branch: str, relpath: str) -> str | None:
    """[معلومة مفقودة — تتبع تاريخي] نسخة عامة من _read_remote_manifest_sync
    تقرأ أي ملف نصي (لا manifest.json تحديدًا) من فرع git البعيد — تُستخدم
    لقراءة تاريخ التشخيص السابق لموقع معيّن."""
    fetch = _run_git(["fetch", "origin", branch], commit_dir)
    if fetch.returncode != 0:
        return None
    show = _run_git(["show", f"origin/{branch}:{relpath}"], commit_dir)
    if show.returncode != 0:
        return None
    return show.stdout


def _load_diagnostic_history_sync(site_slug: str) -> list:
    """[معلومة مفقودة] تتبّع تاريخي: يقرأ تشخيصات سابقة لنفس الموقع (بحسب
    hostname) من فرع الإخراج البعيد (GIT_BRANCH) إن توفّر GIT_COMMIT_DIR،
    وإلا من النسخة المحلية — نفس فرع/مجلد الإخراج المستخدَم أصلًا، بلا أي
    بنية تخزين جديدة."""
    relpath = f"diagnostics/history/{site_slug}.json"
    local_path = OUTPUT_DIR / relpath
    if GIT_COMMIT_DIR:
        git_rel_output = _compute_git_relative_output_dir(GIT_COMMIT_DIR)
        if git_rel_output:
            text = _read_remote_text_sync(GIT_COMMIT_DIR, GIT_BRANCH, f"{git_rel_output}/{relpath}")
            if text:
                try:
                    return json.loads(text)
                except Exception:
                    pass
    if local_path.exists():
        try:
            return json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_diagnostic_history_sync(site_slug: str, history: list) -> None:
    # نحتفظ بآخر 20 فحصًا فقط لكل موقع — كافٍ لرصد التغيّر دون نمو غير محدود.
    path = OUTPUT_DIR / "diagnostics" / "history" / f"{site_slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history[-20:], ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _diff_diagnostic_snapshots(previous: dict, current: dict) -> list[str]:
    """[معلومة مفقودة] يقارن أهم مؤشرات سلوك الحماية بين آخر فحص محفوظ
    والفحص الحالي — بروفايل شغّال اليوم ممكن ينكسر بصمت بعد أسابيع لو
    الموقع غيّر سلوك حمايته دون أي تنبيه."""
    fields = {
        "protection_category_static": "تصنيف الحماية (HTTP خام)",
        "protection_category_browser": "تصنيف الحماية (متصفح)",
        "challenge_detected_static": "صفحة تحقق (HTTP خام)",
        "challenge_detected_browser": "صفحة تحقق (متصفح)",
        "cf_mitigated_static": "ترويسة cf-mitigated (HTTP خام)",
        "cf_mitigated_browser": "ترويسة cf-mitigated (متصفح)",
        "protection_signatures": "توقيعات حماية مطابَقة",
        "referer_only_sufficient": "كفاية Referer وحده",
        "rate_limited_detected": "تحديد معدل مكتشَف",
        "static_block_detected": "حظر ثابت مكتشَف (لا علاقة بتحديد المعدل)",
        "signed_url_params": "معاملات روابط موقّعة",
    }
    changes = []
    for key, label in fields.items():
        old_v, new_v = previous.get(key), current.get(key)
        if old_v != new_v:
            changes.append(f"{label}: {old_v!r} ← {new_v!r}")
    return changes


def _tls_and_server_info_sync(url: str) -> dict:
    """[معلومة مفقودة] شهادة TLS + IP الخادم المستجيب عبر socket/ssl
    القياسيتين، بلا أي مكتبة جديدة — يكشف مزوّد CDN/WAF حتى لو الترويسات
    مخفية عمدًا (بعض المزوّدين يُصدرون شهادات SSL بأسماء مميزة، أو يشغّلون
    على مدى IP معروف)."""
    result = {"server_ip": None, "tls_issuer": None, "tls_subject": None, "tls_not_after": None, "error": None}
    host = urlparse(url).hostname
    if not host:
        result["error"] = "تعذّر استخراج hostname من الرابط"
        return result
    try:
        result["server_ip"] = socket.gethostbyname(host)
    except Exception as e:
        result["error"] = f"فشل تحليل DNS: {e}"
        return result
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        issuer = dict(x[0] for x in cert.get("issuer", []))
        subject = dict(x[0] for x in cert.get("subject", []))
        result["tls_issuer"] = issuer.get("organizationName") or issuer.get("commonName")
        result["tls_subject"] = subject.get("commonName")
        result["tls_not_after"] = cert.get("notAfter")
    except Exception as e:
        result["error"] = f"فشل مصافحة TLS: {e}"
    return result


def _runner_network_info_sync() -> dict:
    """[معلومة مفقودة] IP/ASN الخاص بالـrunner نفسه — مهم بالذات لأن الأنبوب
    يشتغل على GitHub Actions: يفرّق بسرعة بين 'اشتغل من جهاز/شبكة عادية
    محليًا' و'انحظر لأنه IP مركز بيانات (datacenter ASN) معروف لمزوّدي
    الحماية'. طلب واحد خفيف لخدمة عامة مجانية بلا مفتاح API."""
    try:
        resp = requests.get("https://ipinfo.io/json", timeout=8)
        if resp.ok:
            data = resp.json()
            return {
                "ip": data.get("ip"), "org_asn": data.get("org"),
                "city": data.get("city"), "country": data.get("country"), "error": None,
            }
        return {"ip": None, "org_asn": None, "city": None, "country": None, "error": f"status={resp.status_code}"}
    except Exception as e:
        return {"ip": None, "org_asn": None, "city": None, "country": None, "error": f"{e}"}


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
    )


def _get_paddleocr_engine():
    global _PADDLEOCR_ENGINE
    if _PADDLEOCR_ENGINE is None:
        _PADDLEOCR_ENGINE = _build_paddleocr_engine(enable_mkldnn=True)
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


def ocr_extract_english_sync(raw_bytes: bytes) -> list[dict]:
    """يُشغَّل عبر asyncio.to_thread. يُرجع صناديق نص خام بلا فرز/تجميع بعد:
    كل عنصر {bbox: [xmin,ymin,xmax,ymax], text: str, confidence: float}.
    [تصحيح] يُكتَب المحتوى لملف مؤقت ويُمرَّر مساره لـpredict() بدل تمرير
    مصفوفة numpy مباشرة — يطابق مسار الاستخدام الموثَّق رسميًا بـPaddleOCR
    3.x تمامًا (تحميل الصورة داخليًا بنفس ترتيب القنوات المتوقَّع)."""
    engine = _get_paddleocr_engine()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        Image.open(BytesIO(raw_bytes)).convert("RGB").save(tmp_path, format="PNG")
        try:
            result = engine.predict(tmp_path)
        except NotImplementedError as e:
            # [احتياطي — فحص نصي دقيق، لا except عام] فقط خلل PIR/oneDNN
            # تحديدًا يُعاد تهيئة المحرك بسببه؛ أي NotImplementedError آخر
            # يُرفَع كما هو (خطأ فعلي يستحق الظهور، ليس عطلًا معروفًا).
            if _PIR_ONEDNN_ERROR_MARKER not in str(e) or _PADDLEOCR_MKLDNN_FALLBACK_DONE:
                raise
            engine = _reinit_paddleocr_engine_without_mkldnn()
            result = engine.predict(tmp_path)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    items: list[dict] = []
    if not result:
        return items
    res = result[0]
    texts = res.get("rec_texts") or []
    scores = res.get("rec_scores") or []
    boxes = res.get("rec_boxes")
    if boxes is None:
        return items
    for text, score, box in zip(texts, scores, boxes):
        text = (text or "").strip()
        if not text:
            continue
        xmin, ymin, xmax, ymax = [float(v) for v in box]
        items.append({"bbox": [xmin, ymin, xmax, ymax], "text": text, "confidence": float(score)})
    return items


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
    for i, img_url in enumerate(image_urls, start=1):
        raw, reason = await download(img_url)
        if not raw:
            print(f"  ⚠️ فشل تحميل صفحة {i} للـOCR: {reason}")
            continue
        try:
            items = await asyncio.to_thread(ocr_extract_english_sync, raw)
            sentences = group_ocr_lines_into_sentences(items)
            page_texts.append(format_ocr_page_text(i, sentences))
            page_json.append({"page": i, "sentences": sentences})
            sfx_count = sum(1 for s in sentences if s["sfx_suspect"])
            print(f"  ✅ صفحة {i}/{len(image_urls)} — {len(sentences)} بند نص ({sfx_count} مُعلَّم [sfx?])")
        except Exception as e:
            print(f"  ⚠️ فشل OCR للصفحة {i}: {e}")
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


# ============================== وضع التشخيص (موسّع) ==============================

def _static_probe_sync(url: str) -> dict:
    result = {
        "status_code": None, "headers_of_interest": {}, "challenge_detected": False,
        "protection_category": "none",
        "protection_signatures": [], "images_via_noscript": 0, "images_via_data_attr": 0,
        "images_via_plain_src": 0, "extracted_image_count": 0, "extracted_sample_urls": [],
        "sample_image_urls": [], "signed_url_params": [], "raw_cookies_received": [], "error": None,
        # [إضافة — المرحلة أ] زمن الطلب الخام فعليًا، للمقارنة لاحقًا بزمن
        # مسار المتصفح الكامل (raw HTTP سريع دومًا تقريبًا، لكن التوثيق
        # الرقمي هنا أفضل من الافتراض).
        "elapsed_sec": None,
    }
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    _t0 = time.monotonic()
    try:
        resp = _HTTP_SESSION.get(url, headers=headers, timeout=20)
        result["elapsed_sec"] = round(time.monotonic() - _t0, 2)
        result["status_code"] = resp.status_code
        # ترويسات موسّعة: مؤشرات مباشرة لمزوّدي حماية معروفين تحديدًا
        for h in ("server", "cf-ray", "cf-mitigated", "cf-cache-status", "content-type",
                   "set-cookie", "retry-after", "x-sucuri-id", "x-datadome", "x-iinfo"):
            if h in resp.headers:
                result["headers_of_interest"][h] = resp.headers[h][:150]
        result["raw_cookies_received"] = list(resp.cookies.keys())
        html = resp.text
    except Exception as e:
        result["elapsed_sec"] = round(time.monotonic() - _t0, 2)
        result["error"] = f"{e}"
        return result

    result["protection_category"] = _classify_challenge_html(html)
    result["challenge_detected"] = result["protection_category"] != "none"
    result["protection_signatures"] = classify_protection_signatures(html)

    noscript_blocks = re.findall(r"<noscript>(.*?)</noscript>", html, re.I | re.S)
    ns_imgs = []
    for block in noscript_blocks:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', block):
            ns_imgs.append(urljoin(url, m.group(1)))
    ns_imgs = dedupe(ns_imgs)
    result["images_via_noscript"] = len(ns_imgs)

    data_imgs, plain_imgs = [], []
    for tag_match in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = tag_match.group(0)
        got_data = False
        for attr in ("data-src", "data-lazy-src", "data-original"):
            m = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
            if m:
                data_imgs.append(urljoin(url, m.group(1)))
                got_data = True
                break
        if not got_data:
            m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
            if m and not m.group(1).startswith("data:"):
                plain_imgs.append(urljoin(url, m.group(1)))
    data_imgs = dedupe(data_imgs)
    plain_imgs = dedupe(plain_imgs)
    result["images_via_data_attr"] = len(data_imgs)
    result["images_via_plain_src"] = len(plain_imgs)

    # [إصلاح] عدّ منفصل (noscript/data-attr/plain-src) مفيد للتشخيص البصري،
    # لكنه لا يطابق أولوية الاختيار الفعلية في extract_images_from_html()
    # (noscript إن بلغ الحد الأدنى ← وإلا data-attr ← ...). أخذ max() الثلاثة
    # كان يُنتج رقمًا متفائلًا قد لا يتحقق فعليًا في مسار HTTP بالإنتاج. الآن
    # نستدعي دالة الإنتاج الحقيقية نفسها لعدد ونماذج موثوقة 100%.
    extracted = extract_images_from_html(html, url)
    result["extracted_image_count"] = len(extracted)
    result["extracted_sample_urls"] = extracted[:3]
    result["signed_url_params"] = _detect_signed_url_params(extracted)

    # [تصحيح حرج ٢] نفس منطق الحد الأدنى هنا أيضًا في عرض عينة الصور
    # التشخيصية، لتفادي تضليل التوصية الآلية ببكسل تتبع وحيد.
    best_list = (ns_imgs if len(ns_imgs) >= MIN_NOSCRIPT_IMAGES else []) or data_imgs or plain_imgs or ns_imgs
    result["sample_image_urls"] = best_list[:3]
    return result


SIGNED_URL_PARAM_PATTERN = re.compile(
    r"(?:^|[?&])(token|sig|signature|expires|expiry|exp|policy|key-pair-id|"
    r"x-amz-signature|x-amz-expires|x-amz-security-token|auth|hash|st|e)=",
    re.I,
)


def _detect_signed_url_params(urls: list[str]) -> list[str]:
    """[معلومة مفقودة] كشف روابط صور موقّعة/منتهية الصلاحية (token=, expires=,
    sig=, X-Amz-Signature...) — يحدد هل استراتيجية "استخرج روابط الصور الآن،
    حمّلها لاحقًا" آمنة أصلًا لهذا الموقع، أم أن الرابط قد ينتهي قبل استخدامه
    فعليًا (مهم بالذات مع الدفع التدريجي/إعادة المحاولة المتأخرة)."""
    found: set[str] = set()
    for u in urls:
        query = urlparse(u).query
        for m in SIGNED_URL_PARAM_PATTERN.finditer("?" + query):
            found.add(m.group(1).lower())
    return sorted(found)


def _pick_sample_urls(items: list[dict], base_url: str, n: int = 3) -> list[str]:
    """[معلومة مفقودة] sample_url سابقًا كان يأخذ أول عنصر ظاهر بالقائمة
    فقط. سلوك الحماية/CDN قد يختلف فعليًا بين أول/وسط/آخر صورة بالفصل
    (أرقام صفحات مختلفة بالمسار، أحيانًا نطاقات CDN مختلفة لدفعات مختلفة).
    هنا نلتقط حتى n عيّنات موزّعة بالتساوي (أولى/وسط/أخيرة) بدل واحدة."""
    urls = dedupe([urljoin(base_url, it["url"]) for it in items if it.get("url")])
    if len(urls) <= n:
        return urls
    idxs = sorted({0, len(urls) // 2, len(urls) - 1})
    return [urls[i] for i in idxs][:n]


async def _hotlink_probe_one(context, sample_url: str, page_url: str) -> dict:
    """عزل ثلاثي (بند ب) لصورة عيّنة واحدة — مستخرَجة بدالة مشتركة كي تُطبَّق
    على عدة عيّنات (بند "عدة صور عيّنة") بلا تكرار كود."""
    no_ref_ok, no_ref_size, no_ref_reason, no_ref_cache_headers = await asyncio.to_thread(
        _fetch_image_probe_variant_sync, sample_url, None
    )
    ref_ok, ref_size, ref_reason, _ref_cache_headers = await asyncio.to_thread(
        _fetch_image_probe_variant_sync, sample_url, page_url
    )
    raw_browser, reason_browser = await fetch_image_bytes(context, sample_url, page_url)
    return {
        "sample_url": sample_url,
        "no_referer_success": no_ref_ok, "no_referer_size": no_ref_size,
        "no_referer_fail_reason": no_ref_reason,
        # [توافق خلفي] direct_http_* = محاولة Referer فقط.
        "direct_http_success": ref_ok, "direct_http_size": ref_size,
        "direct_http_fail_reason": ref_reason,
        "browser_session_success": raw_browser is not None, "browser_session_size": len(raw_browser) if raw_browser else 0,
        "browser_session_fail_reason": reason_browser,
        "referer_only_sufficient": (not no_ref_ok) and ref_ok,
        # [إضافة — بيانات خام جديدة] ترويسات تخزين مؤقت خام من استجابة CDN
        # الصورة (لا حكم على معناها بالكود — راجع _fetch_image_probe_variant_sync).
        "image_cache_headers": no_ref_cache_headers,
    }


async def _rate_limit_probe_image(img_url: str, referer: str, n: int = 4) -> dict:
    """[إصلاح منطقي هـ] الحمل الحقيقي وقت التشغيل يتركز على CDN الصور (كل
    فصل يُحمَّل صوره تسلسليًا، لكن HTTP_CONCURRENCY فصول تتزامن فعليًا معًا)،
    لا على رابط صفحة الفصل. هذا الفحص يرسل n طلبات *بالتوازي الفعلي* (لا
    تسلسليًا بلا تأخير فقط) لنفس رابط الصورة العيّنة — يحاكي نمط الحمل
    الحقيقي على CDN الصور بدل رابط HTML الذي لا يتكرر تحميله أصلًا."""
    def _one():
        try:
            r = _HTTP_SESSION.get(img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=15)
            return r.status_code, r.headers.get("retry-after")
        except Exception as e:
            return f"error:{e}", None

    t0 = time.monotonic()
    outcomes = await asyncio.gather(*[asyncio.to_thread(_one) for _ in range(n)])
    elapsed = round(time.monotonic() - t0, 2)
    statuses = [o[0] for o in outcomes]
    retry_after = next((o[1] for o in outcomes if o[1]), None)
    # [تصحيح — إيجابية كاذبة] "أي طلب واحد 429/403" كان يُصنَّف تحديد معدل،
    # حتى لو الطلب الأول من أصل n أعطى 403 مباشرة — هذا حظر ثابت مسبق (IP/
    # WAF)، لا علاقة له بمعدل الطلبات، ولا يُصلَحه HTTP_CONCURRENCY=1 إطلاقًا.
    # تحديد معدل حقيقي يُفترض أن يُظهر خليطًا (بعض الطلبات نجحت وبعضها لا)
    # ضمن نفس الدفعة، لا حظرًا كاملًا موحّدًا لكل الطلبات.
    blocked_statuses = [s for s in statuses if isinstance(s, int) and s in (429, 403)]
    any_blocked = bool(blocked_statuses)
    all_blocked = bool(statuses) and len(blocked_statuses) == len(statuses)
    return {
        "target": "image_cdn", "sample_url": img_url, "requests_sent": n,
        "elapsed_sec": elapsed, "status_codes": statuses,
        "rate_limited_detected": any_blocked and not all_blocked,
        "static_block_detected": all_blocked,
        "retry_after_header": retry_after,
    }


def _rate_limit_probe_sync(url: str, n: int = 4) -> dict:
    """يرسل عدة طلبات HTTP سريعة متتالية لنفس الرابط ويرصد 429/403 أو
    ترويسة Retry-After. [احتياطي] يُستخدَم فقط لو تعذّر إيجاد رابط صورة
    عيّنة — الفحص الأساسي أصبح على رابط صورة عبر _rate_limit_probe_image
    (راجع الإصلاح المنطقي هـ: الحمل الحقيقي يتركز على CDN الصور لا الصفحة)."""
    statuses = []
    retry_after = None
    t0 = time.monotonic()
    for _ in range(n):
        try:
            r = _HTTP_SESSION.get(url, headers={"User-Agent": UA}, timeout=15)
            statuses.append(r.status_code)
            if "retry-after" in r.headers:
                retry_after = r.headers["retry-after"]
        except Exception as e:
            statuses.append(f"error:{e}")
    elapsed = round(time.monotonic() - t0, 2)
    # [تصحيح — إيجابية كاذبة] نفس منطق _rate_limit_probe_image أعلاه — راجع
    # تعليقها لسبب الفصل بين "حظر ثابت من كل الطلبات" و"تصاعد جزئي حقيقي".
    blocked_statuses = [s for s in statuses if isinstance(s, int) and s in (429, 403)]
    any_blocked = bool(blocked_statuses)
    all_blocked = bool(statuses) and len(blocked_statuses) == len(statuses)
    return {
        "target": "page_url", "sample_url": url, "requests_sent": n, "elapsed_sec": elapsed,
        "status_codes": statuses,
        "rate_limited_detected": any_blocked and not all_blocked,
        "static_block_detected": all_blocked,
        "retry_after_header": retry_after,
    }


async def _cookie_reuse_probe(context, url: str) -> dict:
    """يختبر إعادة استخدام كوكيز جلسة المتصفح (بعد حل أي تحدٍّ) بطلب HTTP
    عادي بدون متصفح لاحقًا — يجاوب سؤالًا عمليًا مهمًا: هل استراتيجية هجينة
    (حل التحدي مرة واحدة بالمتصفح، ثم HTTP سريع لكل الفصول التالية) ممكنة
    لهذا الموقع، أم يحتاج متصفحًا كاملًا لكل فصل بلا استثناء؟"""
    try:
        cookies = await context.cookies()
    except Exception:
        cookies = []
    if not cookies:
        return {"tested": False, "reason": "لا كوكيز بالجلسة لاختبارها"}

    jar = requests.cookies.RequestsCookieJar()
    for c in cookies:
        try:
            jar.set(c["name"], c["value"], domain=c.get("domain", "") or "", path=c.get("path", "/") or "/")
        except Exception:
            continue

    try:
        resp = await asyncio.to_thread(
            lambda: _HTTP_SESSION.get(url, headers={"User-Agent": UA}, cookies=jar, timeout=20)
        )
        success = resp.ok and not _looks_like_challenge_html(resp.text)
        return {
            "tested": True, "success": success, "status_code": resp.status_code,
            "cookie_count_reused": len(cookies),
            # [إضافة — بيانات خام جديدة] أسماء الكوكيز فقط (لا القيم) —
            # يفيد التحقق اليدوي أي كوكيز فعليًا وراء نجاح/فشل إعادة
            # الاستخدام (مثلًا cf_clearance تحديدًا مقابل كوكيز جلسة عامة).
            "cookie_names_reused": sorted(c["name"] for c in cookies),
        }
    except Exception as e:
        return {"tested": True, "success": False, "error": str(e), "cookie_count_reused": len(cookies),
                "cookie_names_reused": sorted(c["name"] for c in cookies)}


def _fetch_image_probe_variant_sync(img_url: str, referer: str | None) -> tuple[bool, int, str | None, dict]:
    """[إصلاح منطقي ب] محاولة تحميل وحيدة بلا إعادة محاولة (فحص تشخيصي، لا
    إنتاج) — مع Referer أو بدونه، بلا كوكيز دائمًا (_HTTP_SESSION مضبوطة
    على رفض تخزين أي كوكيز واردة). تُستخدم لعزل هل الحماية Referer فقط
    (شائع وسهل التعامل معه بـrequests عادي) أم تحتاج جلسة متصفح كاملة.
    [إضافة — بيانات خام جديدة] يرجّع أيضًا ترويسات التخزين المؤقت الخام
    (Cache-Control/Expires/ETag) من استجابة CDN الصورة نفسها — بيانات
    موضوعية تكمّل signed_url_params لتقييم أمان 'استخرج الآن حمّل لاحقًا'،
    بلا أي حكم مُدمَج بالكود على معناها."""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        resp = _HTTP_SESSION.get(img_url, headers=headers, timeout=20)
        cache_headers = {
            h: resp.headers[h] for h in ("cache-control", "expires", "etag", "age")
            if h in resp.headers
        }
        ctype = resp.headers.get("content-type", "")
        size = len(resp.content) if resp.content else 0
        if resp.ok and (ctype.startswith("image/") or ctype == ""):
            if resp.content and size >= 500:
                valid, why = _validate_image_bytes(resp.content)
                return valid, size, (None if valid else why), cache_headers
            return False, size, f"جسم الاستجابة فارغ/صغير جدًا ({size} بايت)", cache_headers
        return False, size, f"status={resp.status_code} content-type={ctype!r}", cache_headers
    except Exception as e:
        return False, 0, f"استثناء: {e}", {}


FINGERPRINT_SELF_CHECK_JS = """() => ({
    webdriver: navigator.webdriver === undefined ? null : navigator.webdriver,
    hasWindowChrome: !!window.chrome,
    pluginsLength: navigator.plugins ? navigator.plugins.length : null,
    languages: navigator.languages ? Array.from(navigator.languages) : null,
    userAgent: navigator.userAgent,
})"""


NAVIGATION_TIMING_JS = """() => {
    const entries = performance.getEntriesByType('navigation');
    if (!entries.length) return null;
    const e = entries[0];
    return {
        ttfb_ms: Math.round(e.responseStart - e.requestStart),
        dom_content_loaded_ms: Math.round(e.domContentLoadedEventEnd - e.startTime),
        load_event_ms: e.loadEventEnd > 0 ? Math.round(e.loadEventEnd - e.startTime) : null,
        transfer_size_bytes: e.transferSize || null,
    };
}"""


async def _capture_navigation_timing(page) -> dict | None:
    """[إضافة — المرحلة أ] Navigation Timing API الحقيقية من المتصفح — تعزل
    بطء الشبكة (TTFB) عن بطء تحميل DOM/تنفيذ JS بعده، بدقة أعلى من
    time.monotonic() الخارجي وحده حول page.goto."""
    try:
        return await page.evaluate(NAVIGATION_TIMING_JS)
    except Exception:
        return None


async def _capture_fingerprint_signals(page) -> dict:
    """[إضافة — قياس واقعي بدل افتراض] يلتقط ما تراه الصفحة *فعليًا* عن نفسها
    (لا افتراض نظري بأن الترقيع نجح): navigator.webdriver الحقيقي، وجود
    window.chrome، عدد الإضافات المُعلَنة، اللغات، الـUser-Agent. يُستخدَم
    مرتين بكل تشخيص (بلا stealth / بstealth) لإثبات الفرق رقميًا بدل الكلام
    العام عن "stealth يساعد عادةً"."""
    try:
        return await page.evaluate(FINGERPRINT_SELF_CHECK_JS)
    except Exception as e:
        return {"error": str(e)}


async def _no_stealth_reference_probe(browser, url: str) -> dict:
    """[إضافة — تشخيص واقع الإنتاج الفعلي] يفتح متصفحًا منفصلًا تمامًا
    *بلا* أي تمويه إطلاقًا: لا _STEALTH، ولا حتى فلاج الإطلاق
    --disable-blink-features=AutomationControlled الذي يُطلَق به المتصفح
    المشترك (وسيط browser) للممر الرئيسي.
    [تصحيح حرج] كانت هذه الدالة تفتح context جديدًا على نفس browser
    المشترَك — فكلا السياقين (بstealth وبلاه) كانا يرثان الفلاج نفسه،
    وهو وحده كافٍ لإخفاء navigator.webdriver بصرف النظر عن
    playwright-stealth. أي أن "بلا stealth" لم يكن خط أساس حقيقي "بلا أي
    تمويه" — فأي فرق (أو غيابه) بـstealth_comparison لم يكن يقيس أثر
    stealth فعليًا. الإصلاح: متصفح Chromium مستقل بالكامل، بإطلاق بلا أي
    args تمويه، لعزل أثر stealth عن أثر الفلاج تمامًا.
    فحص مركّز (بلا تمرير/hotlink/سكرين‌شوت كامل — تلك غير متأثرة بـstealth
    عادةً) يقيس فقط ما يتأثر فعليًا: هل تظهر صفحة تحقق؟ هل يتغيّر عدد
    الصور المكتشفة؟ ما الذي تراه الصفحة عن بصمتها؟ النتيجة تُقارَن مباشرة
    بنتيجة الممر الرئيسي (الذي يستخدم _STEALTH + الفلاج معًا، مطابقةً
    للإنتاج) — كلا الحقلين خام بتقرير التشخيص، بلا استنتاج مُدمَج بالكود."""
    result = {
        "navigated": False, "challenge_detected": False, "protection_category": "none",
        "images_after_wait": None, "fingerprint": {}, "error": None,
    }
    try:
        async with async_playwright() as p_clean:
            clean_browser = await p_clean.chromium.launch()
            try:
                context = await clean_browser.new_context(
                    user_agent=UA, viewport={"width": 1280, "height": 1000}, locale="en-US",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
                )
                page = await context.new_page()
                try:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                        result["navigated"] = True
                    except Exception as e:
                        result["error"] = f"فشل التحميل الأولي: {e}"

                    result["fingerprint"] = await _capture_fingerprint_signals(page)
                    result["protection_category"] = await classify_challenge_page(page)
                    result["challenge_detected"] = result["protection_category"] != "none"
                    # [تصحيح حرج جديد — Fail-fast] لا فائدة من انتظار/إعادة تحميل على
                    # حظر نهائي — راجع نفس التصحيح بـopen_and_collect لسبب هذا الفرع.
                    if result["protection_category"] == "solvable_challenge":
                        await page.wait_for_timeout(5000)
                        try:
                            await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
                            result["protection_category"] = await classify_challenge_page(page)
                            result["challenge_detected"] = result["protection_category"] != "none"
                        except Exception:
                            pass
                    result["images_after_wait"] = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
                finally:
                    await context.close()
            finally:
                await clean_browser.close()
    except Exception as e:
        result["error"] = result["error"] or f"فشل إطلاق متصفح مرجعي منفصل: {e}"
    return result


async def _browser_probe(browser, url: str, diag_dir: Path, slug: str) -> dict:
    result = {
        "navigated": False, "title": None, "challenge_detected": False,
        "protection_category": "none",
        "challenge_resolved_after_reload": None, "protection_signatures": [],
        "images_at_t0": None, "images_after_wait": None, "images_after_scroll": None,
        "selector_match_counts": {}, "unmatched_img_count": 0, "widget_excluded_count": 0,
        "widget_excluded_samples": [], "suggested_selectors": [], "domain_distribution": {},
        "signed_url_params": [], "screenshot_path": None, "hotlink_probe": None,
        "hotlink_probes": [], "network_vendor_hits": {},
        "adblock_wall": None, "cookie_reuse_probe": None,
        "fingerprint_with_stealth": {}, "stealth_comparison": None, "error": None,
        # [إضافة — المرحلة أ] حقول زمنية حول كل مرحلة فعلية — الآلية سابقًا
        # كانت غنية بقياس *القدرة* لكن عمياء تمامًا عن *الوقت*، فلا يمكن
        # موازنة "نتيجة ممتازة" مقابل "وقت قليل" بلا هذه الأرقام.
        "goto_elapsed_sec": None, "navigation_timing": None,
        "wait_for_images_elapsed_sec": None, "scroll_elapsed_sec": None,
        "total_probe_elapsed_sec": None,
        "scroll_rounds_completed": None, "scroll_stop_reason": None,
        # [إضافة — بيانات خام جديدة] ترويسات استجابة التنقّل الرئيسي عبر
        # المتصفح فعليًا (بعكس static_probe الذي يلتقطها بطلب requests فقط) —
        # يشمل cf-mitigated الموثّق رسميًا من Cloudflare كإشارة تحدٍّ موثوقة
        # (راجع developers.cloudflare.com/cloudflare-challenges)، ويُقارَن
        # لاحقًا يدويًا مع نظيره بـstatic_probe لمعرفة هل الحماية تُفرَّق
        # بين طلب HTTP خام وطلب متصفح ينفّذ JS فعليًا.
        "navigation_response_headers": {},
        # كل نطاق طرف ثالث اتصلت به الصفحة فعليًا أثناء التحميل — لا فقط
        # ما يطابق PROTECTION_VENDOR_NETWORK_PATTERNS المعروفة مسبقًا؛ يكشف
        # مزوّد حماية/تحليلات غير مُدرَج بالقائمة الثابتة بدل اختفائه بصمت.
        "all_third_party_domains": [],
        # [إضافة — حل Turnstile بالنقر المجاني] نتيجة محاولة النقر إن حدثت
        # (None لو لم تظهر حالة solvable_challenge إطلاقًا لهذا الرابط).
        "turnstile_click_attempt": None,
        # [إضافة — تشخيص ممتد] نتيجة probe_challenge_with_extended_wait
        # الكاملة (انتظار صافٍ + 3 نقرات + reload أخير) — None لو لم تظهر
        # solvable_challenge إطلاقًا. يستبدل المسار القديم (نقرة واحدة +
        # 5ث + reload) بوضع التشخيص فقط، ولا يمس open_and_collect الإنتاجي.
        "extended_challenge_probe": None,
    }
    _probe_start = time.monotonic()

    context = await browser.new_context(
        user_agent=UA, viewport={"width": 1280, "height": 1000}, locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    # [تحسين احترافي — مطابقة واقع الإنتاج] الممر الرئيسي هنا يستخدم _STEALTH
    # فعليًا (بدل الترقيع اليدوي القديم navigator.webdriver فقط)، لأن هذا
    # ما تفعله بروفايلات المتصفح بالإنتاج الآن — توصية مبنية على سلوك لا
    # يطابق الإنتاج كانت تضلل. المقارنة "بلا stealth" منفصلة تمامًا
    # (_no_stealth_reference_probe أدناه) لقياس الفرق الفعلي فقط.
    await _STEALTH.apply_stealth_async(context)
    page = await context.new_page()

    # رصد طلبات الشبكة الفعلية أثناء تحميل الصفحة مقابل نطاقات مزوّدي حماية
    # معروفين — دليل مباشر أدق من مطابقة النص وحدها (يلتقط أيضًا سكربتات
    # تُحمَّل بصمت بدون أي أثر نصي ظاهر بالصفحة النهائية)
    vendor_hits: dict[str, set] = {}
    target_host = (urlparse(url).hostname or "").lower()
    third_party_domains: set[str] = set()

    def _on_request(request):
        url_l = request.url.lower()
        for vendor, patterns in PROTECTION_VENDOR_NETWORK_PATTERNS.items():
            if any(p in url_l for p in patterns):
                vendor_hits.setdefault(vendor, set()).add(request.url[:160])
        try:
            req_host = (urlparse(request.url).hostname or "").lower()
        except Exception:
            req_host = ""
        if req_host and target_host and req_host != target_host and not req_host.endswith("." + target_host):
            third_party_domains.add(req_host)

    page.on("request", _on_request)

    _goto_start = time.monotonic()
    try:
        nav_response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        result["navigated"] = True
        if nav_response is not None:
            try:
                result["navigation_response_headers"] = await nav_response.all_headers()
            except Exception:
                pass
    except Exception as e:
        result["error"] = f"فشل التحميل الأولي (domcontentloaded): {e}"
    finally:
        result["goto_elapsed_sec"] = round(time.monotonic() - _goto_start, 2)

    if result["navigated"]:
        result["navigation_timing"] = await _capture_navigation_timing(page)

    try:
        result["title"] = await page.title()
    except Exception:
        pass

    # [إضافة] بصمة الصفحة الفعلية *بعد* تطبيق stealth — يُقارَن رقميًا
    # بنفس الالتقاط بلا stealth أدناه، بدل افتراض أن الترقيع نجح.
    result["fingerprint_with_stealth"] = await _capture_fingerprint_signals(page)

    result["protection_category"] = await classify_challenge_page(page)
    result["challenge_detected"] = result["protection_category"] != "none"
    if result["protection_category"] == "final_block":
        # [تصحيح حرج جديد — Fail-fast] حظر WAF/IP نهائي: لا فائدة من انتظار
        # 5 ثوانٍ + إعادة تحميل — نفس التصحيح المطبَّق بمسار الإنتاج
        # (open_and_collect)، هنا يوفّر وقت تشغيلة التشخيص نفسها أيضًا.
        result["challenge_resolved_after_reload"] = False
    elif result["protection_category"] == "solvable_challenge":
        print(f"  🛡️ تحدٍّ متصفح قابل للحل — انتظار صافٍ حتى {EXTENDED_WAIT_MAX_SEC}ث "
              f"(بلا نقر) قبل أي محاولة نقر...")
        probe = await probe_challenge_with_extended_wait(page)
        result["extended_challenge_probe"] = probe
        # توافق خلفي: نملأ turnstile_click_attempt بآخر محاولة نقر فعلية
        # إن حدثت، حتى لا تنكسر أي قراءة قديمة لهذا الحقل بالتقارير.
        if probe["click_attempts"]:
            result["turnstile_click_attempt"] = probe["click_attempts"][-1]

        if probe["pure_wait"]["resolved_during_pure_wait"]:
            print(f"  ✅ انحل التحدي بالانتظار الصافي وحده خلال "
                  f"{probe['pure_wait']['elapsed_until_resolved_sec']}ث — بلا حاجة لأي نقر")
        else:
            print(f"  ⏱️ لم ينحل خلال {EXTENDED_WAIT_MAX_SEC}ث انتظار صافٍ — "
                  f"بدء {EXTENDED_CLICK_ATTEMPTS} محاولات نقر بفاصل {EXTENDED_CLICK_GAP_SEC}ث")
            for att in probe["click_attempts"]:
                n = att["attempt_number"]
                if att["clicked"]:
                    print(f"    🖱️ محاولة {n}: نُقر ({att['click_method']})")
                elif att["iframe_found"] or att["click_method"] != "none":
                    print(f"    ⚠️ محاولة {n}: تعذّر النقر — {att['error']}")
                else:
                    print(f"    ℹ️ محاولة {n}: لا إطار ولا حاوٍ احتياطي ظاهر — {att['error']}")

        final = probe["final_after_reload"]
        if final["attempted"]:
            result["protection_category"] = final["category"] or result["protection_category"]
            result["challenge_detected"] = (final["category"] or "none") != "none"
            result["challenge_resolved_after_reload"] = bool(final["resolved"])
            if final["error"]:
                print(f"  ⚠️ فشلت إعادة التحميل الأخيرة: {final['error']}")
            try:
                result["title"] = await page.title()
            except Exception:
                pass
        else:
            # انحل بالانتظار الصافي — لم يحدث reload إطلاقًا، والعنوان/الفئة
            # الحاليان (من نهاية حلقة الانتظار) صحيحان بالفعل.
            result["challenge_resolved_after_reload"] = True
            try:
                result["title"] = await page.title()
            except Exception:
                pass

    # جدار مانع إعلانات: كشف + قياس فعلي لمدة العدّ التنازلي + تجاوز
    result["adblock_wall"] = await dismiss_adblock_wall_timed(page)

    try:
        body_text = ""
        if await page.query_selector("body"):
            body_text = (await page.inner_text("body"))[:1500]
        result["protection_signatures"] = classify_protection_signatures((result["title"] or "") + " " + body_text)
    except Exception:
        pass

    result["images_at_t0"] = await count_real_images(page)
    _wait_start = time.monotonic()
    result["images_after_wait"] = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    result["wait_for_images_elapsed_sec"] = round(time.monotonic() - _wait_start, 2)

    try:
        screenshot_path = diag_dir / f"{slug}-screenshot.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        result["screenshot_path"] = str(screenshot_path.relative_to(OUTPUT_DIR))
    except Exception as e:
        print(f"  ⚠️ تعذّر أخذ لقطة شاشة: {e}")

    # [إصلاح] "images_at_t0"/"images_after_wait" عدّ خام لكل <img> بالصفحة
    # (شامل الودجات/الشريط الجانبي)، وقريب من الصفر دائمًا فور domcontentloaded
    # — استخدامه لتقرير "هل يحتاج تمريرًا؟" يجعل الشرط صحيحًا شبه دائمًا حتى
    # لمواقع لا تحتاج تمريرًا إطلاقًا. نأخذ بدلًا منه لقطة صور مطابقة فعليًا
    # لمحددات المحتوى (CONTENT_SELECTORS) *قبل* أي تمرير — وهي نفس المقارنة
    # المستخدَمة لاتخاذ قرار do_scroll الحقيقي في الإنتاج.
    # [تصحيح — توحيد منهجية العدّ] snapshot_images يُرجع عنصرًا واحدًا لكل
    # وسم <img> بالـDOM بلا إزالة تكرار الرابط، بينما images_after_scroll
    # (أدناه) مُجمَّع عبر عدة جولات ومُزال التكرار بمفتاح الرابط (dict `seen`
    # داخل collect_images_while_scrolling). الفرق بمنهجية العدّ وحده كان
    # يجعل content_images_before_scroll > images_after_scroll حتى بلا أي
    # تراجع فعلي بالمحتوى (رُصد بـ12 من 20 تشخيصًا فعليًا لموقع لا يحتاج
    # تمريرًا أصلًا — السبب تكرار DOM محتمل من ودجات Swiper، لا فقدان
    # محتوى). الآن يُزال التكرار هنا بنفس المفتاح (url) لمقارنة متكافئة.
    snapshot_items = await snapshot_images(page, CONTENT_SELECTORS)
    snapshot_unique_urls = {it["url"] for it in snapshot_items if it.get("url")}
    result["content_images_before_scroll"] = len(snapshot_unique_urls)

    _scroll_start = time.monotonic()
    _scroll_meta: dict = {}
    scrolled_items = await collect_images_while_scrolling(page, CONTENT_SELECTORS, scroll_meta=_scroll_meta)
    result["scroll_elapsed_sec"] = round(time.monotonic() - _scroll_start, 2)
    result["images_after_scroll"] = len(scrolled_items)
    # [إضافة — البند 4] يميّز "توقف مبكر لاستقرار المحتوى" عن "وصول السقف
    # الزمني" عن "لا نمو عند القاع" — بدل نسب أي تذبذب بين تشغيلتين
    # (consistency_diffs) لـ"حماية احتمالية" افتراضيًا بلا دليل.
    result["scroll_rounds_completed"] = _scroll_meta.get("rounds_completed")
    result["scroll_stop_reason"] = _scroll_meta.get("stop_reason")

    selector_counts = {sel: 0 for sel in CONTENT_SELECTORS}
    unmatched = 0
    for item in scrolled_items:
        if item["matched"]:
            for sel in item["matched"]:
                selector_counts[sel] = selector_counts.get(sel, 0) + 1
        else:
            unmatched += 1
    result["selector_match_counts"] = selector_counts
    result["unmatched_img_count"] = unmatched
    result["suggested_selectors"] = _suggest_selectors_from_unmatched(scrolled_items)

    filtered = _filter_widget_context(scrolled_items)
    result["widget_excluded_count"] = len(scrolled_items) - len(filtered)
    # [تصحيح — البند 5] كان يعرض أول 80 حرفًا من ctx كاملًا، وctx يبدأ بكلاس
    # عنصر <img> نفسه ثم يتصاعد للآباء (راجع COLLECT_IMAGES_JS) — فلو كان
    # التطابق الفعلي بعيدًا بالآباء (مثلًا كلاس "related-posts" بأب رابع)،
    # أول 80 حرفًا يعرض كلاس الصورة ذاته ولا يظهر سبب الاستبعاد الحقيقي
    # إطلاقًا. الآن يُستخرَج جزء ctx حول التطابق الفعلي (سياق 40 حرفًا قبله
    # وبعده) للتحقق اليدوي الفعلي بدل تخمين السبب.
    widget_samples = []
    for it in scrolled_items:
        ctx = it.get("ctx", "")
        m = WIDGET_CONTEXT_PATTERN.search(ctx)
        if not m:
            continue
        start = max(0, m.start() - 40)
        end = min(len(ctx), m.end() + 40)
        snippet = ctx[start:end].strip()
        widget_samples.append((f"...{snippet}..." if start > 0 or end < len(ctx) else snippet))
        if len(widget_samples) >= 3:
            break
    result["widget_excluded_samples"] = widget_samples

    domains = Counter(urlparse(it["url"]).hostname for it in scrolled_items if it.get("url"))
    result["domain_distribution"] = dict(domains.most_common(5))

    result["signed_url_params"] = _detect_signed_url_params(
        [it["url"] for it in scrolled_items if it.get("url")]
    )

    # [إصلاح منطقي ب + معلومة مفقودة "عدة صور عيّنة"] حتى 3 عيّنات موزّعة
    # (أولى/وسط/أخيرة) بدل واحدة فقط — كل واحدة تخضع للعزل الثلاثي الكامل.
    # [تصحيح] العينات تُختار من `filtered` (بعد استبعاد سياق الودجات) لا من
    # `scrolled_items` الخام — رُصد فعليًا اختيار صورة تعليق/ودجت كعيّنة
    # (مثال: .../images/comments/...) بدل صورة محتوى حقيقية، ما يجعل فحص
    # hotlink/signed-url غير ممثّل بالضرورة لصور الفصل الفعلية التي سيُنزّلها
    # الإنتاج. لا أثر عملي على olympustaff تحديدًا (CDN مفتوح للكل بلا تفريق)،
    # لكنه يمنع نتيجة مضلِّلة على موقع تختلف فيه حماية صور المحتوى عن الودجات.
    sample_urls = _pick_sample_urls(filtered, url, n=3)
    for s_url in sample_urls:
        result["hotlink_probes"].append(await _hotlink_probe_one(context, s_url, url))
    if result["hotlink_probes"]:
        result["hotlink_probe"] = result["hotlink_probes"][0]  # توافق خلفي (عينة أولى)

    # اختبار إعادة استخدام كوكيز الجلسة بطلب HTTP عادي — بعد كل ما سبق (حتى
    # يشمل أي كوكيز نتجت عن تجاوز جدار/تحدٍّ)
    result["cookie_reuse_probe"] = await _cookie_reuse_probe(context, url)

    page.remove_listener("request", _on_request)
    result["network_vendor_hits"] = {k: sorted(v)[:3] for k, v in vendor_hits.items()}
    result["all_third_party_domains"] = sorted(third_party_domains)

    # [إضافة — المرحلة أ] إجمالي زمن الممر الرئيسي (goto حتى إغلاق السياق،
    # بstealth، بلا التكرار الثاني للاتساق ولا فحص no-stealth المرجعي
    # المنفصل أدناه) — هذا الرقم تحديدًا هو ما يُقارَن مستقبلًا بوقت مسار
    # HTTP المباشر عند تقييم جدوى الاستراتيجية الهجينة.
    result["total_probe_elapsed_sec"] = round(time.monotonic() - _probe_start, 2)

    await context.close()

    # [إضافة — قياس واقعي بدل افتراض] تشغيل مرجعي منفصل بلا أي تمويه إطلاقًا،
    # يُرفَق خامًا بالتقرير (stealth_comparison) للمقارنة برقمَي الممر
    # الرئيسي — بلا أي استنتاج نصي مُدمَج بالكود حول معنى الفرق.
    no_stealth = await _no_stealth_reference_probe(browser, url)
    fp_stealth = result.get("fingerprint_with_stealth") or {}
    fp_no_stealth = no_stealth.get("fingerprint") or {}
    result["stealth_comparison"] = {
        "no_stealth": no_stealth,
        "webdriver_flag_hidden_by_stealth": (
            fp_no_stealth.get("webdriver") not in (None, False)
            and fp_stealth.get("webdriver") in (None, False)
        ),
        "challenge_outcome_differs": no_stealth.get("challenge_detected") != result.get("challenge_detected"),
        "image_count_differs": no_stealth.get("images_after_wait") != result.get("images_after_wait"),
    }

    return result


def _diff_browser_probes(a: dict, b: dict) -> list[str]:
    """[معلومة مفقودة — إعادة فحص مزدوج] يقارن أهم مؤشرات نتيجتَي فحص متصفح
    منفصلتين (كل واحدة بجلسة نظيفة كاملة عبر browser.new_context) لنفس
    الرابط — أنظمة حماية كثيرة احتمالية (تسمح أحيانًا وتمنع أحيانًا)، وفحص
    وحيد لا يعكس هذا التذبذب."""
    fields = {
        "challenge_detected": "صفحة تحقق مكتشفة",
        "protection_signatures": "مزوّد الحماية المصنَّف",
        "images_after_scroll": "عدد الصور بعد التمرير",
        "unmatched_img_count": "صور غير مطابقة",
    }
    diffs = []
    for key, label in fields.items():
        va, vb = a.get(key), b.get(key)
        if va != vb:
            note = ""
            # [إضافة — البند 4] لو الفرق بعدد الصور بعد التمرير تحديدًا،
            # نرفق سبب توقف التمرير بكل تشغيلة — لو كان "توقف مبكر لاستقرار
            # المحتوى" (لا سقف زمني ولا تذبذب حماية)، فالتفسير الأرجح توقف
            # تمرير مبكر لهذا الرابط تحديدًا، لا سلوك الموقع المتذبذب.
            if key == "images_after_scroll":
                note = (f" [سبب توقف التمرير: الأول={a.get('scroll_stop_reason')!r}"
                        f"({a.get('scroll_rounds_completed')} جولة) الثاني={b.get('scroll_stop_reason')!r}"
                        f"({b.get('scroll_rounds_completed')} جولة)]")
            diffs.append(f"{label}: الأول={va!r} الثاني={vb!r}{note}")
    hp_a = (a.get("hotlink_probes") or [{}])[0]
    hp_b = (b.get("hotlink_probes") or [{}])[0]
    if hp_a.get("referer_only_sufficient") != hp_b.get("referer_only_sufficient"):
        diffs.append(
            f"كفاية Referer وحده: الأول={hp_a.get('referer_only_sufficient')!r} الثاني={hp_b.get('referer_only_sufficient')!r}"
        )
    return diffs


async def diagnose_url(browser, url: str, diag_dir: Path, runner_info: dict | None = None) -> dict:
    slug = slugify((urlparse(url).hostname or "site") + "-" + str(abs(hash(url)) % 10000))
    site_slug = slugify(urlparse(url).hostname or "site")
    print("\n" + "═" * 60)
    print(f"🔬 تقرير تشخيصي: {url}")
    print("═" * 60)

    print("⓪ معلومات شبكة أساسية (TLS + IP الخادم)...")
    tls_info = await asyncio.to_thread(_tls_and_server_info_sync, url)
    if tls_info["error"]:
        print(f"   ⚠️ {tls_info['error']}")
    else:
        print(f"   IP الخادم: {tls_info['server_ip']}")
        print(f"   شهادة TLS — الجهة المُصدِرة: {tls_info['tls_issuer']!r} | الاسم: {tls_info['tls_subject']!r} | تنتهي: {tls_info['tls_not_after']}")
    if runner_info and not runner_info.get("error"):
        print(f"   🌐 IP/موقع الـrunner الحالي: {runner_info.get('ip')} ({runner_info.get('org_asn')}, {runner_info.get('city')}/{runner_info.get('country')})")

    print("① فحص HTTP خام (بدون Playwright إطلاقًا)...")
    static_r = await asyncio.to_thread(_static_probe_sync, url)
    if static_r["error"]:
        print(f"   ❌ فشل الطلب المباشر: {static_r['error']}")
    else:
        print(f"   حالة الاستجابة: {static_r['status_code']}")
        if static_r["headers_of_interest"]:
            print(f"   ترويسات ملفتة: {static_r['headers_of_interest']}")
        print(f"   صفحة تحقق/حماية مكتشفة (تصنيف نمطي): {'نعم ⚠️' if static_r['challenge_detected'] else 'لا'}")
        if static_r["protection_signatures"]:
            print(f"   🛡️ توقيعات حماية مطابَقة: {', '.join(static_r['protection_signatures'])}")
        print(f"   صور عبر noscript: {static_r['images_via_noscript']} | عبر data-src: {static_r['images_via_data_attr']} | عبر src عادي: {static_r['images_via_plain_src']}")
        print(f"   📌 العدد الذي سيُستخرَج فعليًا بمسار HTTP المباشر (نفس منطق الإنتاج): {static_r['extracted_image_count']}")
        if static_r["sample_image_urls"]:
            print("   عينة روابط صور من HTML الثابت:")
            for u in static_r["sample_image_urls"]:
                print(f"     - {u}")
        if static_r["signed_url_params"]:
            print(f"   🔑 روابط تحمل معاملات توقيع/انتهاء صلاحية: {static_r['signed_url_params']}")

    print("② فحص متصفح كامل (تحميل + جدار إعلانات + انتظار + تمرير تراكمي)...")
    browser_r = await _browser_probe(browser, url, diag_dir, slug)
    if browser_r["error"]:
        print(f"   ⚠️ {browser_r['error']}")
    print(f"   عنوان الصفحة: {browser_r['title']!r}")
    print(f"   صفحة تحقق/حماية مكتشفة عبر المتصفح (تصنيف نمطي): {'نعم ⚠️' if browser_r['challenge_detected'] else 'لا'}")
    if browser_r["challenge_resolved_after_reload"] is not None:
        print(f"   🔁 حالة التحدي بعد إعادة التحميل: {browser_r['challenge_resolved_after_reload']}")
    ecp = browser_r.get("extended_challenge_probe")
    if ecp is not None:
        pw = ecp["pure_wait"]
        if pw["resolved_during_pure_wait"]:
            print(f"   ⏱️ الانتظار الصافي (بلا نقر): ✅ انحل خلال {pw['elapsed_until_resolved_sec']}ث "
                  f"من أصل {pw['max_wait_sec']}ث كحد أقصى")
        else:
            print(f"   ⏱️ الانتظار الصافي (بلا نقر): ❌ لم ينحل خلال كامل {pw['max_wait_sec']}ث")
            for att in ecp["click_attempts"]:
                n, method = att["attempt_number"], att["click_method"]
                outcome = "نُقر فعليًا" if att["clicked"] else ("حاوٍ موجود، فشل النقر" if method != "none" else "لا إطار ولا حاوٍ احتياطي")
                print(f"   🖱️ محاولة نقر {n}/{EXTENDED_CLICK_ATTEMPTS} (طريقة: {method}): {outcome}")
            final = ecp["final_after_reload"]
            if final["attempted"]:
                print(f"   🔁 بعد آخر نقرة + reload أخير: {'✅ انحل' if final['resolved'] else '❌ ما زال ظاهرًا'}")
    if browser_r["protection_signatures"]:
        print(f"   🛡️ توقيعات حماية مطابَقة (متصفح): {', '.join(browser_r['protection_signatures'])}")
    if browser_r.get("navigation_response_headers"):
        nrh = browser_r["navigation_response_headers"]
        cf_keys = {k: v for k, v in nrh.items() if k in ("cf-mitigated", "cf-ray", "cf-cache-status", "alt-svc", "server")}
        if cf_keys:
            print(f"   📡 ترويسات استجابة التنقّل الرئيسي عبر المتصفح: {cf_keys}")
    if browser_r["network_vendor_hits"]:
        print("   🌐 طلبات شبكة مطابقة لأنماط مزوّدي حماية معروفة مسبقًا:")
        for vendor, samples in browser_r["network_vendor_hits"].items():
            print(f"     - {vendor}: {samples}")
    if browser_r.get("all_third_party_domains"):
        print(f"   🌐 كل نطاقات الطرف الثالث المتصل بها فعليًا (خام، غير مصفّى لقائمة معروفة): {browser_r['all_third_party_domains']}")
    sc = browser_r.get("stealth_comparison") or {}
    if sc:
        ns = sc.get("no_stealth") or {}
        print(f"   🕵️ مقارنة stealth: بلا-stealth (تحقق={ns.get('challenge_detected')}, "
              f"صور={ns.get('images_after_wait')}) ↔ بstealth (تحقق={browser_r['challenge_detected']}, "
              f"صور={browser_r['images_after_wait']})")
        print(f"   🕵️ navigator.webdriver — بلا-stealth: {ns.get('fingerprint', {}).get('webdriver') if ns else None}، "
              f"بstealth: {browser_r.get('fingerprint_with_stealth', {}).get('webdriver')}")
    aw = browser_r.get("adblock_wall") or {}
    if aw.get("detected"):
        status = f"لم يصبح جاهزًا خلال {aw.get('became_ready_after_sec')}ث" if aw.get("timed_out") else f"جاهز بعد {aw.get('became_ready_after_sec')}ث"
        print(f"   🧱 جدار مانع إعلانات مكتشَف — {status} — تم الضغط: {aw.get('clicked')}")
    print(f"   منحنى نمو عدد الصور — أول لحظة: {browser_r['images_at_t0']} → بعد الانتظار: {browser_r['images_after_wait']} → بعد التمرير: {browser_r['images_after_scroll']}")
    print(f"   جولات التمرير المكتملة: {browser_r.get('scroll_rounds_completed')} | سبب التوقف: {browser_r.get('scroll_stop_reason')}")
    nt = browser_r.get("navigation_timing") or {}
    nav_txt = f" (TTFB={nt['ttfb_ms']}ms, DOMContentLoaded={nt['dom_content_loaded_ms']}ms)" if nt else ""
    print(f"   ⏱️ أزمنة مقاسة فعليًا — goto: {browser_r.get('goto_elapsed_sec')}ث{nav_txt} | "
          f"انتظار استقرار الصور: {browser_r.get('wait_for_images_elapsed_sec')}ث | "
          f"تمرير: {browser_r.get('scroll_elapsed_sec')}ث | "
          f"إجمالي الممر الرئيسي: {browser_r.get('total_probe_elapsed_sec')}ث")
    if static_r.get("elapsed_sec") is not None:
        print(f"   ⏱️ للمقارنة — زمن مسار HTTP المباشر وحده: {static_r['elapsed_sec']}ث")
    print(f"   مطابقة المحددات الحالية: {browser_r['selector_match_counts']}")
    print(f"   صور لا تطابق أي محدد معروف: {browser_r['unmatched_img_count']}")
    if browser_r["suggested_selectors"]:
        print(f"   💡 توكنات متكررة بالصور غير المطابقة (بيانات خام، لا اعتماد تلقائي): {browser_r['suggested_selectors']}")
    if browser_r["widget_excluded_count"]:
        print(f"   🧹 فلتر الودجات استبعد {browser_r['widget_excluded_count']} صورة — عينات سياق: {browser_r['widget_excluded_samples']}")
    else:
        print("   🧹 فلتر الودجات لم يستبعد أي صورة")
    if browser_r["domain_distribution"]:
        print(f"   توزيع النطاقات: {browser_r['domain_distribution']}")
    if browser_r["signed_url_params"]:
        print(f"   🔑 روابط تحمل معاملات توقيع/انتهاء صلاحية عبر المتصفح: {browser_r['signed_url_params']}")

    print("②-تكرار إعادة فحص كامل بجلسة نظيفة ثانية (فحص اتساق)...")
    browser_r2 = await _browser_probe(browser, url, diag_dir, slug + "-run2")
    consistency_diffs = _diff_browser_probes(browser_r, browser_r2)
    if consistency_diffs:
        print("   🎲 فروقات مكتشَفة بين التكرارين:")
        for d in consistency_diffs:
            print(f"     - {d}")
    else:
        print("   ✅ النتيجة متطابقة بين التكرارين")

    hotlink_probes = browser_r.get("hotlink_probes") or []
    if hotlink_probes:
        print(f"③ فحص حماية السرقة (hotlink) على {len(hotlink_probes)} صورة عيّنة (أولى/وسط/أخيرة) — عزل ثلاثي لكل واحدة...")
        for i, hp in enumerate(hotlink_probes, start=1):
            print(f"   — عيّنة {i}: {hp['sample_url']}")
            no_ref_line = f"     بلا Referer وبلا كوكيز: {hp['no_referer_success']} ({hp['no_referer_size']} بايت)"
            if not hp["no_referer_success"]:
                no_ref_line += f" — السبب: {hp['no_referer_fail_reason']}"
            print(no_ref_line)
            direct_line = f"     بReferer صحيح وبلا كوكيز: {hp['direct_http_success']} ({hp['direct_http_size']} بايت)"
            if not hp["direct_http_success"]:
                direct_line += f" — السبب: {hp['direct_http_fail_reason']}"
            print(direct_line)
            session_line = f"     بجلسة متصفح كاملة: {hp['browser_session_success']} ({hp['browser_session_size']} بايت)"
            if not hp["browser_session_success"]:
                session_line += f" — السبب: {hp['browser_session_fail_reason']}"
            print(session_line)
            print(f"     referer_only_sufficient: {hp.get('referer_only_sufficient')}")
            if hp.get("image_cache_headers"):
                print(f"     ترويسات تخزين مؤقت لصورة العيّنة: {hp['image_cache_headers']}")
        modes = {hp["direct_http_success"] for hp in hotlink_probes}
        if len(modes) > 1:
            print("   🎲 نتيجة hotlink اختلفت بين العيّنات (تفصيل أعلاه لكل عيّنة)")
    else:
        print("③ لم يتوفر رابط صورة عينة لفحص حماية السرقة")

    cr = browser_r.get("cookie_reuse_probe") or {}
    print("④ اختبار إعادة استخدام كوكيز الجلسة بطلب HTTP عادي...")
    if not cr.get("tested"):
        print(f"   لم يُختبَر: {cr.get('reason', '—')}")
    else:
        print(f"   نجح: {cr.get('success')} (status={cr.get('status_code')}, "
              f"عدد الكوكيز: {cr.get('cookie_count_reused')}, أسماء الكوكيز: {cr.get('cookie_names_reused')})")
        # [تصحيح] الأثر العملي المباشر لهذه النتيجة على قرار البروفايل لم يكن
        # صريحًا — كان يُترَك للقارئ استنتاجه من status_code وحده. الآن يُذكَر
        # صراحة: نجاح=True يعني fetch_mode هجين (حل واحد بالمتصفح ثم HTTP لباقي
        # الفصول) ممكن نظريًا لهذا الموقع؛ فشل=True يعني fetch_mode: "browser"
        # وحده هو الخيار الصالح — كل فصل يحتاج تمريرة متصفح كاملة بلا اختصار.
        if cr.get("success"):
            print("   💡 الأثر العملي: كوكيز الجلسة صالحة لطلب HTTP عادٍ — نمط هجين "
                  "(حل واحد بالمتصفح ثم HTTP سريع لباقي الفصول) مطروح كتحسين أداء ممكن.")
        else:
            print("   💡 الأثر العملي: كوكيز الجلسة غير كافية لطلب HTTP عادٍ (الحماية "
                  "على مستوى الصفحة/JS لا الكوكيز فقط) — fetch_mode: \"browser\" وحده "
                  "صالح؛ كل فصل يتطلب تمريرة متصفح كاملة، لا اختصار HTTP ممكن.")

    print("⑤ فحص تحديد المعدل (Rate Limiting) — 4 طلبات موازية فعليًا...")
    rate_limit_sample = None
    if hotlink_probes:
        rate_limit_sample = hotlink_probes[0]["sample_url"]
    if rate_limit_sample:
        print(f"   🎯 الهدف: رابط صورة CDN عيّنة (يحاكي الحمل الحقيقي وقت التشغيل): {rate_limit_sample}")
        rl = await _rate_limit_probe_image(rate_limit_sample, url)
    else:
        print("   ⚠️ لا رابط صورة متاح — رجوع لرابط الصفحة (أقل تمثيلًا للحمل الحقيقي)")
        rl = await asyncio.to_thread(_rate_limit_probe_sync, url)
    print(f"   الحالات: {rl['status_codes']} خلال {rl['elapsed_sec']}ث"
          + (f" — Retry-After: {rl['retry_after_header']}" if rl['retry_after_header'] else ""))

    if browser_r["screenshot_path"]:
        print(f"   🖼️ لقطة شاشة مرجعية محفوظة: {browser_r['screenshot_path']}")

    # [معلومة مفقودة — تتبع تاريخي] مقارنة بآخر فحص محفوظ لنفس الموقع (بحسب
    # hostname) على فرع الإخراج، وحفظ لقطة جديدة بالتاريخ للفحوصات القادمة.
    # حقول خام فقط (لا استنتاج تركيبي) — كل حقل هنا كشف نمطي مباشر أو رقم
    # مقاس، بلا قرار fetch_mode/likely_unfixable مبني على دمجها.
    first_hp = hotlink_probes[0] if hotlink_probes else {}
    current_snapshot = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "url": url,
        "protection_category_static": static_r.get("protection_category"),
        "protection_category_browser": browser_r.get("protection_category"),
        "challenge_detected_static": static_r.get("challenge_detected"),
        "challenge_detected_browser": browser_r.get("challenge_detected"),
        "cf_mitigated_static": static_r.get("headers_of_interest", {}).get("cf-mitigated"),
        "cf_mitigated_browser": browser_r.get("navigation_response_headers", {}).get("cf-mitigated"),
        "protection_signatures": sorted(set((static_r.get("protection_signatures") or []) + (browser_r.get("protection_signatures") or []))),
        "referer_only_sufficient": first_hp.get("referer_only_sufficient"),
        "rate_limited_detected": rl.get("rate_limited_detected"),
        "static_block_detected": rl.get("static_block_detected"),
        "signed_url_params": sorted(set((static_r.get("signed_url_params") or []) + (browser_r.get("signed_url_params") or []))),
    }
    history = await asyncio.to_thread(_load_diagnostic_history_sync, site_slug)
    print("⑥ تتبّع تاريخي (مقارنة بآخر فحص محفوظ لهذا الموقع)...")
    history_diffs = []
    if history:
        history_diffs = _diff_diagnostic_snapshots(history[-1], current_snapshot)
        if history_diffs:
            print(f"   🚨 تغيّر منذ آخر فحص ({history[-1].get('date', '؟')}):")
            for d in history_diffs:
                print(f"     - {d}")
        else:
            print(f"   ✅ لا تغيّر منذ آخر فحص محفوظ ({history[-1].get('date', '؟')})")
    else:
        print("   ℹ️ لا يوجد فحص سابق محفوظ لهذا الموقع — هذه أول لقطة تاريخية")
    await asyncio.to_thread(_save_diagnostic_history_sync, site_slug, history + [current_snapshot])
    print("═" * 60)

    # [جديد — أرشيف تشغيلة قابل للتنزيل] slug مبني جزئيًا على hash() النصي،
    # وهو عشوائي بذرته لكل عملية بايثون (PYTHONHASHSEED) — أي استدعاء منفصل
    # لإعادة حساب نفس slug خارج هذه الدالة غير موثوق. بدل ذلك، تُسجَّل هنا
    # المسارات الفعلية (نسبية لـOUTPUT_DIR، بنفس تنسيق screenshot_path) التي
    # كتبتها هذه الدالة تحديدًا لهذا الرابط، ليستخدمها run_diagnostic_mode
    # لاحقًا لبناء zip خاص بهذه التشغيلة فقط دون تخمين أسماء الملفات.
    report_relpath = f"diagnostics/{slug}-report.json"
    report = {
        "url": url, "tls_and_server_info": tls_info, "runner_network_info": runner_info,
        "static_probe": static_r, "browser_probe": browser_r, "browser_probe_second_run": browser_r2,
        "consistency_diffs": consistency_diffs, "rate_limit_probe": rl,
        "history_diffs_since_last_run": history_diffs,
        "diagnostic_run_files": {
            "report": report_relpath,
            "screenshots": [
                p for p in [browser_r.get("screenshot_path"), browser_r2.get("screenshot_path")] if p
            ],
        },
    }
    (diag_dir / f"{slug}-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return report


async def run_diagnostic_mode(chapter_urls: list[str]) -> None:
    print("🔬 وضع التشخيص مفعّل (موسّع) — لن يُنزَّل أو يُضغط أي فصل فعليًا، ولن يُستخدم اختيار الموقع المصدر إطلاقًا")
    if len(chapter_urls) > 3:
        print(f"⚠️ تم إدخال {len(chapter_urls)} رابط — يُفضَّل رابط أو رابطين فقط (كل رابط يفتح متصفحًا كاملًا ويشغّل فحصًا مزدوجًا لكل مرحلة). سيُتابَع بكل الروابط رغم ذلك")

    diag_dir = OUTPUT_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # [معلومة مفقودة] IP/ASN الخاص بالـrunner — طلب واحد يكفي لكل التشغيلة
    # (نفس الشبكة لكل الروابط بهذه التشغيلة)، لا لكل رابط على حدة.
    print("🌐 جلب معلومات شبكة الـrunner الحالي (IP/ASN)...")
    runner_info = await asyncio.to_thread(_runner_network_info_sync)
    if runner_info.get("error"):
        print(f"   ⚠️ تعذّر جلب معلومات الشبكة: {runner_info['error']}")
    else:
        print(f"   IP: {runner_info.get('ip')} | ASN/مزوّد: {runner_info.get('org_asn')} | الموقع: {runner_info.get('city')}/{runner_info.get('country')}")

    reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for url in chapter_urls:
            try:
                report = await diagnose_url(browser, url, diag_dir, runner_info)
                reports.append(report)
            except Exception as e:
                print(f"❌ خطأ غير متوقع أثناء تشخيص {url}: {e}")
                reports.append({"url": url, "error": str(e)})
        await browser.close()

    (diag_dir / "summary.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # [جديد — أرشيف zip خاص بهذه التشغيلة فقط] output/diagnostics/ يتراكم
    # عبر التشغيلات (worktree يسحب فرع output الحالي بتاريخه كاملًا قبل
    # التشغيل)، لذا لا الـartifact ولا مجلد diagnostics المدفوع يمثلان "هذه
    # التشغيلة فقط" فعليًا — فقط summary.json كان كذلك. هنا نجمع تحديدًا:
    # summary.json + تقرير كل رابط بهذه التشغيلة + لقطتي الشاشة (الفحص
    # الأول والثاني) إن وُجدتا، بالاعتماد على diagnostic_run_files المُسجَّل
    # داخل كل report (لا بإعادة تخمين slug). يُحفظ في مسار run-<RUN_ID>
    # موازٍ لنمط output/runs/run-<RUN_ID>.json المستخدم أصلًا للفصول
    # (RUN_MANIFEST_RELPATH)، ويقع أصلًا ضمن allowed_paths=["diagnostics"]
    # أدناه فلا حاجة لأي تعديل بمنطق الدفع. الهدف: رابط raw.githubusercontent
    # مباشر (بلا تسجيل دخول) يُنزَّل بموثوقية على أندرويد، بعكس رابط أرتيفاكت
    # GitHub Actions الذي يعتمد على واجهة/جلسة الموقع.
    run_zip_relpath = f"diagnostics/runs/run-{RUN_ID}.zip"
    run_zip_path = OUTPUT_DIR / run_zip_relpath
    run_zip_path.parent.mkdir(parents=True, exist_ok=True)

    files_to_zip: list[Path] = [diag_dir / "summary.json"]
    for r in reports:
        dfiles = (r or {}).get("diagnostic_run_files") or {}
        if dfiles.get("report"):
            files_to_zip.append(OUTPUT_DIR / dfiles["report"])
        for sp in dfiles.get("screenshots") or []:
            files_to_zip.append(OUTPUT_DIR / sp)

    zip_ok = True
    zipped_count = 0
    try:
        with zipfile.ZipFile(run_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in files_to_zip:
                try:
                    if fp.is_file():
                        zf.write(fp, arcname=fp.relative_to(diag_dir))
                        zipped_count += 1
                    else:
                        print(f"   ⚠️ ملف تشخيصي متوقَّع غير موجود على القرص، تخطّي من zip: {fp}")
                except Exception as e:
                    print(f"   ⚠️ تعذّر إضافة {fp} لملف zip التشغيلة: {e}")
    except Exception as e:
        zip_ok = False
        print(f"⚠️ تعذّر إنشاء zip التشخيص الخاص بهذه التشغيلة: {e}")

    if zip_ok:
        print(f"🗜️ أُنشئ أرشيف zip خاص بهذه التشغيلة فقط ({zipped_count} ملف): {run_zip_relpath}")

    if GIT_COMMIT_DIR:
        # [تصحيح حرج ٥] وضع التشخيص يكتب حصرًا ضمن output/diagnostics/ ولا
        # يلمس manifest.json أو مجلدات الفصول إطلاقًا — تقييد allowed_paths
        # على مجلد diagnostics فقط يمنع أي احتمال لحذف نتائج فصول تشغيلات
        # أخرى بنفس الآلية الموصوفة أعلاه، دون الحاجة لتعداد كل ملف تشخيصي
        # فرعي (تقارير/لقطات شاشة/تتبع تاريخي) بالاسم.
        ok, msg = await asyncio.to_thread(
            _commit_and_push_sync,
            GIT_COMMIT_DIR,
            GIT_BRANCH,
            "تقرير تشخيصي جديد + تحديث التتبع التاريخي",
            ["diagnostics"],
        )
        print(f"{'✅' if ok else '⚠️'} دفع تقرير التشخيص: {msg}")

    print("\n" + "=" * 50)
    print(f"✅ اكتمل التشخيص لـ {len(reports)} رابط")
    print(f"📁 التقارير التفصيلية + لقطات الشاشة في: {diag_dir}")
    print("📎 كما تُرفَع نسخة كأرتيفاكت مستقل في صفحة التشغيلة على GitHub Actions")
    if zip_ok:
        print(f"🔗 أرشيف zip خاص بهذه التشغيلة فقط (تقارير + صور، رابط تنزيل مباشر يعمل على أندرويد): {OUTPUT_DIR}/{run_zip_relpath}")
    print("=" * 50)


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
        await run_diagnostic_mode(chapter_urls)
        return

    if OCR_EXPERIMENT_MODE:
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
