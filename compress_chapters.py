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

نتيجة كل هذا: توصية آلية جاهزة للصق داخل PROFILES، مع ملف JSON تفصيلي +
لقطة شاشة لكل رابط في output/diagnostics، مرفوعة كأرتيفاكت GitHub Actions
مستقل، ومدفوعة لفرع output إن كان الدفع التدريجي مفعّلًا.
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
  ودفعت بنجاح حسب سجلّها الخاص، اختفى لاحقًا من الفرع البعيد). الإصلاح:
  التقاط قائمة الملفات التي غيّرها التزام هذه التشغيلة تحديدًا (قبل أي
  reset، عبر git diff --name-only) وتقييد كل "git add" بعد reset على تلك
  القائمة فقط — بدل مجلد الإخراج كامل — في كل من compress_chapters.py
  (_commit_and_push_sync) وخطوة "دفع احتياطي نهائي" بملف الـworkflow،
  بحيث لا تُلمَس إطلاقًا أي ملفات لم تكتبها هذه التشغيلة نفسها.
================================================================================
"""
import asyncio
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import requests.adapters  # استيراد صريح — كان يعمل سابقًا فقط بأثر جانبي غير موثّق
import requests.cookies   # لاستخدام RequestsCookieJar في فحص إعادة استخدام الكوكيز
from PIL import Image
from io import BytesIO
from playwright.async_api import async_playwright

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
    "Cloudflare Challenge": ["challenges.cloudflare.com", "/cdn-cgi/challenge-platform"],
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
    "mangatuk": {"label": "مانجا توك", "fetch_mode": "browser", "do_scroll": False, "do_widget_filter": False},
    "mangatime": {"label": "مانجا تايم", "fetch_mode": "browser", "do_scroll": True, "do_widget_filter": True},
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


def _looks_like_challenge_html(html: str) -> bool:
    low = html.lower()
    if any(m in low for m in CHALLENGE_TITLE_MARKERS):
        return True
    return sum(1 for m in CHALLENGE_BODY_MARKERS if m in low) >= 2


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

async def looks_like_challenge_page(page) -> bool:
    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    if any(m in title for m in CHALLENGE_TITLE_MARKERS):
        return True
    try:
        body_text = ""
        if await page.query_selector("body"):
            body_text = (await page.inner_text("body"))[:800].lower()
    except Exception:
        return False
    return sum(1 for m in CHALLENGE_BODY_MARKERS if m in body_text) >= 2


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


async def collect_images_while_scrolling(page, content_selectors: list[str]) -> list[dict]:
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
    for _ in range(SCROLL_MAX_STEPS):
        if time.monotonic() - start > SCROLL_MAX_TOTAL_SEC:
            print(f"  ⏱️ توقف التمرير عند السقف الزمني ({SCROLL_MAX_TOTAL_SEC}ث) — استخدام ما جُمع حتى الآن")
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
                break
        else:
            stable_rounds = 0

        if content_stable_rounds >= CONTENT_STABLE_ROUNDS_REQUIRED:
            print(f"  ⏱️ استقرت صور محتوى القراءة الفعلية ({cur_content}) — إيقاف التمرير مبكرًا")
            break

        if not reached_bottom:
            try:
                await page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.85))")
            except Exception:
                pass
        await page.wait_for_timeout(SCROLL_STEP_WAIT_MS)

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


async def extract_image_urls(page, base_url: str, do_scroll: bool, do_widget_filter: bool) -> list[str]:
    try:
        items = await (collect_images_while_scrolling(page, CONTENT_SELECTORS) if do_scroll
                       else snapshot_images(page, CONTENT_SELECTORS))
    except Exception:
        items = []

    filtered = _filter_widget_context(items) if do_widget_filter else items

    if filtered:
        for selector in CONTENT_SELECTORS:
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
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = await context.new_page()

    navigated = False
    wait_strategy = "domcontentloaded" if attempt == 1 else "load"
    try:
        await page.goto(chapter_url, wait_until=wait_strategy, timeout=NAV_TIMEOUT_MS)
        navigated = True
    except Exception as e:
        print(f"  ⚠️ تعذّر تحميل الصفحة ({wait_strategy}): {e}")

    if navigated and await looks_like_challenge_page(page):
        print("  🛡️ صفحة تحقق/حماية محتملة (Cloudflare أو ما شابه) — انتظار وإعادة تحميل")
        await page.wait_for_timeout(5000)
        try:
            await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
            # [إصلاح منطقي أ] لا نفترض أن الreload حلّ التحدي — نعيد الفحص
            # فعليًا بعده مباشرة (أغلب تحديات Cloudflare JS تنحل تلقائيًا
            # خلال الانتظار، لكن ليس كلها).
            if await looks_like_challenge_page(page):
                print("  ⚠️ التحدي ما زال ظاهرًا بعد إعادة التحميل")
            else:
                print("  ✅ التحدي انحل بعد إعادة التحميل")
        except Exception as e:
            print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): {found_count}")

    t0 = time.monotonic()
    do_scroll = profile.get("do_scroll", True)
    do_widget_filter = profile.get("do_widget_filter", True)
    image_urls = await extract_image_urls(page, chapter_url, do_scroll, do_widget_filter)
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

def compress_image(raw_bytes: bytes, max_width: int, quality: int) -> bytes:
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
        "fetch_mode_recommended": "fetch_mode المقترح",
        "challenge_detected_static": "صفحة تحقق (HTTP خام)",
        "challenge_detected_browser": "صفحة تحقق (متصفح)",
        "protection_signatures": "مزوّد الحماية المصنَّف",
        "referer_only_sufficient": "كفاية Referer وحده",
        "rate_limited_detected": "تحديد معدل مكتشَف",
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


def _commit_and_push_sync(commit_dir: str, branch: str, message: str, max_attempts: int = 5) -> tuple[bool, str]:
    # [تصحيح حرج ١] نستخدم مسار OUTPUT_DIR الفعلي المحسوب نسبيًا لمستودع
    # git، بدل الاسم الحرفي الثابت "output" الذي كان يتجاهل تخصيص
    # OUTPUT_DIR بالكامل ويسبب فقدان نتائج صامتًا.
    git_rel_output = _compute_git_relative_output_dir(commit_dir)
    if git_rel_output is None:
        return False, f"OUTPUT_DIR ({OUTPUT_DIR}) ليس داخل GIT_COMMIT_DIR ({commit_dir}) — تعذّر تحديد مسار الدفع"

    add = _run_git(["add", git_rel_output], commit_dir)
    if add.returncode != 0:
        return False, f"git add فشل: {add.stderr.strip()[:200]}"
    diff = _run_git(["diff", "--cached", "--quiet"], commit_dir)
    if diff.returncode == 0:
        return True, "لا تغييرات جديدة (تخطي الدفع)"
    commit = _run_git(["commit", "-m", message], commit_dir)
    if commit.returncode != 0:
        return False, f"git commit فشل: {commit.stderr.strip()[:200]}"

    # [تصحيح حرج ٤] نلتقط أسماء الملفات التي غيّرها التزامنا المحلي تحديدًا
    # — الآن، قبل أي reset — لاستخدامها لاحقًا بدل "git add <مجلد الإخراج
    # كامل>" الشامل بعد أي reset. السبب: "git reset origin/<branch>" ينقل
    # الفهرس (index) ليطابق أحدث نسخة بعيدة لكنه لا يمس قرص هذه التشغيلة
    # إطلاقًا. لو تشغيلة أخرى منفصلة (نسخة GitHub Actions runner مختلفة)
    # دفعت بنجاح ملفات جديدة (مثل runs/run-<معرّف آخر>.json، أو صور فصل
    # مانهوا أخرى) بين محاولتي دفع هذه التشغيلة، فسيحتوي الفهرس بعد reset
    # على تلك الملفات، لكنها غائبة تمامًا عن قرص هذه التشغيلة (كل تشغيلة
    # لها worktree مستقل خاص بها من الصفر). "git add <مجلد>" (منذ git 2.0
    # يشمل رصد الحذف ضمنيًا) كان حينها يعتبرها "محذوفة" ويُدرجها بنفس
    # الـcommit التالي — فيُدفَع حذفها فعليًا، ماحيًا نتيجة تشغيلة أخرى
    # ناجحة تمامًا بصمت. تقييد "git add" على قائمة الملفات المحددة التي
    # هذه التشغيلة كتبتها فعليًا يمنع هذا السيناريو جذريًا: أي ملف لم
    # تكتبه هذه التشغيلة لن يُلمَس إطلاقًا مهما حدث بالفهرس بعد أي reset.
    changed_result = _run_git(["diff", "--name-only", "HEAD~1", "HEAD"], commit_dir)
    changed_files = [p.strip() for p in changed_result.stdout.splitlines() if p.strip()]
    if not changed_files:
        # احتياط نادر: لو تعذّر تحديد القائمة لأي سبب، نعود للسلوك القديم
        # (مجلد الإخراج كامل) بدل تعطيل الدفع كليًا.
        changed_files = [git_rel_output]

    for attempt in range(1, max_attempts + 1):
        push = _run_git(["push", "origin", f"HEAD:{branch}"], commit_dir)
        if push.returncode == 0:
            return True, "تم الدفع"
        _run_git(["fetch", "origin", branch], commit_dir)
        _run_git(["reset", f"origin/{branch}"], commit_dir)
        _run_git(["add", "--"] + changed_files, commit_dir)
        diff2 = _run_git(["diff", "--cached", "--quiet"], commit_dir)
        if diff2.returncode == 0:
            return True, "أصبحت التغييرات مطابقة لأحدث نسخة على البعيد أصلًا"
        _run_git(["commit", "-m", message], commit_dir)
        time.sleep(attempt * 2)
    return False, "فشل الدفع بعد عدة محاولات (سيُعالجه الدفع الاحتياطي النهائي بالـ workflow إن وُجد)"


async def push_now(message: str) -> None:
    if not ENABLE_INCREMENTAL_PUSH or not GIT_COMMIT_DIR:
        return
    ok, msg = await asyncio.to_thread(_commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, message)
    print(f"  {'✅' if ok else '⚠️'} دفع: {msg}")


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
            compressed = compress_image(raw, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
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
                    compressed = compress_image(raw, MAX_WIDTH, QUALITY)
                    filename = f"{i:03d}.webp"
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


# ============================== وضع التشخيص (موسّع) ==============================

def _static_probe_sync(url: str) -> dict:
    result = {
        "status_code": None, "headers_of_interest": {}, "challenge_detected": False,
        "protection_signatures": [], "images_via_noscript": 0, "images_via_data_attr": 0,
        "images_via_plain_src": 0, "extracted_image_count": 0, "extracted_sample_urls": [],
        "sample_image_urls": [], "signed_url_params": [], "raw_cookies_received": [], "error": None,
    }
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    try:
        resp = _HTTP_SESSION.get(url, headers=headers, timeout=20)
        result["status_code"] = resp.status_code
        # ترويسات موسّعة: مؤشرات مباشرة لمزوّدي حماية معروفين تحديدًا
        for h in ("server", "cf-ray", "cf-mitigated", "cf-cache-status", "content-type",
                   "set-cookie", "retry-after", "x-sucuri-id", "x-datadome", "x-iinfo"):
            if h in resp.headers:
                result["headers_of_interest"][h] = resp.headers[h][:150]
        result["raw_cookies_received"] = list(resp.cookies.keys())
        html = resp.text
    except Exception as e:
        result["error"] = f"{e}"
        return result

    result["challenge_detected"] = _looks_like_challenge_html(html)
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
    no_ref_ok, no_ref_size, no_ref_reason = await asyncio.to_thread(
        _fetch_image_probe_variant_sync, sample_url, None
    )
    ref_ok, ref_size, ref_reason = await asyncio.to_thread(
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
    blocked = any(isinstance(s, int) and s in (429, 403) for s in statuses)
    return {
        "target": "image_cdn", "sample_url": img_url, "requests_sent": n,
        "elapsed_sec": elapsed, "status_codes": statuses,
        "rate_limited_detected": blocked, "retry_after_header": retry_after,
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
    blocked = any(isinstance(s, int) and s in (429, 403) for s in statuses)
    return {
        "target": "page_url", "sample_url": url, "requests_sent": n, "elapsed_sec": elapsed,
        "status_codes": statuses, "rate_limited_detected": blocked, "retry_after_header": retry_after,
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
        }
    except Exception as e:
        return {"tested": True, "success": False, "error": str(e), "cookie_count_reused": len(cookies)}


def _fetch_image_probe_variant_sync(img_url: str, referer: str | None) -> tuple[bool, int, str | None]:
    """[إصلاح منطقي ب] محاولة تحميل وحيدة بلا إعادة محاولة (فحص تشخيصي، لا
    إنتاج) — مع Referer أو بدونه، بلا كوكيز دائمًا (_HTTP_SESSION مضبوطة
    على رفض تخزين أي كوكيز واردة). تُستخدم لعزل هل الحماية Referer فقط
    (شائع وسهل التعامل معه بـrequests عادي) أم تحتاج جلسة متصفح كاملة."""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        resp = _HTTP_SESSION.get(img_url, headers=headers, timeout=20)
        ctype = resp.headers.get("content-type", "")
        size = len(resp.content) if resp.content else 0
        if resp.ok and (ctype.startswith("image/") or ctype == ""):
            if resp.content and size >= 500:
                valid, why = _validate_image_bytes(resp.content)
                return valid, size, (None if valid else why)
            return False, size, f"جسم الاستجابة فارغ/صغير جدًا ({size} بايت)"
        return False, size, f"status={resp.status_code} content-type={ctype!r}"
    except Exception as e:
        return False, 0, f"استثناء: {e}"


async def _browser_probe(browser, url: str, diag_dir: Path, slug: str) -> dict:
    result = {
        "navigated": False, "title": None, "challenge_detected": False,
        "challenge_resolved_after_reload": None, "protection_signatures": [],
        "images_at_t0": None, "images_after_wait": None, "images_after_scroll": None,
        "selector_match_counts": {}, "unmatched_img_count": 0, "widget_excluded_count": 0,
        "widget_excluded_samples": [], "suggested_selectors": [], "domain_distribution": {},
        "signed_url_params": [], "screenshot_path": None, "hotlink_probe": None,
        "hotlink_probes": [], "network_vendor_hits": {},
        "adblock_wall": None, "cookie_reuse_probe": None, "error": None,
    }

    context = await browser.new_context(
        user_agent=UA, viewport={"width": 1280, "height": 1000}, locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = await context.new_page()

    # رصد طلبات الشبكة الفعلية أثناء تحميل الصفحة مقابل نطاقات مزوّدي حماية
    # معروفين — دليل مباشر أدق من مطابقة النص وحدها (يلتقط أيضًا سكربتات
    # تُحمَّل بصمت بدون أي أثر نصي ظاهر بالصفحة النهائية)
    vendor_hits: dict[str, set] = {}

    def _on_request(request):
        url_l = request.url.lower()
        for vendor, patterns in PROTECTION_VENDOR_NETWORK_PATTERNS.items():
            if any(p in url_l for p in patterns):
                vendor_hits.setdefault(vendor, set()).add(request.url[:160])

    page.on("request", _on_request)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        result["navigated"] = True
    except Exception as e:
        result["error"] = f"فشل التحميل الأولي (domcontentloaded): {e}"

    try:
        result["title"] = await page.title()
    except Exception:
        pass

    result["challenge_detected"] = await looks_like_challenge_page(page)
    if result["challenge_detected"]:
        await page.wait_for_timeout(5000)
        try:
            await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
            # [إصلاح منطقي أ] فحص ثانٍ فعلي بعد الreload بدل افتراض الحل
            # التلقائي، + إعادة التقاط العنوان (كان يُحفَظ سابقًا من *قبل*
            # الreload، فلو صار تحدٍّ يبقى عنوان صفحة التحقق بالتقرير النهائي
            # لا العنوان الحقيقي بعد ما تحل).
            still_challenge = await looks_like_challenge_page(page)
            result["challenge_resolved_after_reload"] = not still_challenge
            try:
                result["title"] = await page.title()
            except Exception:
                pass
        except Exception as e:
            print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")
            result["challenge_resolved_after_reload"] = False

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
    result["images_after_wait"] = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)

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
    snapshot_items = await snapshot_images(page, CONTENT_SELECTORS)
    result["content_images_before_scroll"] = len(snapshot_items)

    scrolled_items = await collect_images_while_scrolling(page, CONTENT_SELECTORS)
    result["images_after_scroll"] = len(scrolled_items)

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
    result["widget_excluded_samples"] = [
        it["ctx"].strip()[:80] for it in scrolled_items
        if WIDGET_CONTEXT_PATTERN.search(it.get("ctx", ""))
    ][:3]

    domains = Counter(urlparse(it["url"]).hostname for it in scrolled_items if it.get("url"))
    result["domain_distribution"] = dict(domains.most_common(5))

    result["signed_url_params"] = _detect_signed_url_params(
        [it["url"] for it in scrolled_items if it.get("url")]
    )

    # [إصلاح منطقي ب + معلومة مفقودة "عدة صور عيّنة"] حتى 3 عيّنات موزّعة
    # (أولى/وسط/أخيرة) بدل واحدة فقط — كل واحدة تخضع للعزل الثلاثي الكامل.
    sample_urls = _pick_sample_urls(scrolled_items, url, n=3)
    for s_url in sample_urls:
        result["hotlink_probes"].append(await _hotlink_probe_one(context, s_url, url))
    if result["hotlink_probes"]:
        result["hotlink_probe"] = result["hotlink_probes"][0]  # توافق خلفي (عينة أولى)

    # اختبار إعادة استخدام كوكيز الجلسة بطلب HTTP عادي — بعد كل ما سبق (حتى
    # يشمل أي كوكيز نتجت عن تجاوز جدار/تحدٍّ)
    result["cookie_reuse_probe"] = await _cookie_reuse_probe(context, url)

    page.remove_listener("request", _on_request)
    result["network_vendor_hits"] = {k: sorted(v)[:3] for k, v in vendor_hits.items()}

    await context.close()
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
            diffs.append(f"{label}: الأول={va!r} الثاني={vb!r}")
    hp_a = (a.get("hotlink_probes") or [{}])[0]
    hp_b = (b.get("hotlink_probes") or [{}])[0]
    if hp_a.get("referer_only_sufficient") != hp_b.get("referer_only_sufficient"):
        diffs.append(
            f"كفاية Referer وحده: الأول={hp_a.get('referer_only_sufficient')!r} الثاني={hp_b.get('referer_only_sufficient')!r}"
        )
    return diffs


def _recommend_profile(static_r: dict, browser_r: dict, rate_limit_r: dict | None = None, consistency_diffs: list[str] | None = None) -> dict:
    reasons = []
    fetch_mode = "browser"

    static_total = static_r.get("extracted_image_count", 0)
    hp = browser_r.get("hotlink_probe")

    if static_total >= 3 and not static_r.get("challenge_detected") and hp and hp["direct_http_success"]:
        fetch_mode = "http"
        reasons.append(f"مسار HTTP المباشر الفعلي (extract_images_from_html) سيستخرج {static_total} صورة فعليًا، بلا صفحة تحقق، ونجح تحميل صورة عينة بطلب مباشر بلا جلسة")
    else:
        if static_r.get("challenge_detected"):
            sigs = static_r.get("protection_signatures") or browser_r.get("protection_signatures") or []
            sig_txt = f" ({', '.join(sigs)})" if sigs else ""
            reasons.append(f"صفحة تحقق/حماية ظهرت حتى بالطلب الثابت{sig_txt} — يحتاج متصفحًا حقيقيًا على الأقل")
        if static_total < 3:
            reasons.append(f"مسار HTTP المباشر الفعلي سيستخرج {static_total} صورة فقط — غير كافٍ (الصور على الأغلب تُحقَن بجافاسكربت بعد التحميل)")
        if hp and not hp["direct_http_success"] and hp["browser_session_success"]:
            reasons.append("صورة العينة رفضت التحميل المباشر بدون جلسة، ونجحت فقط عبر جلسة متصفح — حماية سرقة (hotlink) حقيقية")

    if hp and hp.get("referer_only_sufficient"):
        reasons.append(
            "💡 عزل الحماية: صورة العينة رفضت التحميل بلا Referer، ونجحت بمجرد إرسال Referer صحيح "
            "بلا أي جلسة/كوكيز — الحماية Referer فقط، ويمكن التعامل معها بطلب HTTP عادي (requests) بلا متصفح"
        )

    hotlink_probes = browser_r.get("hotlink_probes") or []
    if len({p["direct_http_success"] for p in hotlink_probes}) > 1:
        reasons.append(
            "⚠️ نتيجة فحص hotlink تذبذبت بين عيّنات مختلفة (أولى/وسط/أخيرة) — "
            "التوصية أعلاه مبنية على العيّنة الأولى فقط، يُنصَح بمراجعة التقرير التفصيلي قبل الاعتماد"
        )

    signed_params = list(set((static_r.get("signed_url_params") or []) + (browser_r.get("signed_url_params") or [])))
    if signed_params:
        reasons.append(
            f"🔑 روابط الصور تحمل معاملات توقيع/انتهاء صلاحية ({', '.join(signed_params)}) — "
            "أي استراتيجية 'استخرج الروابط الآن وحمّلها لاحقًا' (تأخير، إعادة محاولة متأخرة) قد تفشل "
            "لأن الرابط ينتهي؛ يُفضَّل التحميل فور الاستخراج مباشرة"
        )

    if consistency_diffs:
        reasons.append(
            "🎲 فحص مزدوج (جلستان نظيفتان منفصلتان) أظهر تذبذبًا: " + " | ".join(consistency_diffs) +
            " — الحماية غالبًا احتمالية لا ثابتة؛ التوصية أعلاه مبنية على التكرار الأول فقط، "
            "يُفضَّل تشغيل التشخيص أكثر من مرة قبل الاعتماد النهائي"
        )

    cr = browser_r.get("cookie_reuse_probe") or {}
    if fetch_mode == "browser" and cr.get("tested") and cr.get("success"):
        reasons.append(
            "⭐ اكتشاف مهم: إعادة استخدام كوكيز جلسة المتصفح نجحت بطلب HTTP عادي لاحقًا — "
            "استراتيجية هجينة (حل التحدي مرة واحدة بمتصفح، ثم HTTP سريع لبقية الفصول) ممكنة "
            "نظريًا هنا، رغم أن fetch_mode='browser' هو الخيار الآمن المتاح حاليًا بالكود"
        )

    aw = browser_r.get("adblock_wall") or {}
    if aw.get("detected"):
        wait_txt = f"{aw.get('became_ready_after_sec')}ث" if aw.get("became_ready_after_sec") is not None else "غير محدد"
        reasons.append(f"جدار مانع إعلانات مكتشَف — استغرق زر التجاوز {wait_txt} ليصبح جاهزًا فعليًا")

    # [إصلاح] المقارنة الصحيحة لقرار do_scroll: صور مطابقة لمحددات المحتوى
    # *قبل* التمرير مقابل بعده — لا العدّ الخام شبه الصفري عند t0 (انظر
    # التعليق في _browser_probe). توافق خلفي: لو الحقل الجديد غير متوفر
    # (نتيجة قديمة محفوظة)، نرجع للمقياس القديم بدل الانهيار.
    before_scroll = browser_r.get("content_images_before_scroll")
    if before_scroll is None:
        before_scroll = browser_r.get("images_at_t0") or 0
    after_scroll = browser_r.get("images_after_scroll") or 0
    do_scroll = after_scroll > max(3, int(before_scroll * 1.15))
    do_widget_filter = (browser_r.get("widget_excluded_count") or 0) > 0

    # [إصلاح] ربط فحص تحديد المعدل (⑤) فعليًا بالتوصية النهائية — كان يُطبَع
    # منفصلًا فقط رغم أن التوثيق يَعِد بأنه "يفيد تحديد HTTP_CONCURRENCY الآمن".
    rl = rate_limit_r or {}
    rl_target_txt = "CDN الصور" if rl.get("target") == "image_cdn" else "رابط الصفحة (احتياطي)"
    if rl.get("rate_limited_detected"):
        suggested_http_concurrency = 1
        reasons.append(
            f"⚠️ تحديد معدل مكتشَف فعليًا على {rl_target_txt} (حالات: {rl.get('status_codes')}) — "
            f"يُنصَح بـHTTP_CONCURRENCY=1 لهذا الموقع تحديدًا بدل الافتراضي"
        )
    else:
        suggested_http_concurrency = 3
        reasons.append(f"لا تحديد معدل ظاهر في فحص موازٍ سريع (4 طلبات على {rl_target_txt}) — HTTP_CONCURRENCY=3 الافتراضي معقول كبداية")

    return {
        "fetch_mode": fetch_mode, "do_scroll": do_scroll, "do_widget_filter": do_widget_filter,
        "suggested_http_concurrency": suggested_http_concurrency, "reasons": reasons,
    }


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
        print(f"   صفحة تحقق/حماية مكتشفة: {'نعم ⚠️' if static_r['challenge_detected'] else 'لا'}")
        if static_r["protection_signatures"]:
            print(f"   🛡️ مزوّد الحماية المُصنَّف: {', '.join(static_r['protection_signatures'])}")
        print(f"   صور عبر noscript: {static_r['images_via_noscript']} | عبر data-src: {static_r['images_via_data_attr']} | عبر src عادي: {static_r['images_via_plain_src']}")
        print(f"   📌 العدد الذي سيُستخرَج فعليًا بمسار HTTP المباشر (نفس منطق الإنتاج): {static_r['extracted_image_count']}")
        if static_r["sample_image_urls"]:
            print("   عينة روابط صور من HTML الثابت:")
            for u in static_r["sample_image_urls"]:
                print(f"     - {u}")
        if static_r["signed_url_params"]:
            print(f"   🔑 روابط موقّعة/منتهية الصلاحية مكتشفة (معاملات: {static_r['signed_url_params']}) — "
                  f"'استخرج الآن حمّل لاحقًا' قد لا يكون آمنًا هنا")

    print("② فحص متصفح كامل (تحميل + جدار إعلانات + انتظار + تمرير تراكمي)...")
    browser_r = await _browser_probe(browser, url, diag_dir, slug)
    if browser_r["error"]:
        print(f"   ⚠️ {browser_r['error']}")
    print(f"   عنوان الصفحة: {browser_r['title']!r}")
    print(f"   صفحة تحقق/حماية مكتشفة عبر المتصفح: {'نعم ⚠️' if browser_r['challenge_detected'] else 'لا'}")
    if browser_r["challenge_resolved_after_reload"] is not None:
        print(f"   🔁 حالة التحدي بعد إعادة التحميل: {'✅ انحل تلقائيًا' if browser_r['challenge_resolved_after_reload'] else '⚠️ ما زال عالقًا'}")
    if browser_r["protection_signatures"]:
        print(f"   🛡️ مزوّد الحماية المُصنَّف (متصفح): {', '.join(browser_r['protection_signatures'])}")
    if browser_r["network_vendor_hits"]:
        print("   🌐 طلبات شبكة مطابقة لمزوّدي حماية معروفين (دليل مباشر):")
        for vendor, samples in browser_r["network_vendor_hits"].items():
            print(f"     - {vendor}: {samples}")
    aw = browser_r.get("adblock_wall") or {}
    if aw.get("detected"):
        status = "⏱️ لم يصبح جاهزًا خلال المهلة القصوى" if aw.get("timed_out") else f"جاهز بعد {aw.get('became_ready_after_sec')}ث"
        print(f"   🧱 جدار مانع إعلانات مكتشَف — {status} — تم الضغط: {'نعم' if aw.get('clicked') else 'لا'}")
    print(f"   منحنى نمو عدد الصور — أول لحظة: {browser_r['images_at_t0']} → بعد الانتظار: {browser_r['images_after_wait']} → بعد التمرير: {browser_r['images_after_scroll']}")
    print(f"   مطابقة المحددات الحالية: {browser_r['selector_match_counts']}")
    print(f"   صور لا تطابق أي محدد معروف: {browser_r['unmatched_img_count']}" +
          ("  ← يُرجَّح الحاجة لمحدد CSS جديد" if browser_r['unmatched_img_count'] else ""))
    if browser_r["suggested_selectors"]:
        print(f"   💡 محددات CSS مقترَحة (من الأنماط المتكررة بالصور غير المطابقة): {browser_r['suggested_selectors']}")
    if browser_r["widget_excluded_count"]:
        print(f"   🧹 فلتر الودجات استبعد {browser_r['widget_excluded_count']} صورة — عينات: {browser_r['widget_excluded_samples']}")
    else:
        print("   🧹 فلتر الودجات لم يستبعد أي صورة (قد يكون غير ضروري)")
    if browser_r["domain_distribution"]:
        print(f"   توزيع النطاقات: {browser_r['domain_distribution']}")
    if browser_r["signed_url_params"]:
        print(f"   🔑 روابط موقّعة/منتهية الصلاحية مكتشفة عبر المتصفح (معاملات: {browser_r['signed_url_params']})")

    print("②-تكرار إعادة فحص كامل بجلسة نظيفة ثانية (فحص اتساق/احتمالية الحماية)...")
    browser_r2 = await _browser_probe(browser, url, diag_dir, slug + "-run2")
    consistency_diffs = _diff_browser_probes(browser_r, browser_r2)
    if consistency_diffs:
        print("   🎲 تذبذب مكتشَف بين التكرارين (حماية غالبًا احتمالية):")
        for d in consistency_diffs:
            print(f"     - {d}")
    else:
        print("   ✅ النتيجة متطابقة بين التكرارين — لا تذبذب ظاهر ضمن هذا الفحص")

    hotlink_probes = browser_r.get("hotlink_probes") or []
    if hotlink_probes:
        print(f"③ فحص حماية السرقة (hotlink) على {len(hotlink_probes)} صورة عيّنة (أولى/وسط/أخيرة) — عزل ثلاثي لكل واحدة...")
        for i, hp in enumerate(hotlink_probes, start=1):
            print(f"   — عيّنة {i}: {hp['sample_url']}")
            no_ref_line = f"     بلا Referer وبلا كوكيز: {'✅ نجح' if hp['no_referer_success'] else '❌ فشل'} ({hp['no_referer_size']} بايت)"
            if not hp["no_referer_success"]:
                no_ref_line += f" — السبب: {hp['no_referer_fail_reason']}"
            print(no_ref_line)
            direct_line = f"     بReferer صحيح وبلا كوكيز: {'✅ نجح' if hp['direct_http_success'] else '❌ فشل'} ({hp['direct_http_size']} بايت)"
            if not hp["direct_http_success"]:
                direct_line += f" — السبب: {hp['direct_http_fail_reason']}"
            print(direct_line)
            session_line = f"     بجلسة متصفح كاملة: {'✅ نجح' if hp['browser_session_success'] else '❌ فشل'} ({hp['browser_session_size']} بايت)"
            if not hp["browser_session_success"]:
                session_line += f" — السبب: {hp['browser_session_fail_reason']}"
            print(session_line)
            if hp.get("referer_only_sufficient"):
                print("     💡 استنتاج: الحماية Referer فقط لهذي العيّنة")
        # [إصلاح منطقي متوقّع] هل النتيجة متسقة عبر العيّنات؟ عيّنة واحدة كانت
        # تخفي تذبذبًا محتملًا بين أول/وسط/آخر صورة بالفصل.
        modes = {hp["direct_http_success"] for hp in hotlink_probes}
        if len(modes) > 1:
            print("   ⚠️ تذبذب: نتيجة الحماية اختلفت بين العيّنات (بعضها نجح بReferer فقط وبعضها لا) — التوصية أدناه مبنية على العيّنة الأولى فقط")
    else:
        print("③ لم يتوفر رابط صورة عينة لفحص حماية السرقة")

    cr = browser_r.get("cookie_reuse_probe") or {}
    print("④ اختبار إعادة استخدام كوكيز الجلسة بطلب HTTP عادي...")
    if not cr.get("tested"):
        print(f"   لم يُختبَر: {cr.get('reason', '—')}")
    else:
        outcome = "✅ نجح — قد تصلح استراتيجية هجينة (حل مرة واحدة + HTTP لاحقًا)" if cr.get("success") else "❌ فشل — يحتاج متصفحًا لكل فصل"
        print(f"   {outcome} (status={cr.get('status_code')}, كوكيز مُعاد استخدامها: {cr.get('cookie_count_reused')})")

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
    print(f"   الحالات: {rl['status_codes']} خلال {rl['elapsed_sec']}ث — تحديد معدل مكتشَف: {'نعم ⚠️' if rl['rate_limited_detected'] else 'لا'}"
          + (f" — Retry-After: {rl['retry_after_header']}" if rl['retry_after_header'] else ""))

    if browser_r["screenshot_path"]:
        print(f"   🖼️ لقطة شاشة مرجعية محفوظة: {browser_r['screenshot_path']}")

    recommendation = _recommend_profile(static_r, browser_r, rl, consistency_diffs)
    print("⑥ التوصية المقترحة لبروفايل جديد:")
    print(f"   fetch_mode المقترح: {recommendation['fetch_mode']}")
    if recommendation["fetch_mode"] == "browser":
        print(f"   do_scroll المقترح: {recommendation['do_scroll']}")
        print(f"   do_widget_filter المقترح: {recommendation['do_widget_filter']}")
    if recommendation["fetch_mode"] == "http":
        print(f"   HTTP_CONCURRENCY المقترح لهذا الموقع: {recommendation['suggested_http_concurrency']}")
    for reason in recommendation["reasons"]:
        print(f"   • {reason}")
    print("   جاهز للصق داخل قاموس PROFILES:")
    if recommendation["fetch_mode"] == "http":
        print('   "اسم_الموقع": {"label": "...", "fetch_mode": "http"},')
    else:
        print(
            f'   "اسم_الموقع": {{"label": "...", "fetch_mode": "browser", '
            f'"do_scroll": {recommendation["do_scroll"]}, "do_widget_filter": {recommendation["do_widget_filter"]}}},'
        )

    # [معلومة مفقودة — تتبع تاريخي] مقارنة بآخر فحص محفوظ لنفس الموقع (بحسب
    # hostname) على فرع الإخراج، وحفظ لقطة جديدة بالتاريخ للفحوصات القادمة.
    first_hp = hotlink_probes[0] if hotlink_probes else {}
    current_snapshot = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "url": url,
        "fetch_mode_recommended": recommendation["fetch_mode"],
        "challenge_detected_static": static_r.get("challenge_detected"),
        "challenge_detected_browser": browser_r.get("challenge_detected"),
        "protection_signatures": sorted(set((static_r.get("protection_signatures") or []) + (browser_r.get("protection_signatures") or []))),
        "referer_only_sufficient": first_hp.get("referer_only_sufficient"),
        "rate_limited_detected": rl.get("rate_limited_detected"),
        "signed_url_params": sorted(set((static_r.get("signed_url_params") or []) + (browser_r.get("signed_url_params") or []))),
    }
    history = await asyncio.to_thread(_load_diagnostic_history_sync, site_slug)
    print("⑦ تتبّع تاريخي (مقارنة بآخر فحص محفوظ لهذا الموقع)...")
    history_diffs = []
    if history:
        history_diffs = _diff_diagnostic_snapshots(history[-1], current_snapshot)
        if history_diffs:
            print(f"   🚨 تغيّر سلوك الحماية منذ آخر فحص ({history[-1].get('date', '؟')}):")
            for d in history_diffs:
                print(f"     - {d}")
        else:
            print(f"   ✅ لا تغيّر ملحوظ منذ آخر فحص محفوظ ({history[-1].get('date', '؟')})")
    else:
        print("   ℹ️ لا يوجد فحص سابق محفوظ لهذا الموقع — هذه أول لقطة تاريخية")
    await asyncio.to_thread(_save_diagnostic_history_sync, site_slug, history + [current_snapshot])
    print("═" * 60)

    report = {
        "url": url, "tls_and_server_info": tls_info, "runner_network_info": runner_info,
        "static_probe": static_r, "browser_probe": browser_r, "browser_probe_second_run": browser_r2,
        "consistency_diffs": consistency_diffs, "rate_limit_probe": rl,
        "recommendation": recommendation, "history_diffs_since_last_run": history_diffs,
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

    if GIT_COMMIT_DIR:
        ok, msg = await asyncio.to_thread(
            _commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, "تقرير تشخيصي جديد + تحديث التتبع التاريخي"
        )
        print(f"{'✅' if ok else '⚠️'} دفع تقرير التشخيص: {msg}")

    print("\n" + "=" * 50)
    print(f"✅ اكتمل التشخيص لـ {len(reports)} رابط")
    print(f"📁 التقارير التفصيلية + لقطات الشاشة في: {diag_dir}")
    print("📎 كما تُرفَع نسخة كأرتيفاكت مستقل في صفحة التشغيلة على GitHub Actions")
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
                await push_now(f"إضافة {result['manga_id']} - الفصل {result['chapter_num']}")

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

    base_manifest = {"manga": {}}
    if GIT_COMMIT_DIR:
        remote = await asyncio.to_thread(_read_remote_manifest_sync, GIT_COMMIT_DIR, GIT_BRANCH)
        if remote:
            base_manifest = remote
    elif (OUTPUT_DIR / "manifest.json").exists():
        try:
            base_manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            print("  ⚠️ تعذّر قراءة manifest.json المحلي الحالي — سيُعاد بناؤه من نتائج هذه التشغيلة فقط")

    manifest = merge_manifest_dict(base_manifest, results)
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    run_manifest_path = OUTPUT_DIR / RUN_MANIFEST_RELPATH
    run_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    run_manifest_path.write_text(
        json.dumps(build_run_manifest(results), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if GIT_COMMIT_DIR:
        ok, msg = await asyncio.to_thread(_commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, "تحديث manifest.json ونتائج التشغيل")
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
