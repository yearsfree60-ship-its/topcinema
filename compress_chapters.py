#!/usr/bin/env python3
"""
يقرأ قائمة روابط فصول (سطر لكل رابط) من متغيرات البيئة، يفتح كل صفحة بمتصفح
Chromium حقيقي مؤتمت (Playwright) — هذا يمرّ تلقائيًا أغلب أنظمة التحميل الكسول
وبعض تحديات Cloudflare البسيطة (غير مضمون 100% مع الحماية المتقدمة) — يستخرج
روابط الصور، يحمّلها، يضغطها فعليًا بمكتبة Pillow، ويحفظها في مجلد الإخراج
مع ملف manifest.json يصف كل مانهوا وفصولها وروابط صورها النهائية.

ملاحظات تصميم مهمة (تراكمت من التشخيص الفعلي لمشاكل واجهناها):

1) لا يعتمد هذا السكربت على "networkidle" لاعتبار الصفحة جاهزة. كثير من مواقع
   المانجا (خصوصًا المدعومة بإعلانات) فيها طلبات شبكة دورية لا تتوقف أبدًا،
   فحالة "خمول الشبكة" لا تتحقق مطلقًا حتى لو اكتمل المحتوى فعليًا.

2) تحميل الصور نفسها يتم عبر Playwright (نفس جلسة المتصفح وكوكيزها وبصمتها)
   وليس عبر مكتبة requests منفصلة — لأن بعض المواقع ترفض تحميل الصور من
   خارج جلسة المتصفح الحقيقية (تسبّب خطأ "cannot identify image" رغم أن
   الرابط نفسه صحيح ويعمل داخل نفس متصفح Playwright الذي فتح الصفحة).

3) الاستخراج يجرّب أولًا محدّدات CSS معروفة لحاويات محتوى المانجا الحقيقي
   (Madara وما شابه) قبل اللجوء لكل وسوم <img> في الصفحة — لتفادي التقاط
   شعار الموقع أو الإعلانات أو صور مصغّرة لمانهوات أخرى في الشريط الجانبي.

3.1) [مُضاف] حتى ضمن نفس حاوية المحتوى (.reading-content مثلًا) قد يُحقن
   قالب الموقع ودجت ثابت (مثل "قد يعجبك أيضًا" / صور مانهوات مشابهة) بنفس
   وسوم <img> الحقيقية، دون أي إشارة في رابط الصورة نفسه تدل على أنه ودجت.
   لذلك أصبح الاستخراج الآن يفحص "سياق" كل صورة (أصولها/parents في الـDOM
   حتى 5 مستويات) ويستبعد أي صورة أصلها يحمل class/id يوحي بأنه قسم
   "مقترح/مشابه/تعليقات/إعلان" بدل الاعتماد فقط على نمط نصي في رابط الصورة.
   هذا اكتُشف لأن عدد الصور الفاشلة كان ثابتًا بدقة (6 صور) في كل فصل بغض
   النظر عن طول الفصل — وهو دليل حاسم على عنصر ثابت التكرار في القالب،
   وليس فشل شبكة عشوائيًا.

3.2) [مُضاف] اكتُشف لاحقًا أن الصور الست الثابتة في هذا الموقع تحديدًا ليست
   ودجت "مقترحات" بل شريط أيقونات تفاعل (إعجاب/حب/ضحك...) بصيغة SVG من
   /theme/emotes/svg/ — وهي ثابتة في كل صفحة بحكم قالب الموقع نفسه لا بحكم
   المحتوى. فشلها في الضغط ليس بسبب الشبكة أو الجلسة، بل لأن Pillow لا يدعم
   فك ترميز SVG أصلًا (تنسيق متجهي وليس نقطيًا) — فيرمي "cannot identify
   image file" حتى لو تم تحميل الملف بنجاح ومكتمل 100%. لذلك أصبح
   IGNORE_PATTERN يستبعد أي رابط بامتداد .svg أو داخل مسار /theme/ أو يحوي
   كلمة emote/reaction، قبل حتى محاولة تحميله.

4) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط، لأن حد WebP الصارم
   (16383 بكسل لأي بعد) قد يُتجاوز حتى لو كان العرض ضمن الحد المطلوب.

4.1) [مُضاف] رقم "الجودة" في WebP (0-100) ليس نسبة مئوية من الحجم النهائي —
   إنه مقياس جودة بصري داخلي لا يرتبط خطيًا بحجم الملف. صورة بسيطة (خطوط/
   ألوان مسطحة) قد تُضغَط أصلًا بكفاءة عالية فتبقى قريبة من حجمها الأصلي حتى
   بجودة منخفضة جدًا (لوحظ فعليًا: 172ك.ب ← 169ك.ب عند جودة 30). لذلك أصبح
   الوضع الافتراضي الآن "استهداف نسبة حجم حقيقية" (COMPRESSION_MODE=ratio):
   الرقم الذي يختاره المستخدم (مثلًا 30) يُفهَم كنسبة مئوية من حجم الصورة
   الأصلية، ويُبحث بالبحث الثنائي (binary search) عن قيمة جودة WebP تُنتج
   فعليًا حجمًا قريبًا من تلك النسبة لكل صورة على حدة. الوضع القديم (تمرير
   الرقم مباشرة كمعامل جودة WebP خام) لا يزال متاحًا عبر COMPRESSION_MODE=fixed
   لمن يفضّل التحكم اليدوي المباشر.

4.2) [مُضاف] بعض صور PNG المحوّلة تحمل قناة شفافية (alpha) غير مستخدمة
   فعليًا (كل البكسلات معتمة 100%) — هذه القناة تُبقي حجم WebP كبيرًا بغضّ
   النظر عن إعداد الجودة. يُكتشف هذا تلقائيًا (فحص أقصى وأدنى قيمة alpha)
   وتُحذف القناة إن كانت فارغة فعليًا، قبل الضغط.

5) الحكم بنجاح/فشل تحميل الصفحة يعتمد على وجود صور مستخرجة فعليًا، وليس على
   إطلاق حدث goto (domcontentloaded/load) بذاته. بعض الصفحات (خصوصًا الفصل
   الأول من مانهوا، حيث يوجد محتوى ترويجي إضافي) ترسم محتواها الحقيقي كاملًا
   ويظهر فيها عشرات الصور الحقيقية، لكن حدث goto يتعلّق ولا يُطلَق أبدًا بسبب
   مورد بطيء غير متعلق بالمحتوى (إعلان فيديو، سكربت تتبّع معلّق...). رفض
   النتيجة تلقائيًا في هذه الحالة كان يُهدر بيانات صحيحة مكتشفة فعليًا.

6) [مُضاف] عند فشل تحميل بايتات صورة، يُتحقق الآن من content-type فعليًا
   قبل تمريرها لـ Pillow، ويُطبع السبب الدقيق (status/content-type/الرابط
   الكامل) بدل الاكتفاء برسالة Pillow العامة "cannot identify image file"
   التي لا تفسّر شيئًا. هذا يجعل أي سبب فشل مستقبلي قابلًا للتشخيص فورًا
   من اللوج نفسه دون تخمين.

7) [مُضاف] دفع تدريجي (commit + push) لفرع Git بعد كل فصل ناجح، بدل انتظار
   اكتمال كل الفصول ثم الدفع دفعة واحدة في نهاية الـworkflow. هذا يحمي من
   فقدان كل النتائج عند بلوغ سقف وقت التشغيلة (timeout-minutes) أو إلغاء
   يدوي أو عطل مؤقت في الـRunner — فقط الفصل قيد المعالجة لحظة الانقطاع هو
   ما يُفقد، لا كل شيء. يُفعَّل هذا فقط إذا كان GIT_COMMIT_DIR مضبوطًا (من
   الـworkflow)؛ إن تُرك فارغًا يعمل السكربت كالسابق تمامًا (كتابة ملفات محليًا
   بدون أي عمليات Git) — مفيد للتشغيل المحلي أو الاختبار.

   كذلك، بما أن الدفع صار تدريجيًا عبر عدة "commits" منفصلة، أصبح الـmanifest
   يُحمَّل ويُدمَج بدل أن يُبنى من الصفر ويستبدل القديم بالكامل في كل تشغيلة
   (كما كان يحدث سابقًا، وهو ما كان يعني فقدان مانهوات/فصول من تشغيلات سابقة
   من ملف manifest.json رغم بقاء صورها على القرص فعليًا وبلا فائدة).
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

from PIL import Image
from io import BytesIO
from playwright.async_api import async_playwright

QUALITY = int(os.environ.get("IMG_QUALITY", "25"))
MAX_WIDTH = int(os.environ.get("IMG_MAX_WIDTH", "700"))

# [مُضاف] وضع الضغط: "ratio" (افتراضي) يعني أن IMG_QUALITY يُفهَم كنسبة مئوية
# حقيقية مستهدفة من حجم الصورة الأصلية (مثلًا 30 = ~30% من الحجم الأصلي)،
# ويُبحث تلقائيًا (binary search) عن جودة WebP التي تحقق ذلك فعليًا لكل صورة.
# "fixed" يعيد السلوك القديم: تمرير IMG_QUALITY مباشرة كمعامل جودة WebP خام
# (0-100) دون أي ربط فعلي بنسبة الحجم الناتج.
COMPRESSION_MODE = os.environ.get("COMPRESSION_MODE", "ratio").strip().lower()

# حدود البحث عن الجودة في وضع "ratio" — لا ننزل تحت MIN_QUALITY مهما بعُد
# الحجم الناتج عن الهدف (تفاديًا لتشويه بصري غير مقبول)، ولا نرفع فوق
# MAX_QUALITY_SEARCH (لا فائدة من جودة قريبة من 100 في صور مانهوا مضغوطة أصلًا)
MIN_QUALITY = int(os.environ.get("IMG_MIN_QUALITY", "8"))
MAX_QUALITY_SEARCH = int(os.environ.get("IMG_MAX_QUALITY_SEARCH", "95"))
RATIO_SEARCH_ITERS = int(os.environ.get("IMG_RATIO_SEARCH_ITERS", "7"))
CHAPTER_URLS_RAW = os.environ.get("CHAPTER_URLS", "")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
CDN_BASE = os.environ.get("CDN_BASE", "")

# [مُضاف] إعدادات الدفع التدريجي لـGit. GIT_COMMIT_DIR هو جذر الـworktree
# الذي يتتبّع فرع الإخراج (output) — إذا تُرك فارغًا يبقى السكربت يعمل محليًا
# فقط بلا أي عمليات Git، تمامًا كالسابق (وضع آمن للتشغيل المحلي/الاختبار).
GIT_COMMIT_DIR = os.environ.get("GIT_COMMIT_DIR", "").strip()
GIT_BRANCH = os.environ.get("GIT_BRANCH", "output")
GIT_PUSH_RETRIES = int(os.environ.get("GIT_PUSH_RETRIES", "5"))
GIT_USER_NAME = os.environ.get("GIT_USER_NAME", "manhwa-bot")
GIT_USER_EMAIL = os.environ.get("GIT_USER_EMAIL", "bot@users.noreply.github.com")

NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))
CONTENT_WAIT_MS = int(os.environ.get("CONTENT_WAIT_MS", "20000"))
CONTENT_POLL_MS = int(os.environ.get("CONTENT_POLL_MS", "800"))
RETRY_PER_CHAPTER = int(os.environ.get("RETRY_PER_CHAPTER", "2"))

# [مُضاف] ميزانية زمنية للانتظار الفعلي حتى تُحل صفحة تحقق Cloudflare (أو ما
# شابه) — بدل انتظار ثابت 5 ثوانٍ + إعادة تحميل مرة واحدة فقط. التحديات
# الحقيقية (JS Challenge/Turnstile) قد تحتاج حتى 30-45 ثانية، خصوصًا من
# عناوين IP مصنّفة كمراكز بيانات (وهذا حال أغلب بيئات CI مثل GitHub Actions).
CHALLENGE_MAX_WAIT_MS = int(os.environ.get("CHALLENGE_MAX_WAIT_MS", "45000"))
CHALLENGE_POLL_MS = int(os.environ.get("CHALLENGE_POLL_MS", "3000"))

# [مُضاف] مجلد لحفظ حالة الجلسة (كوكيز التحقق مثل cf_clearance) لكل نطاق على
# حدة، بحيث لو نجحنا في تجاوز الحماية لفصل واحد، تُستخدم نفس الكوكيز للفصول
# التالية من نفس الموقع بدل إعادة اختبار الحماية من الصفر في كل فصل — كان
# هذا الشكل السابق (context جديد تمامًا لكل فصل) يهدر أي مصادقة سابقة.
STORAGE_STATE_DIR = Path(os.environ.get("STORAGE_STATE_DIR", ".storage_state"))

# إذا فُعِّل هذا (STRICT_DOMAIN_FILTER=1) يتم استبعاد أي صورة من نطاق (domain)
# غير النطاق الأغلب بين صور الفصل — بعض المواقع تحمّل ودجات التوصيات من
# نطاق خارجي (شبكة إعلانات/خدمة توصيات) مختلف عن نطاق CDN صور المانهوا نفسه.
# مُعطَّل افتراضيًا لأن بعض المواقع الشرعية توزّع صورها على أكثر من نطاق CDN.
STRICT_DOMAIN_FILTER = os.environ.get("STRICT_DOMAIN_FILTER", "0") == "1"

# أقصى بعد مسموح لأي صورة (عرض أو طول) قبل إعادة تحجيمه إجباريًا — يحمي من
# فشل ترميز WebP الذي له حد صارم 16383 بكسل، بغضّ النظر عن إعداد العرض الأقصى
WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(
    r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad|"
    r"emote|reaction|/theme/|\.svg(?:\?|$)",
    re.I,
)

# [مُضاف] أنماط أسماء classes/ids شائعة لحاويات "ودجات" غير محتوى القراءة
# الفعلي — مقترحات/مانهوات مشابهة/تعليقات/إعلانات/كاروسيل إلخ. يُفحص بها
# سياق (أصول DOM) كل صورة بغضّ النظر عن مدى بُعدها عن المحدّد الرئيسي.
WIDGET_CONTEXT_PATTERN = re.compile(
    r"related|similar|recommend|suggest|you-may|you_may|might-like|"
    r"widget|sidebar|comment|carousel|swiper|sponsor|advert|banner-ad|"
    r"next-chap|prev-chap|also-read|readers-also|trending|popular-manga",
    re.I,
)

# محدّدات CSS شائعة لحاويات صفحات المانجا الحقيقية (Madara وما شابه من قوالب
# ووردبريس) — تُجرَّب أولًا لتضييق الاستخراج على المحتوى الحقيقي فقط
CONTENT_SELECTORS = [
    ".reading-content img",
    ".page-break img",
    ".text-left img",
    "#readerarea img",
    ".chapter-content img",
]

CHALLENGE_MARKERS = [
    "just a moment", "checking your browser", "attention required",
    "cf-browser-verification", "ddos protection by", "verifying you are human",
    "enable javascript and cookies",
]

# [مُعدَّل] يعيد الآن لكل عنصر <img> كائنًا يحوي رابطه + نص "سياقه" (classes
# وids لخمسة مستويات من الأصول في الـDOM) بدل رابط مجرّد فقط — هذا ما يمكّن
# فلترة الودجات لاحقًا بالاعتماد على بنية الصفحة الفعلية لا على تخمين نصي.
IMG_SRC_WITH_CONTEXT_JS = """els => els.map(e => {
    const u = e.getAttribute('data-src') || e.getAttribute('data-lazy-src')
        || e.getAttribute('data-original') || e.currentSrc || e.src;
    let anc = e, depth = 0, ctx = '';
    while (anc && depth < 5) {
        ctx += ' ' + (anc.className && anc.className.toString ? anc.className.toString() : '')
             + ' ' + (anc.id || '');
        anc = anc.parentElement;
        depth++;
    }
    return {url: u, ctx: ctx.toLowerCase()};
}).filter(x => x.url)"""


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF]+", "-", text).strip("-").lower()
    return text or "chapter"


def manga_slug_from_url(url: str) -> tuple[str, str]:
    """يحاول استخراج (اسم_مانهوا_تقريبي, رقم_الفصل) من بنية الرابط الشائعة."""
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


async def looks_like_challenge_page(page) -> bool:
    try:
        title = (await page.title() or "").lower()
        body_text = ""
        if await page.query_selector("body"):
            body_text = (await page.inner_text("body"))[:800].lower()
    except Exception:
        return False
    combined = f"{title} {body_text}"
    return any(marker in combined for marker in CHALLENGE_MARKERS)


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


def dedupe(urls: list[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen and not IGNORE_PATTERN.search(u):
            seen.add(u)
            out.append(u)
    return out


def _filter_widget_context(items: list[dict], base_url: str) -> list[str]:
    """
    [مُضاف] يستبعد أي صورة يحمل أحد أصولها في الـDOM (حتى 5 مستويات) اسم
    class/id يطابق WIDGET_CONTEXT_PATTERN، ثم يطبّق فلترة النطاق الاختيارية
    (STRICT_DOMAIN_FILTER) ثم dedupe المعتاد. يطبع عدد الصور المستبعدة
    بسبب الودجت ليكون التشخيص واضحًا في اللوج مباشرة.
    """
    kept, excluded_widget = [], 0
    for item in items:
        u = item.get("url")
        ctx = item.get("ctx", "")
        if not u or u.startswith("data:"):
            continue
        if WIDGET_CONTEXT_PATTERN.search(ctx):
            excluded_widget += 1
            continue
        kept.append(urljoin(base_url, u))

    if excluded_widget:
        print(f"  🧹 استُبعدت {excluded_widget} صورة بسبب سياق ودجت (مقترح/مشابه/إعلان...)")

    kept = dedupe(kept)

    if STRICT_DOMAIN_FILTER and len(kept) >= 4:
        domains = [urlparse(u).hostname for u in kept]
        majority_domain, _ = Counter(domains).most_common(1)[0]
        before = len(kept)
        kept = [u for u in kept if urlparse(u).hostname == majority_domain]
        if len(kept) != before:
            print(f"  🌐 استُبعدت {before - len(kept)} صورة من نطاق مختلف عن {majority_domain}")

    return kept


async def extract_image_urls(page, base_url: str) -> list[str]:
    # 0) أولوية قصوى: محدّدات محتوى معروفة — تستبعد الشعار/الإعلانات تلقائيًا.
    #    الآن نستخدم النسخة الواعية بالسياق (مع ctx) لفلترة أي ودجت مُحقَن
    #    داخل نفس الحاوية (كما اكتُشف: عدد ثابت 6 صور في كل فصل بغض النظر
    #    عن طوله — دليل قاطع على ودجت قالب ثابت لا فشل شبكة عشوائي).
    for selector in CONTENT_SELECTORS:
        try:
            items = await page.eval_on_selector_all(selector, IMG_SRC_WITH_CONTEXT_JS)
        except Exception:
            items = []
        found = _filter_widget_context(items, base_url)
        if len(found) >= 3:
            return found

    # 1) صور داخل noscript (بديل حقيقي شائع عند التحميل الكسول)
    noscript_imgs = await page.eval_on_selector_all("noscript", "els => els.map(e => e.innerHTML)")
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    # 2) كل وسوم <img> في الصفحة (احتياط أخير، عرضة لالتقاط شعار/إعلانات)
    #    نستخدم أيضًا النسخة الواعية بالسياق هنا لأنها أوسع نطاقًا وأكثر
    #    عرضة لالتقاط ودجات، لا فقط الشعار/الإعلانات المغطاة بـIGNORE_PATTERN.
    items = await page.eval_on_selector_all("img", IMG_SRC_WITH_CONTEXT_JS)
    found = _filter_widget_context(items, base_url)
    if found:
        return found

    # 3) احتياط نهائي: أي رابط بامتداد صورة داخل كود الصفحة الكامل
    html = await page.content()
    found = [urljoin(base_url, m.group(0)) for m in
             re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(found)


def _drop_unused_alpha(img: Image.Image) -> Image.Image:
    """
    [مُضاف] يحذف قناة الشفافية إن كانت غير مستخدمة فعليًا (كل البكسلات
    معتمة 100%) — قناة alpha فارغة تُبقي حجم WebP كبيرًا بغضّ النظر عن
    إعداد الجودة، وهي شائعة في صور PNG محوّلة آليًا من مصادر مختلفة.
    """
    if img.mode in ("RGBA", "LA"):
        try:
            alpha = img.getchannel("A")
            lo, hi = alpha.getextrema()
            if lo == 255 and hi == 255:
                img = img.convert("RGB") if img.mode == "RGBA" else img.convert("L")
        except Exception:
            pass
    return img


def _resize_for_limits(img: Image.Image, max_width: int) -> Image.Image:
    # نتحقق من العرض والطول معًا: صورة ضيقة لكن طويلة جدًا (أو العكس) تتجاوز
    # حد WebP الصارم (16383 بكسل) حتى لو عرضها ضمن الحد المطلوب أصلًا
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
    return img


def _encode_webp(img: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def _compress_to_target_ratio(img: Image.Image, original_size: int, ratio_percent: int):
    """
    [مُضاف] هذا هو قلب "التحكم الحقيقي": بدل تمرير الرقم كمعامل WebP خام،
    نبحث فعليًا (بحث ثنائي) عن جودة WebP التي تُنتج حجمًا قريبًا من
    (ratio_percent% من الحجم الأصلي) — لأن العلاقة بين رقم الجودة وحجم
    الملف الناتج ليست خطية ولا موحّدة بين الصور (تعتمد على تعقيد المحتوى).

    يعيد (bytes, جودة_مستخدمة, تم_بلوغ_الحد_الأدنى_دون_تحقيق_الهدف: bool)
    """
    target_size = max(1024, int(original_size * (ratio_percent / 100.0)))

    # فحص سريع: حتى بأعلى جودة بحث، هل الحجم أصلًا أصغر من أو يساوي الهدف؟
    # (يحدث لصور صغيرة/بسيطة أصلًا) — لا داعي لأي بحث إضافي، نأخذ أفضل جودة
    data_hi = _encode_webp(img, MAX_QUALITY_SEARCH)
    if len(data_hi) <= target_size:
        return data_hi, MAX_QUALITY_SEARCH, False

    # فحص الحد الأدنى: إذا حتى أدنى جودة مسموحة لا تصل للهدف (صورة معقدة
    # جدًا أو هدف صغير جدًا)، نقبل بأدنى جودة كأفضل ما يمكن ونُبلّغ بذلك
    data_lo = _encode_webp(img, MIN_QUALITY)
    if len(data_lo) >= target_size:
        return data_lo, MIN_QUALITY, True

    # بحث ثنائي بين lo و hi عن أقرب جودة تُنتج حجمًا قريبًا من الهدف
    lo, hi = MIN_QUALITY, MAX_QUALITY_SEARCH
    best_bytes, best_q, best_diff = data_lo, MIN_QUALITY, abs(len(data_lo) - target_size)
    for _ in range(RATIO_SEARCH_ITERS):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        data_mid = _encode_webp(img, mid)
        diff = abs(len(data_mid) - target_size)
        if diff < best_diff:
            best_bytes, best_q, best_diff = data_mid, mid, diff
        if len(data_mid) > target_size:
            hi = mid
        else:
            lo = mid
    return best_bytes, best_q, False


def compress_image(raw_bytes: bytes, max_width: int, quality: int):
    """
    [مُعدَّل] يعيد الآن (bytes, جودة_مستخدمة, ملاحظة|None) بدل bytes فقط.
    في وضع COMPRESSION_MODE=ratio (الافتراضي): quality تُفهَم كنسبة مئوية
    حقيقية مستهدفة من الحجم الأصلي، ويُبحث تلقائيًا عن جودة WebP تحققها.
    في وضع COMPRESSION_MODE=fixed: السلوك القديم — quality تُمرَّر مباشرة
    كمعامل WebP خام دون أي استهداف لحجم فعلي.
    """
    img = Image.open(BytesIO(raw_bytes))
    img = img.convert("RGB") if img.mode in ("P", "CMYK") else img
    img = _drop_unused_alpha(img)
    img = _resize_for_limits(img, max_width)

    if COMPRESSION_MODE == "fixed":
        return _encode_webp(img, quality), quality, None

    data, used_q, hit_floor = _compress_to_target_ratio(img, len(raw_bytes), quality)
    note = None
    if hit_floor:
        note = (f"تعذّر بلوغ نسبة {quality}% المطلوبة حتى بأدنى جودة ({MIN_QUALITY})، "
                f"استُخدم أفضل الممكن")
    return data, used_q, note


IMG_FETCH_RETRIES = int(os.environ.get("IMG_FETCH_RETRIES", "3"))
IMG_FETCH_DELAY_MS = int(os.environ.get("IMG_FETCH_DELAY_MS", "120"))


async def fetch_image_bytes(context, img_url: str, referer: str):
    """
    يحمّل الصورة عبر نفس جلسة متصفح Playwright (كوكيز + بصمة حقيقية) بدل
    مكتبة requests منفصلة — يحل مشكلة رفض بعض المواقع للتحميل من خارج
    جلسة متصفح حقيقية (السبب الأغلب وراء خطأ "cannot identify image").

    يعيد المحاولة عدة مرات بفاصل زمني متزايد عند الفشل: في الفصول الطويلة
    (مئات الصور)، خادم الصور أحيانًا يحدّد معدل الطلبات مؤقتًا (Rate Limiting)
    بعد سيل من الطلبات المتتالية على نفس الجلسة، فيرفض دفعة صور مرة وحدة ثم
    يعود يقبل بعد قليل — إعادة المحاولة بفاصل قصير تتعافى من هذا تلقائيًا.

    [مُعدَّل] يعيد الآن (bytes|None, سبب_الفشل|None) بدل bytes|None فقط —
    يتحقق من content-type فعليًا قبل قبول الاستجابة كصورة صالحة، ويحتفظ
    بآخر سبب فشل دقيق (status/content-type/استثناء) ليُطبع في اللوج بدل
    رسالة Pillow العامة التي لا تفسّر شيئًا.
    """
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
                    return body, None
                last_reason = f"جسم الاستجابة فارغ/صغير جدًا ({len(body) if body else 0} بايت)"
            else:
                last_reason = f"status={resp.status} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < IMG_FETCH_RETRIES:
            await asyncio.sleep(0.6 * attempt)
    return None, last_reason


async def wait_out_challenge(page) -> bool:
    """
    [مُضاف] بدل انتظار ثابت 5 ثوانٍ ثم إعادة تحميل واحدة فقط: يبقى يفحص كل
    CHALLENGE_POLL_MS إن كانت صفحة التحقق ما زالت ظاهرة، ويعيد التحميل بين
    كل فحص وآخر، ضمن ميزانية زمنية إجمالية CHALLENGE_MAX_WAIT_MS. يعيد True
    إن اختفت علامات صفحة التحقق (نجاح محتمل)، أو False إن استمرت حتى نفاد
    الميزانية الزمنية (على الأغلب تحدٍ لا يمكن حله من هذه البيئة/العنوان).
    """
    elapsed = 0
    while elapsed < CHALLENGE_MAX_WAIT_MS:
        await page.wait_for_timeout(CHALLENGE_POLL_MS)
        elapsed += CHALLENGE_POLL_MS
        if not await looks_like_challenge_page(page):
            return True
        try:
            await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
        except Exception:
            pass
        if not await looks_like_challenge_page(page):
            return True
    return False


async def open_and_collect(context, chapter_url: str, attempt: int, state_path: Path):
    """
    محاولة واحدة لفتح الصفحة واستخراج روابط الصور، باستخدام context مشترك
    (يُمرَّر من الخارج) بدل إنشاء context جديد في كل محاولة — هذا يحافظ على
    أي كوكيز تحقق (مثل cf_clearance) رُبحت سابقًا لنفس النطاق. يعيد
    (نجاح: bool, روابط_الصور, سبب_الفشل).
    """
    page = await context.new_page()

    navigated = False
    wait_strategy = "domcontentloaded" if attempt == 1 else "load"
    try:
        await page.goto(chapter_url, wait_until=wait_strategy, timeout=NAV_TIMEOUT_MS)
        navigated = True
    except Exception as e:
        print(f"  ⚠️ تعذّر تحميل الصفحة ({wait_strategy}): {e}")

    if navigated and await looks_like_challenge_page(page):
        print(f"  🛡️ صفحة تحقق/حماية محتملة (Cloudflare أو ما شابه) — انتظار حتى {CHALLENGE_MAX_WAIT_MS//1000} ثانية")
        cleared = await wait_out_challenge(page)
        if cleared:
            print("  ✅ يبدو أن صفحة التحقق زالت — نتابع الاستخراج")
            try:
                STORAGE_STATE_DIR.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=str(state_path))
            except Exception:
                pass
        else:
            print("  ❌ صفحة التحقق لم تُحَل ضمن المهلة — على الأغلب حماية Cloudflare متقدمة "
                  "(Managed Challenge/Turnstile) ترفض بيئة التشغيل الحالية (عنوان IP لخوادم CI "
                  "مصنّف عالي الخطورة غالبًا). لا يوجد حل برمجي مضمون 100% لهذا من داخل GitHub Actions.")
            await page.close()
            return False, [], "صفحة تحقق Cloudflare لم تُحَل ضمن المهلة الزمنية"

    # تمرير تدريجي لأسفل الصفحة لتحفيز أي تحميل كسول يعتمد على ظهور العنصر
    # بالشاشة (IntersectionObserver) — احتياط إضافي حتى لو المحدّدات نجحت
    try:
        for _ in range(6):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(400)
        await page.mouse.wheel(0, -20000)
    except Exception:
        pass

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة قبل الاستخراج: {found_count}")

    image_urls = await extract_image_urls(page, chapter_url)
    await page.close()

    # الحكم بالنجاح يعتمد على وجود صور مستخرجة فعليًا، وليس على إطلاق حدث
    # goto (domcontentloaded/load): بعض الصفحات ترسم محتواها الحقيقي كاملًا
    # (والصور معه) قبل أن يتعلّق الحدث نفسه بسبب مورد بطيء غير متعلق بالمحتوى
    # (إعلان فيديو، سكربت تتبّع معلّق...)، فرفض النتيجة في هذه الحالة كان
    # يُهدر بيانات صحيحة مكتشفة فعليًا بلا داعٍ.
    if not image_urls:
        reason = "لم يتم تحميل الصفحة أصلًا (انتهت المهلة)" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        return False, [], reason
    if not navigated:
        print("  ℹ️ ملاحظة: حدث goto لم يُطلَق (انتهت مهلته) لكن المحتوى الحقيقي كان قد اكتمل فعليًا — نُكمل به")
    return True, image_urls, ""


def domain_of(url: str) -> str:
    return urlparse(url).hostname or "unknown"


async def get_or_create_context(browser, domain: str):
    """
    [مُضاف] يُنشئ context واحدًا فقط لكل نطاق (وليس لكل فصل)، ويحمّل حالة
    جلسة محفوظة سابقًا (storage_state) إن وُجدت — أي كوكيز تحقق (cf_clearance)
    رُبحت في تشغيلة سابقة أو فصل سابق من نفس الموقع تُستخدم مباشرة، فيقل
    احتمال مواجهة صفحة التحقق من الأساس بدل اختبارها من الصفر في كل مرة.
    """
    STORAGE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STORAGE_STATE_DIR / f"{domain}.json"
    kwargs = dict(
        user_agent=UA,
        viewport={"width": 1280, "height": 1000},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    if state_path.exists():
        kwargs["storage_state"] = str(state_path)
        print(f"  🍪 استُخدمت جلسة محفوظة سابقًا لنطاق {domain}")
    context = await browser.new_context(**kwargs)
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return context, state_path


async def process_chapter(context, state_path: Path, chapter_url: str, index: int, total: int):
    print(f"[{index}/{total}] فتح: {chapter_url}")

    ok, image_urls, fail_reason = False, [], ""
    for attempt in range(1, RETRY_PER_CHAPTER + 1):
        if attempt > 1:
            print(f"  🔁 إعادة محاولة #{attempt}")
        ok, image_urls, fail_reason = await open_and_collect(context, chapter_url, attempt, state_path)
        if image_urls:
            break

    if not image_urls:
        print(f"  ❌ {fail_reason or 'لم يُعثر على صور في هذا الفصل'}")
        return None

    manga_id, chapter_num = manga_slug_from_url(chapter_url)
    chapter_dir = OUTPUT_DIR / manga_id / f"ch-{chapter_num}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    failed_indices = []
    for i, img_url in enumerate(image_urls, start=1):
        raw, reason = await fetch_image_bytes(context, img_url, chapter_url)
        if not raw:
            print(f"  ⚠️ فشلت صورة {i}: {reason} — الرابط: {img_url}")
            failed_indices.append(i)
            continue
        try:
            compressed, used_q, note = compress_image(raw, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            pct = (len(compressed) / len(raw) * 100) if raw else 0
            extra = f" — جودة WebP={used_q}" if COMPRESSION_MODE == "ratio" else ""
            print(f"  ✅ {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب ({pct:.0f}%){extra}")
            if note:
                print(f"     ⚠️ {note}")
        except Exception as e:
            print(f"  ⚠️ فشلت صورة {i} أثناء الضغط: {e} — الرابط: {img_url}")
        # فاصل بسيط بين كل صورة والتالية لتقليل احتمال إثارة تحديد معدل
        # الطلبات من الأساس في الفصول الطويلة (مئات الصور على نفس الجلسة)
        await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

    # تمريرة أخيرة: إعادة محاولة الصور اللي فشلت نهائيًا بعد إكمال البقية،
    # بعد ما يكون خادم الصور احتمالًا تعافى من أي تحديد معدل طلبات مؤقت
    if failed_indices:
        print(f"  🔁 إعادة محاولة نهائية لـ {len(failed_indices)} صورة فشلت...")
        still_failed = []
        for i in failed_indices:
            img_url = image_urls[i - 1]
            raw, reason = await fetch_image_bytes(context, img_url, chapter_url)
            if raw:
                try:
                    compressed, used_q, note = compress_image(raw, MAX_WIDTH, QUALITY)
                    filename = f"{i:03d}.webp"
                    (chapter_dir / filename).write_bytes(compressed)
                    saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
                    pct = (len(compressed) / len(raw) * 100) if raw else 0
                    extra = f" — جودة WebP={used_q}" if COMPRESSION_MODE == "ratio" else ""
                    print(f"  ✅ (إعادة محاولة) {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب ({pct:.0f}%){extra}")
                    if note:
                        print(f"     ⚠️ {note}")
                except Exception as e:
                    print(f"  ⚠️ فشلت صورة {i} أثناء الضغط بعد إعادة المحاولة: {e} — الرابط: {img_url}")
                    still_failed.append(i)
            else:
                print(f"  ⚠️ فشلت صورة {i} نهائيًا: {reason} — الرابط: {img_url}")
                still_failed.append(i)
            await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)
        if still_failed:
            print(f"  ❌ تعذّر تحميل {len(still_failed)} صورة نهائيًا: {still_failed}")

    # [مُعدَّل] لا نُغلق الـcontext هنا بعد الآن — أصبح مشتركًا بين كل فصول
    # نفس النطاق (يُغلق مرة واحدة في main() بعد معالجة كل فصول ذلك النطاق)
    # حتى تبقى كوكيز التحقق (cf_clearance) صالحة للفصل التالي من نفس الموقع.

    if not saved_paths:
        return None

    return {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "source_url": chapter_url,
        "image_paths": saved_paths,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=60
    )


def load_existing_manifest(manifest_path: Path) -> dict:
    """
    [مُضاف] يحمّل manifest.json الموجود مسبقًا (لو كان الـworktree يتتبّع فرع
    output الذي فيه بيانات من تشغيلات سابقة) بدل البدء من قاموس فارغ. هذا
    يمنع فقدان مانهوات/فصول سابقة كانت تُفقد سابقًا عند استبدال الملف بالكامل.
    """
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "manga" in data:
                return data
        except Exception as e:
            print(f"  ⚠️ تعذّرت قراءة manifest.json الحالي ({e}) — سيُبنى من جديد")
    return {"manga": {}}


def merge_chapter_into_manifest(manifest: dict, result: dict) -> None:
    """
    [مُضاف] يدمج فصلًا واحدًا ناجحًا داخل الـmanifest القائم: يضيف مانهوا
    جديدة إن لم تكن موجودة، ويستبدل الفصل لو كان موجودًا مسبقًا (نفس رابط
    المصدر أو نفس رقم الفصل — حالة إعادة معالجة فصل فشل جزئيًا سابقًا)، وإلا
    يضيفه، ثم يعيد ترتيب الفصول برقمها.
    """
    mid = result["manga_id"]
    if mid not in manifest["manga"]:
        manifest["manga"][mid] = {
            "name": mid.split("__", 1)[-1].replace("-", " "),
            "chapters": [],
        }
    images_cdn = [f"{CDN_BASE}/{p}" for p in result["image_paths"]] if CDN_BASE else result["image_paths"]
    new_chapter = {
        "label": f"الفصل {result['chapter_num']}",
        "chNum": float(result["chapter_num"]) if re.match(r"^\d+(\.\d+)?$", result["chapter_num"]) else 0,
        "sourceUrl": result["source_url"],
        "images": images_cdn,
    }
    chapters = manifest["manga"][mid]["chapters"]
    for idx, c in enumerate(chapters):
        if c.get("sourceUrl") == new_chapter["sourceUrl"] or c.get("chNum") == new_chapter["chNum"]:
            chapters[idx] = new_chapter
            break
    else:
        chapters.append(new_chapter)
    chapters.sort(key=lambda c: c["chNum"])


def write_manifest(manifest: dict) -> None:
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def git_commit_and_push(commit_message: str) -> bool:
    """
    [مُضاف] يحفظ كل التغييرات الحالية داخل GIT_COMMIT_DIR (commit + push)
    فورًا. يُستدعى بعد كل فصل ناجح — لا بعد اكتمال كل الفصول — حتى لا تُفقد
    نتائج الفصول التي سبق دفعها لو انقطع التشغيل لاحقًا (بلوغ سقف الوقت،
    إلغاء يدوي، عطل مؤقت). لا يوقف تنفيذ باقي الفصول عند فشله — فقط يسجّل
    تحذيرًا ويكمل، مع محاولة تعويضية أخيرة في نهاية main().
    """
    if not GIT_COMMIT_DIR:
        return False

    rel_output = str(OUTPUT_DIR)
    add = _run_git(["add", rel_output], cwd=GIT_COMMIT_DIR)
    if add.returncode != 0:
        print(f"  ⚠️ git add فشل: {add.stderr.strip()[:300]}")
        return False

    status = _run_git(["status", "--porcelain", "--", rel_output], cwd=GIT_COMMIT_DIR)
    if not status.stdout.strip():
        print("  ℹ️ لا تغييرات جديدة لحفظها في Git لهذا الفصل")
        return True

    commit = _run_git(
        ["-c", f"user.name={GIT_USER_NAME}", "-c", f"user.email={GIT_USER_EMAIL}",
         "commit", "-m", commit_message],
        cwd=GIT_COMMIT_DIR,
    )
    if commit.returncode != 0:
        print(f"  ⚠️ git commit فشل: {commit.stderr.strip()[:300]}")
        return False

    for attempt in range(1, GIT_PUSH_RETRIES + 1):
        push = _run_git(["push", "origin", f"HEAD:{GIT_BRANCH}"], cwd=GIT_COMMIT_DIR)
        if push.returncode == 0:
            print(f"  📤 تم الحفظ والدفع لفرع {GIT_BRANCH} (محاولة {attempt})")
            return True
        print(f"  ⚠️ فشل push (محاولة {attempt}/{GIT_PUSH_RETRIES}): {push.stderr.strip()[:300]}")
        if attempt < GIT_PUSH_RETRIES:
            # الأرجح تعارض fast-forward (كاتب آخر دفع بينما نحن نعمل) — نسحب
            # ونعيد الترتيب فوق أحدث تغييرات عن بُعد قبل إعادة محاولة الدفع
            _run_git(["fetch", "origin", GIT_BRANCH], cwd=GIT_COMMIT_DIR)
            rebase = _run_git(["rebase", f"origin/{GIT_BRANCH}"], cwd=GIT_COMMIT_DIR)
            if rebase.returncode != 0:
                _run_git(["rebase", "--abort"], cwd=GIT_COMMIT_DIR)
            time.sleep(2 * attempt)

    print(f"  ❌ تعذّر دفع هذا الفصل لفرع {GIT_BRANCH} بعد {GIT_PUSH_RETRIES} محاولات "
          f"— التغييرات محفوظة محليًا (commit) وستُعاد محاولة دفعها في نهاية التشغيلة")
    return False


async def main():
    chapter_urls = [u for u in re.split(r'[\s,،؛;]+', CHAPTER_URLS_RAW.strip()) if u.startswith('http')]
    print(f"📋 تم استخراج {len(chapter_urls)} رابط صالح من المدخلات:")
    for u in chapter_urls:
        print(f"   - {u}")
    if not chapter_urls:
        print("لا توجد روابط فصول في المدخلات (CHAPTER_URLS فارغة)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if GIT_COMMIT_DIR:
        print(f"🔗 الدفع التدريجي مفعّل — سيُحفظ كل فصل ناجح فورًا لفرع {GIT_BRANCH}")
    else:
        print("ℹ️ الدفع التدريجي معطّل (GIT_COMMIT_DIR غير مضبوط) — كتابة محلية فقط")

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest = load_existing_manifest(manifest_path)

    results = []
    pushed_count, failed_push_count = 0, 0

    def _handle_chapter_result(r: dict) -> None:
        """
        [مُضاف] يُستدعى فور نجاح كل فصل: يدمجه في الـmanifest، يكتبه على
        القرص، ثم يحاول حفظه ودفعه في Git فورًا — بدل تجميع كل النتائج
        وانتظار نهاية كل الفصول لحفظ أي شيء.
        """
        nonlocal pushed_count, failed_push_count
        results.append(r)
        merge_chapter_into_manifest(manifest, r)
        write_manifest(manifest)
        commit_msg = f"إضافة {r['manga_id']} — الفصل {r['chapter_num']} - {_utc_now()}"
        if git_commit_and_push(commit_msg):
            pushed_count += 1
        elif GIT_COMMIT_DIR:
            failed_push_count += 1

    async with async_playwright() as p:
        # [مُعدَّل] نحاول أولًا تشغيل Chrome الحقيقي المثبَّت (channel="chrome")
        # بدل نسخة Chromium المرفقة الافتراضية — بصمة Chrome الحقيقي أقرب لما
        # يتوقعه Cloudflare من متصفح مستخدم عادي، فاحتمال نجاحها أعلى قليلًا.
        # لو لم يكن مثبَّتًا في البيئة (مثل GitHub Actions بدون خطوة تثبيت
        # إضافية)، نعود تلقائيًا لـChromium العادي.
        try:
            browser = await p.chromium.launch(
                channel="chrome", args=["--disable-blink-features=AutomationControlled"]
            )
            print("🌐 تم تشغيل Chrome الحقيقي (channel=chrome)")
        except Exception:
            browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            print("🌐 Chrome الحقيقي غير متاح — تشغيل Chromium الافتراضي")

        # [مُعدَّل] نُجمّع الفصول حسب النطاق ونُنشئ context واحدًا فقط لكل
        # نطاق (بدل واحد لكل فصل) — يُغلق بعد معالجة كل فصول ذلك النطاق.
        # هذا يحافظ على كوكيز التحقق (cf_clearance) بين فصول نفس الموقع.
        by_domain: dict[str, list[tuple[int, str]]] = {}
        for i, url in enumerate(chapter_urls, start=1):
            by_domain.setdefault(domain_of(url), []).append((i, url))

        for domain, items in by_domain.items():
            context, state_path = await get_or_create_context(browser, domain)
            for i, url in items:
                r = await process_chapter(context, state_path, url, i, len(chapter_urls))
                if r:
                    # [مُعدَّل] بدل تجميع النتيجة فقط بالذاكرة، تُدمَج وتُكتب
                    # وتُدفَع فورًا (انظر _handle_chapter_result وملاحظة 7 أعلى
                    # الملف) — حماية من فقدان كل شيء لو انقطع التشغيل لاحقًا
                    _handle_chapter_result(r)
            await context.close()

        await browser.close()

    # محاولة تعويضية أخيرة: لو فشل دفع فصل أو أكثر أثناء التشغيل (تعارض
    # مؤقت، انقطاع شبكة قصير...)، هذه فرصة أخيرة لدفع كل ما تبقى محليًا
    # بدل تركه عالقًا في الـcommits المحلية فقط داخل الـRunner المؤقت
    if GIT_COMMIT_DIR:
        final_msg = f"دفع ختامي للتشغيلة - {_utc_now()}"
        if git_commit_and_push(final_msg):
            print("📤 الدفع الختامي: تم التأكد من رفع كل التغييرات المتبقية")
        if failed_push_count:
            print(f"⚠️ تنبيه: فشل الدفع الفوري لـ {failed_push_count} فصل أثناء التشغيل "
                  f"(تمت تغطيتها على الأغلب بالدفع الختامي أعلاه إن نجح)")

    print(f"\n✅ اكتمل: {len(results)} فصل من أصل {len(chapter_urls)}")
    if GIT_COMMIT_DIR:
        print(f"📤 دُفع فوريًا بنجاح: {pushed_count}/{len(results)} فصل")
    print(f"manifest.json جاهز في {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
