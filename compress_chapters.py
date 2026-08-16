#!/usr/bin/env python3
"""
سكربت ضغط فصول المانهوا — نسخة "بروفايلات المواقع".

بدل ما يحاول اكتشاف الأسلوب المناسب لكل موقع بالتجربة والخطأ في كل تشغيلة
(وهذا كان يهدر دقائق كاملة، خصوصًا مع مواقع لا تطابق قوالب معروفة)، هذا
السكربت يحمل جدول SITE_PROFILES بإعدادات جاهزة ومؤكدة لكل موقع جرّبناه
فعليًا، مبنية على تشخيص حقيقي من تشغيلات سابقة — راجع التعليق أعلى كل
بروفايل لمصدر كل قرار.

اختيار البروفايل:
- تلقائي حسب نطاق رابط كل فصل (كل فصل بقائمة الروابط يُكتشف له بروفايله
  الخاص، فتقدر تخلط فصولًا من مواقع مختلفة بنفس التشغيلة).
- أو تقدر تجبر بروفايل معيّن عبر متغيّر البيئة SITE_PROFILE (تملأه قائمة
  اختيار "site" في واجهة GitHub Actions) — مفيد لو رابط موقع جديد ما
  انطابق تلقائيًا، أو لو تبي تتجاوز الاكتشاف لأي سبب.

البروفايلات المتوفرة حاليًا: azorafly, manga-starz, mangatuk, mangatime,
dilar. أي موقع غير معروف يستخدم "البروفايل العام" (الأكثر أمانًا: متصفح
آلي + تمرير تراكمي + استخراج عام + فلترة ودجات) — وهو نفسه أسلوب mangatime
لأنه أثبت نجاحه مع موقع لا يطابق أي قالب معروف.
"""
import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import httpx
from PIL import Image
from io import BytesIO
from playwright.async_api import async_playwright

try:
    from curl_cffi import requests as curl_cffi_requests
except ImportError:
    curl_cffi_requests = None

QUALITY = int(os.environ.get("IMG_QUALITY", "25"))
MAX_WIDTH = int(os.environ.get("IMG_MAX_WIDTH", "700"))
CHAPTER_URLS_RAW = os.environ.get("CHAPTER_URLS", "")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
CDN_BASE = os.environ.get("CDN_BASE", "")
FORCED_SITE = os.environ.get("SITE_PROFILE", "auto").strip().lower()

SCROLL_MAX_STEPS = int(os.environ.get("SCROLL_MAX_STEPS", "400"))
SCROLL_STEP_WAIT_MS = int(os.environ.get("SCROLL_STEP_WAIT_MS", "350"))
WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad", re.I)
WIDGET_CONTEXT_PATTERN = re.compile(
    r"related|similar|recommend|suggest|you-may|you_may|might-like|"
    r"widget|sidebar|comment|carousel|swiper|sponsor|advert|banner-ad|"
    r"next-chap|prev-chap|also-read|readers-also|trending|popular-manga",
    re.I,
)
CHALLENGE_MARKERS = [
    "just a moment", "checking your browser", "attention required",
    "cf-browser-verification", "ddos protection by", "verifying you are human",
    "enable javascript and cookies",
]

# محدّدات قالب Madara القياسي (مواقع ووردبريس للمانجا/المانهوا الشائعة)
MADARA_SELECTORS = [
    ".reading-content img",
    ".page-break img",
    ".text-left img",
    "#readerarea img",
    ".chapter-content img",
]

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


# ===================== جدول بروفايلات المواقع =====================
# كل بروفايل = إعدادات مؤكدة من تشخيص فعلي سابق، لا اكتشاف بالتجربة.
SITE_PROFILES = {

    # أزورافلاي: أخف حالة بيننا. الروابط الحقيقية موجودة مباشرة في HTML
    # الثابت (noscript / data-src) — لا حاجة لمتصفح آلي ولا تمرير إطلاقًا.
    # لا حماية Cloudflare ولا حماية سرقة (hotlink) — تحميل مباشر بدون جلسة.
    "azorafly": {
        "label": "أزورافلاي",
        "match": ["azorafly.com"],
        "method": "static",
        "content_selectors": None,
        "needs_scroll": False,
        "browser_session_for_images": False,
        "ad_wall": None,
        "persistent_context": False,
        "accept_partial_nav": False,
        "nav_timeout_ms": 20000,
        "img_fetch_retries": 2,
        "img_fetch_delay_ms": 50,
    },

    # ستار مانجا: محمي بتحدي Cloudflare كامل. لا يوجد حل تلقائي مضمون.
    # نجرّب محاكاة بصمة TLS (curl_cffi) كخطوة تجريبية أولى (لم تُختبر
    # نجاحها فعليًا بعد — إن فشلت، ننتقل لمتصفح Playwright الذي سيكتشف
    # صفحة التحدي بوضوح بدل تخمين غامض).
    "manga-starz": {
        "label": "ستار مانجا",
        "match": ["manga-starz.net"],
        "method": "playwright",
        "content_selectors": MADARA_SELECTORS,
        "needs_scroll": True,
        "browser_session_for_images": True,
        "ad_wall": None,
        "persistent_context": False,
        "accept_partial_nav": True,
        "nav_timeout_ms": 30000,
        "img_fetch_retries": 3,
        "img_fetch_delay_ms": 150,
        "try_curl_cffi_first": True,
        "known_hard_blocked": True,
    },

    # مانجا توك: يحتاج متصفح آلي، والصور تحتاج نفس جلسة المتصفح (كوكيز).
    # الفصل الأول أثقل عادة (محتوى ترويجي) فقد يتأخر حدث goto دون أن يعني
    # فشلًا حقيقيًا — نتساهل ونحكم بالنجاح على وجود صور مستخرجة فعليًا.
    # فصول طويلة جدًا ممكنة (شُوهد فصل من 900 صفحة) فنحتاج صبرًا بالتحميل.
    "mangatuk": {
        "label": "مانجا توك",
        "match": ["mangatuk.com"],
        "method": "playwright",
        "content_selectors": MADARA_SELECTORS,
        "needs_scroll": False,
        "browser_session_for_images": True,
        "ad_wall": None,
        "persistent_context": False,
        "accept_partial_nav": True,
        "nav_timeout_ms": 60000,
        "img_fetch_retries": 3,
        "img_fetch_delay_ms": 150,
    },

    # مانجا تايم: لا يطابق أي قالب معروف (Madara وغيره) — استخراج عام فقط.
    # يستخدم تحميلًا كسولًا/virtualization يُلغي الصور البعيدة عن الشاشة،
    # فيحتاج تمريرًا تراكميًا كاملًا لا لقطة واحدة. يحقن صور "مقترح لك" في
    # نفس منطقة القراءة تقريبًا فيحتاج فلترة سياق ودجات (مُفعَّلة دائمًا).
    "mangatime": {
        "label": "مانجا تايم",
        "match": ["mangatime.org"],
        "method": "playwright",
        "content_selectors": None,
        "needs_scroll": True,
        "browser_session_for_images": True,
        "ad_wall": None,
        "persistent_context": False,
        "accept_partial_nav": True,
        "nav_timeout_ms": 30000,
        "img_fetch_retries": 3,
        "img_fetch_delay_ms": 120,
    },

    # أوليمبوس ستاف: محمي بتحدي Cloudflare "خفيف" (Managed Challenge) —
    # الطلب المباشر يرجع 403 (cf-mitigated: challenge)، لكن على عكس ستار
    # مانجا، متصفح Playwright يتجاوزه فعليًا (challenge_detected=false،
    # وعنوان الصفحة الحقيقي يظهر صح) — تأكدنا من هذا بفحص تشخيصي مباشر.
    # التمرير التراكمي لا يفيد هنا (34 صورة عند أول لحظة → 32 بعد تمرير
    # كامل، يعني نقصان طفيف لا زيادة) فنعتمد لقطة سريعة بدون تمرير. قالب
    # Madara قياسي (.reading-content/.page-break طابقا 26/25 صورة). صور
    # الفصل نفسها غير محمية إطلاقًا (اختبار hotlink نجح بطلب مباشر بلا
    # جلسة بنفس حجم التحميل عبر جلسة المتصفح)، فنكتفي بطلب HTTP عادي
    # لتحميلها بدل إبقاء جلسة متصفح مفتوحة لكل صورة — أخف وأسرع. بعض
    # صور الفصل من نطاقات خارجية (i.ibb.co, blogspot) بجانب نطاق الموقع،
    # فلا تُفعَّل أي فلترة نطاق صارمة لهذا الموقع مستقبلًا.
    "olympustaff": {
        "label": "أوليمبوس ستاف",
        "match": ["olympustaff.com"],
        "method": "playwright",
        "content_selectors": MADARA_SELECTORS,
        "needs_scroll": False,
        "browser_session_for_images": False,
        "ad_wall": None,
        "persistent_context": False,
        "accept_partial_nav": True,
        "nav_timeout_ms": 30000,
        "img_fetch_retries": 3,
        "img_fetch_delay_ms": 150,
    },

    # دايلار: جدار "متابعة" يظهر فورًا (زر #_fb_continue) ويبقى معطّلًا/غير
    # مرئي لمدة متغيّرة (ليست ثابتة) — لازم انتظار فعلي (polling) لحين يصير
    # مرئيًا ومفعَّلًا. persistent_context=True عشان لو الموقع يحفظ تجاوز
    # الجدار بكوكيز الجلسة، يظهر بالفصل الأول فقط ويُتخطى تلقائيًا بالبقية.
    # الاستخراج بعد تجاوز الجدار غير مؤكد بعد (لم نصل لتجربة ناجحة كاملة) —
    # نستخدم نفس أسلوب Madara كأفضل تخمين احتياطي، ونطبع تحذيرًا بذلك.
    "dilar": {
        "label": "دايلار",
        "match": ["dilar.tube"],
        "method": "playwright",
        "content_selectors": MADARA_SELECTORS,
        "needs_scroll": True,
        "browser_session_for_images": True,
        "ad_wall": {"selector": "#_fb_continue", "max_wait_ms": 30000},
        "persistent_context": True,
        "accept_partial_nav": True,
        "nav_timeout_ms": 30000,
        "img_fetch_retries": 3,
        "img_fetch_delay_ms": 150,
        "unconfirmed": True,
    },
}

# البروفايل العام: يُستخدم لأي موقع غير مُدرَج بالجدول أعلاه. نفس أسلوب
# mangatime لأنه أثبت نجاحه مع موقع لا يطابق أي قالب معروف مسبقًا.
DEFAULT_PROFILE = {
    "label": "عام (افتراضي)",
    "match": [],
    "method": "playwright",
    "content_selectors": None,
    "needs_scroll": True,
    "browser_session_for_images": True,
    "ad_wall": None,
    "persistent_context": False,
    "accept_partial_nav": True,
    "nav_timeout_ms": 30000,
    "img_fetch_retries": 3,
    "img_fetch_delay_ms": 150,
}


def detect_profile(url: str):
    """يعيد (اسم_البروفايل, إعداداته). يحترم SITE_PROFILE المفروض من
    البيئة لو كان اسمًا معروفًا؛ وإلا يكتشف تلقائيًا حسب نطاق الرابط؛
    وإلا يرجع للبروفايل العام."""
    if FORCED_SITE and FORCED_SITE != "auto" and FORCED_SITE in SITE_PROFILES:
        return FORCED_SITE, SITE_PROFILES[FORCED_SITE]

    hostname = (urlparse(url).hostname or "").lower()
    for name, profile in SITE_PROFILES.items():
        if any(m in hostname for m in profile["match"]):
            return name, profile

    return "default", DEFAULT_PROFILE


# ===================== أدوات عامة مشتركة =====================

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


def is_cloudflare_challenge(html: str) -> bool:
    lowered = html[:3000].lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def dedupe(urls: list[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen and not IGNORE_PATTERN.search(u):
            seen.add(u)
            out.append(u)
    return out


def compress_image(raw_bytes: bytes, max_width: int, quality: int) -> bytes:
    img = Image.open(BytesIO(raw_bytes))
    img = img.convert("RGB") if img.mode in ("P", "CMYK") else img

    scale = 1.0
    if img.width > max_width:
        scale = min(scale, max_width / img.width)
    if img.width * scale > WEBP_HARD_LIMIT:
        scale = min(scale, WEBP_HARD_LIMIT / img.width)
    if img.height * scale > WEBP_HARD_LIMIT:
        scale = min(scale, WEBP_HARD_LIMIT / img.height)
    if scale < 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)

    out = BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


# ===================== المسار الثابت (بدون متصفح آلي) — أزورافلاي وأمثاله =====================

async def fetch_static_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"  ⚠️ فشل الجلب الثابت: {e}")
    return None


def extract_from_static_html(html: str, base_url: str) -> list[str]:
    # 1) noscript أولًا (بديل حقيقي شائع عند التحميل الكسول)
    found = []
    for ns in re.finditer(r"<noscript>([\s\S]*?)</noscript>", html, re.I):
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', ns.group(1)):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    # 2) كل وسوم <img> — نفضّل data-src/data-lazy-src/data-original على src
    for tag_m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = tag_m.group(0)
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            am = re.search(attr + r'=["\']([^"\']+)["\']', tag, re.I)
            if am and not am.group(1).startswith("data:"):
                found.append(urljoin(base_url, am.group(1)))
                break
    if found:
        return dedupe(found)

    # 3) احتياط نهائي
    found = [urljoin(base_url, m.group(0)) for m in
             re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(found)


async def fetch_image_static(client: httpx.AsyncClient, img_url: str, referer: str, retries: int, delay_ms: int):
    last_reason = "سبب غير معروف"
    for attempt in range(1, retries + 1):
        try:
            resp = await client.get(img_url, headers={"User-Agent": UA, "Referer": referer}, timeout=20)
            ctype = resp.headers.get("content-type", "")
            if resp.status_code == 200 and (ctype.startswith("image/") or ctype == ""):
                if resp.content and len(resp.content) >= 500:
                    return resp.content, None
                last_reason = f"جسم الاستجابة فارغ/صغير جدًا"
            else:
                last_reason = f"status={resp.status_code} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < retries:
            await asyncio.sleep(0.6 * attempt)
    return None, last_reason


async def process_chapter_static(chapter_url: str, profile: dict, index: int, total: int):
    async with httpx.AsyncClient() as client:
        html = await fetch_static_html(client, chapter_url)
        if not html:
            print("  ❌ تعذّر جلب الصفحة (ثابت)")
            return None
        if is_cloudflare_challenge(html):
            print("  🛡️ صفحة تحدي حماية — البروفايل الثابت لا يتجاوزها، جرّب بروفايل متصفح آلي")
            return None

        image_urls = extract_from_static_html(html, chapter_url)
        if not image_urls:
            print("  ❌ لم يُعثر على صور (استخراج ثابت)")
            return None
        print(f"  📊 إجمالي الصور (استخراج ثابت): {len(image_urls)}")

        async def fetch_one(u):
            return await fetch_image_static(client, u, chapter_url, profile["img_fetch_retries"], profile["img_fetch_delay_ms"])

        return await save_all_images(chapter_url, image_urls, fetch_one, profile)


# ===================== المسار الآلي (Playwright) =====================

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


async def collect_images_while_scrolling(page, selector: str, do_scroll: bool) -> list[dict]:
    """يمرّر تراكميًا (إن do_scroll) ويجمع كل الصور التي ظهرت في أي لحظة —
    يحل مشكلة الصفحات التي تُلغي (unmount) الصور البعيدة عن منطقة العرض."""
    seen: dict[str, str] = {}

    def merge(items):
        for it in items:
            u = it.get("url")
            if u and u not in seen:
                seen[u] = it.get("ctx", "")

    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await page.wait_for_timeout(300)

    if not do_scroll:
        try:
            items = await page.eval_on_selector_all(selector, IMG_SRC_WITH_CONTEXT_JS)
            merge(items)
        except Exception:
            pass
        return [{"url": u, "ctx": c} for u, c in seen.items()]

    stable_rounds = 0
    for _ in range(SCROLL_MAX_STEPS):
        try:
            items = await page.eval_on_selector_all(selector, IMG_SRC_WITH_CONTEXT_JS)
        except Exception:
            items = []
        before = len(seen)
        merge(items)
        grew = len(seen) > before

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
            items = await page.eval_on_selector_all(selector, IMG_SRC_WITH_CONTEXT_JS)
            merge(items)
        except Exception:
            pass

    return [{"url": u, "ctx": c} for u, c in seen.items()]


def filter_widget_context(items: list[dict], base_url: str) -> list[str]:
    kept, excluded = [], 0
    for item in items:
        u, ctx = item.get("url"), item.get("ctx", "")
        if not u or u.startswith("data:"):
            continue
        if WIDGET_CONTEXT_PATTERN.search(ctx):
            excluded += 1
            continue
        kept.append(urljoin(base_url, u))
    if excluded:
        print(f"  🧹 استُبعدت {excluded} صورة بسبب سياق ودجت (مقترح/مشابه/إعلان...)")
    return dedupe(kept)


async def extract_via_playwright(page, base_url: str, profile: dict) -> list[str]:
    do_scroll = profile["needs_scroll"]

    if profile["content_selectors"]:
        for selector in profile["content_selectors"]:
            items = await collect_images_while_scrolling(page, selector, do_scroll)
            found = filter_widget_context(items, base_url)
            if len(found) >= 3:
                return found

    # noscript
    try:
        noscript_imgs = await page.eval_on_selector_all("noscript", "els => els.map(e => e.innerHTML)")
    except Exception:
        noscript_imgs = []
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    # عام: كل <img> بعد تمرير تراكمي
    items = await collect_images_while_scrolling(page, "img", do_scroll)
    found = filter_widget_context(items, base_url)
    if found:
        return found

    # احتياط نهائي
    try:
        html = await page.content()
    except Exception:
        html = ""
    return dedupe([urljoin(base_url, m.group(0)) for m in
                   re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)])


async def bypass_ad_wall(page, wall_config: dict | None):
    if not wall_config:
        return
    selector = wall_config["selector"]
    max_wait = wall_config.get("max_wait_ms", 30000)
    elapsed = 0
    while elapsed < max_wait:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible() and not await el.is_disabled():
                await el.click()
                print("  🚧 تم تجاوز جدار الإعلانات")
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass
        await page.wait_for_timeout(500)
        elapsed += 500
    print("  ⚠️ لم يظهر زر تجاوز جدار الإعلانات خلال المهلة (قد يكون غائبًا لهذا الفصل، أو تغيّر الموقع)")


async def fetch_image_via_context(context, img_url: str, referer: str, retries: int, delay_ms: int):
    last_reason = "سبب غير معروف"
    for attempt in range(1, retries + 1):
        try:
            resp = await context.request.get(
                img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=20000,
            )
            ctype = resp.headers.get("content-type", "")
            if resp.ok and (ctype.startswith("image/") or ctype == ""):
                body = await resp.body()
                if body and len(body) >= 500:
                    return body, None
                last_reason = "جسم الاستجابة فارغ/صغير جدًا"
            else:
                last_reason = f"status={resp.status} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < retries:
            await asyncio.sleep(0.6 * attempt)
    return None, last_reason


async def get_or_create_context(browser, profile_name: str, profile: dict, shared_contexts: dict):
    if profile["persistent_context"] and profile_name in shared_contexts:
        return shared_contexts[profile_name], False  # False = ليس جديدًا، لا تغلقه بعد الفصل

    context = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 1000},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

    if profile["persistent_context"]:
        shared_contexts[profile_name] = context
        return context, False
    return context, True  # True = جديد ومؤقت، أغلقه بعد الفصل


async def process_chapter_playwright(browser, chapter_url: str, profile_name: str, profile: dict,
                                      index: int, total: int, shared_contexts: dict):
    context, should_close = await get_or_create_context(browser, profile_name, profile, shared_contexts)
    page = await context.new_page()

    navigated = False
    try:
        await page.goto(chapter_url, wait_until="domcontentloaded", timeout=profile["nav_timeout_ms"])
        navigated = True
    except Exception as e:
        print(f"  ⚠️ تعذّر تحميل الصفحة بالكامل: {e}")

    if navigated and profile.get("ad_wall"):
        await bypass_ad_wall(page, profile["ad_wall"])

    if navigated:
        try:
            title = (await page.title() or "").lower()
            body = (await page.inner_text("body"))[:800].lower() if await page.query_selector("body") else ""
            if is_cloudflare_challenge(title + " " + body):
                print("  🛡️ صفحة تحدي حماية Cloudflare مؤكدة — لا حل تلقائي مضمون لهذا الموقع")
                await page.close()
                if should_close:
                    await context.close()
                return None
        except Exception:
            pass

    image_urls = await extract_via_playwright(page, chapter_url, profile)
    await page.close()

    if not image_urls:
        if should_close:
            await context.close()
        reason = "لم تُحمَّل الصفحة ولم تُستخرج صور" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        print(f"  ❌ {reason}")
        return None

    if not navigated and profile.get("accept_partial_nav"):
        print("  ℹ️ ملاحظة: حدث التنقل لم يكتمل رسميًا لكن محتوى حقيقي استُخرج فعليًا — نُكمل به")

    print(f"  📊 إجمالي الصور المستخرجة: {len(image_urls)}")

    async def fetch_one(u):
        if profile["browser_session_for_images"]:
            return await fetch_image_via_context(context, u, chapter_url, profile["img_fetch_retries"], profile["img_fetch_delay_ms"])
        async with httpx.AsyncClient() as client:
            return await fetch_image_static(client, u, chapter_url, profile["img_fetch_retries"], profile["img_fetch_delay_ms"])

    result = await save_all_images(chapter_url, image_urls, fetch_one, profile)

    if should_close:
        await context.close()
    return result


# ===================== curl_cffi تجريبي (لمواقع محمية ببصمة TLS) =====================

async def try_curl_cffi_html(url: str) -> str | None:
    """محاولة تجريبية غير مضمونة: محاكاة بصمة TLS حقيقية لمتصفح Chrome.
    لم تُختبر نجاحها فعليًا بعد مع أي موقع بهذه المحادثة — إن فشلت أو
    المكتبة غير مثبَّتة، نرجع None بصمت وننتقل لمسار Playwright كالمعتاد."""
    if curl_cffi_requests is None:
        return None
    try:
        def _do():
            r = curl_cffi_requests.get(url, impersonate="chrome124", timeout=20, headers={"User-Agent": UA})
            return r.text if r.status_code == 200 else None
        return await asyncio.to_thread(_do)
    except Exception as e:
        print(f"  🧪 محاولة curl_cffi فشلت: {e}")
        return None


# ===================== حفظ الصور (مشترك بين كل المسارات) =====================

async def save_all_images(chapter_url: str, image_urls: list[str], fetch_one, profile: dict):
    manga_id, chapter_num = manga_slug_from_url(chapter_url)
    chapter_dir = OUTPUT_DIR / manga_id / f"ch-{chapter_num}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    saved_paths, failed_indices = [], []
    delay_s = profile["img_fetch_delay_ms"] / 1000

    for i, img_url in enumerate(image_urls, start=1):
        raw, reason = await fetch_one(img_url)
        if not raw:
            print(f"  ⚠️ فشلت صورة {i}: {reason} — {img_url}")
            failed_indices.append(i)
            await asyncio.sleep(delay_s)
            continue
        try:
            compressed = compress_image(raw, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            print(f"  ✅ {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
        except Exception as e:
            print(f"  ⚠️ فشلت صورة {i} أثناء الضغط: {e}")
        await asyncio.sleep(delay_s)

    if failed_indices:
        print(f"  🔁 إعادة محاولة نهائية لـ {len(failed_indices)} صورة فشلت...")
        still_failed = []
        for i in failed_indices:
            raw, reason = await fetch_one(image_urls[i - 1])
            if raw:
                try:
                    compressed = compress_image(raw, MAX_WIDTH, QUALITY)
                    filename = f"{i:03d}.webp"
                    (chapter_dir / filename).write_bytes(compressed)
                    saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
                    print(f"  ✅ (إعادة محاولة) {i}/{len(image_urls)}")
                except Exception as e:
                    print(f"  ⚠️ فشلت صورة {i} أثناء الضغط بعد إعادة المحاولة: {e}")
                    still_failed.append(i)
            else:
                print(f"  ⚠️ فشلت صورة {i} نهائيًا: {reason}")
                still_failed.append(i)
            await asyncio.sleep(delay_s)
        if still_failed:
            print(f"  ❌ تعذّر تحميل {len(still_failed)} صورة نهائيًا: {still_failed}")

    if not saved_paths:
        return None

    return {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "source_url": chapter_url,
        "image_paths": saved_paths,
    }


# ===================== التوزيع الرئيسي =====================

async def process_chapter(browser, chapter_url: str, index: int, total: int, shared_contexts: dict):
    profile_name, profile = detect_profile(chapter_url)
    label = profile.get("label", profile_name)
    tag = " (تجريبي/غير مؤكد)" if profile.get("unconfirmed") else ""
    print(f"[{index}/{total}] فتح: {chapter_url}  [بروفايل: {label}{tag}]")

    if profile.get("known_hard_blocked"):
        print("  ⚠️ هذا الموقع معروف بحماية قوية (Cloudflare) — النجاح غير مضمون")

    if profile.get("try_curl_cffi_first"):
        html = await try_curl_cffi_html(chapter_url)
        if html and not is_cloudflare_challenge(html):
            print("  🧪 نجحت محاكاة بصمة TLS تجريبيًا — استخراج ثابت من النتيجة")
            image_urls = extract_from_static_html(html, chapter_url)
            if image_urls:
                async with httpx.AsyncClient() as client:
                    async def fetch_one(u):
                        return await fetch_image_static(client, u, chapter_url, profile["img_fetch_retries"], profile["img_fetch_delay_ms"])
                    return await save_all_images(chapter_url, image_urls, fetch_one, profile)
        print("  🧪 محاولة curl_cffi لم تنجح (تجريبي، غير مضمون) — نكمل بمتصفح Playwright")

    if profile["method"] == "static":
        result = await process_chapter_static(chapter_url, profile, index, total)
        if result:
            return result
        print("  ↪️ الاستخراج الثابت لم ينجح — نحاول بمتصفح Playwright كاحتياط")
        return await process_chapter_playwright(browser, chapter_url, profile_name, DEFAULT_PROFILE, index, total, shared_contexts)

    return await process_chapter_playwright(browser, chapter_url, profile_name, profile, index, total, shared_contexts)


async def main():
    chapter_urls = [u for u in re.split(r'[\s,،؛;]+', CHAPTER_URLS_RAW.strip()) if u.startswith('http')]
    print(f"📋 تم استخراج {len(chapter_urls)} رابط صالح من المدخلات:")
    for u in chapter_urls:
        _, prof = detect_profile(u)
        print(f"   - {u}  [{prof.get('label')}]")
    if not chapter_urls:
        print("لا توجد روابط فصول في المدخلات (CHAPTER_URLS فارغة)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    shared_contexts = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for i, url in enumerate(chapter_urls, start=1):
            r = await process_chapter(browser, url, i, len(chapter_urls), shared_contexts)
            if r:
                results.append(r)
        for ctx in shared_contexts.values():
            await ctx.close()
        await browser.close()

    manifest = {"manga": {}}
    for r in results:
        mid = r["manga_id"]
        if mid not in manifest["manga"]:
            manifest["manga"][mid] = {"name": mid.split("__", 1)[-1].replace("-", " "), "chapters": []}
        images_cdn = [f"{CDN_BASE}/{p}" for p in r["image_paths"]] if CDN_BASE else r["image_paths"]
        manifest["manga"][mid]["chapters"].append({
            "label": f"الفصل {r['chapter_num']}",
            "chNum": float(r["chapter_num"]) if re.match(r"^\d+(\.\d+)?$", r["chapter_num"]) else 0,
            "sourceUrl": r["source_url"],
            "images": images_cdn,
        })
    for mid in manifest["manga"]:
        manifest["manga"][mid]["chapters"].sort(key=lambda c: c["chNum"])

    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ اكتمل: {len(results)} فصل من أصل {len(chapter_urls)}")
    print(f"manifest.json جاهز في {OUTPUT_DIR}/manifest.json")


if __name__ == "__main__":
    asyncio.run(main())
