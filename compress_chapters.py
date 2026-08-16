#!/usr/bin/env python3
"""
يقرأ قائمة روابط فصول (سطر لكل رابط) من متغيرات البيئة، يستخرج روابط الصور،
يحمّلها، يضغطها فعليًا بمكتبة Pillow، ويحفظها في مجلد الإخراج مع ملف
manifest.json يصف كل مانهوا وفصولها وروابط صورها النهائية.

============================== بروفايلات المواقع ==============================
بدل محاولة "تخمين" الأسلوب المناسب من الصفر لكل موقع (وهو ما كان يهدر دقائق
كاملة أحيانًا)، السكربت يقرأ SITE_PROFILE من البيئة (تختاره من قائمة منسدلة في
الـ workflow) ويطبّق مباشرة الأسلوب المثبت تجريبيًا لهذا الموقع تحديدًا:

- azorafly    → HTTP مباشر بدون متصفح إطلاقًا. الصور موجودة كـ noscript أو
                data-src في HTML الثابت نفسه، ولا يوجد حجب Cloudflare ولا
                حماية سرقة (hotlink) تمنع تحميلها بطلب عادي. الأسرع والأخف
                من كل البروفايلات — لا يُطلق متصفح Chromium إطلاقًا لهذا الموقع.

- mangatuk    → يحتاج متصفح حقيقي (كوكيز/جلسة Playwright لتحميل الصور نفسها،
                وإلا فشل "cannot identify image"). لا يحتاج تمريرًا تراكميًا
                طويلًا (الصور تظهر مباشرة دون virtualization)، ولا فلترة
                ودجات (لا يوجد قسم "مقترح" يتداخل مع محتوى القراءة). يتساهل
                مع تأخر حدث goto (الفصل الأول تحديدًا كان يتعلّق أحيانًا بسبب
                مورد بطيء غير متعلق بالمحتوى — نعتمد على وجود صور حقيقية لا
                على الحدث نفسه). فصوله الطويلة (مئات الصور) عرضة لتحديد معدل
                طلبات، فيُعتمد عليه إعادة محاولة + تأخير بين كل صورة أكثر.

- mangatime   → يحتاج متصفح حقيقي + تمرير تراكمي إجباري (تحميل كسول حقيقي
                يُلغي الصور البعيدة عن الشاشة من الـDOM/virtualization)، ويحتاج
                فلترة سياق الودجات (قسم "مانجا مقترحة" يحقن صورًا بنفس وسوم
                <img> الحقيقية ضمن نفس منطقة القراءة تقريبًا). لا يطابق أي
                محدّد قالب معروف (ليس Madara)، فيعتمد على الاستخراج العام.

- manga_starz → غير مدعوم تلقائيًا. محمي بتحدي Cloudflare كامل يكتشف بصمة
                الأتمتة حتى مع متصفح Chromium حقيقي مؤتمت (لا حل معروف حاليًا
                غير بروكسي residential حقيقي، لم يُختبر). السكربت يتوقف فورًا
                لهذا البروفايل برسالة واضحة بدل إهدار وقت تشغيل على محاولات
                ستفشل حتمًا.

- auto        → السلوك العام الآمن الافتراضي لأي موقع لم نُشخّصه بعد: متصفح
                حقيقي + تمرير تراكمي كامل + فلترة ودجات (يغطي أوسع نطاق حالات
                حتى لو لم يكن الأمثل أداءً لموقع بعينه).
================================================================================

ملاحظات تصميم عامة أخرى (تراكمت من التشخيص الفعلي عبر المحادثة):

1) لا يعتمد أي مسار متصفح على "networkidle" لاعتبار الصفحة جاهزة — مواقع فيها
   إعلانات/تتبّع لا تدخل خمول شبكة أبدًا حتى لو اكتمل المحتوى فعليًا.

2) الحكم بنجاح/فشل تحميل صفحة (في مسار المتصفح) يعتمد على وجود صور مستخرجة
   فعليًا، لا على إطلاق حدث goto بذاته — هذا سلوك عام مفيد لكل المواقع، وليس
   خاصًا ببروفايل بعينه، فأبقيناه غير مرتبط بالبروفايل عمدًا.

3) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط (حد WebP الصارم 16383 بكسل).

4) manifest.json يُدمَج مع أحدث نسخة على الفرع البعيد فعليًا قبل كل كتابة —
   لا يُعاد بناؤه من الصفر — لتفادي تعارضات "add/add" عند الدفع.

5) استراتيجية إعادة محاولة الدفع: fetch + reset مختلط + إعادة commit، بدل
   git rebase الهش مع ملفات JSON مُولَّدة بالكامل.

6) الدفع التدريجي الفعلي (commit+push بعد كل فصل ناجح) يعمل إن كان
   ENABLE_INCREMENTAL_PUSH مفعّلًا و GIT_COMMIT_DIR مضبوطًا.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from PIL import Image
from io import BytesIO
from playwright.async_api import async_playwright

QUALITY = int(os.environ.get("IMG_QUALITY", "25"))
MAX_WIDTH = int(os.environ.get("IMG_MAX_WIDTH", "700"))
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

IMG_FETCH_RETRIES = int(os.environ.get("IMG_FETCH_RETRIES", "3"))
IMG_FETCH_DELAY_MS = int(os.environ.get("IMG_FETCH_DELAY_MS", "120"))

WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

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

CHALLENGE_MARKERS = [
    "just a moment", "checking your browser", "attention required",
    "cf-browser-verification", "ddos protection by", "verifying you are human",
    "enable javascript and cookies",
]

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

# ============================== بروفايلات المواقع ==============================
SITE_PROFILE = os.environ.get("SITE_PROFILE", "auto").strip().lower()

PROFILES = {
    "azorafly": {
        "label": "أزورافلاي",
        "fetch_mode": "http",
    },
    "mangatuk": {
        "label": "مانجا توك",
        "fetch_mode": "browser",
        "do_scroll": False,
        "do_widget_filter": False,
    },
    "mangatime": {
        "label": "مانجا تايم",
        "fetch_mode": "browser",
        "do_scroll": True,
        "do_widget_filter": True,
    },
    "manga_starz": {
        "label": "ستار مانجا",
        "fetch_mode": "unsupported",
        "unsupported_reason": (
            "محمي بتحدي Cloudflare كامل يكتشف بصمة الأتمتة حتى مع متصفح "
            "Chromium حقيقي مؤتمت. لا حل معروف تلقائيًا حاليًا — يحتاج نسخ "
            "روابط الصور يدويًا من متصفح حقيقي بعد اجتياز التحدي، أو بروكسي "
            "residential حقيقي (لم يُختبر بعد)."
        ),
    },
    "auto": {
        "label": "تلقائي (عام)",
        "fetch_mode": "browser",
        "do_scroll": True,
        "do_widget_filter": True,
    },
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


def dedupe(urls: list[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        if u not in seen and not IGNORE_PATTERN.search(u):
            seen.add(u)
            out.append(u)
    return out


# ---------------------------- مسار HTTP المباشر (azorafly) ----------------------------

def extract_images_from_html(html: str, base_url: str) -> list[str]:
    """يستخرج روابط الصور من نص HTML خام دون تنفيذ جافاسكربت. يفضّل noscript
    (بديل حقيقي للتحميل الكسول)، ثم data-src/data-lazy-src/data-original لكل
    <img>، وإلا src العادي."""
    noscript_blocks = re.findall(r"<noscript>(.*?)</noscript>", html, re.I | re.S)
    found = []
    for block in noscript_blocks:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', block):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

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
            found.append(urljoin(base_url, u))
    if found:
        return dedupe(found)

    found = [urljoin(base_url, m.group(0)) for m in
             re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(found)


def fetch_via_http_simple_sync(chapter_url: str) -> tuple[list[str], str]:
    """جلب HTML ثابت بطلب عادي بدون متصفح — كافٍ تمامًا لمواقع مثل أزورافلاي
    التي لا تستخدم حماية Cloudflare ولا حماية سرقة (hotlink) على الصور."""
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    try:
        resp = requests.get(chapter_url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        return [], f"فشل الطلب المباشر: {e}"
    html = resp.text
    if any(m in html.lower() for m in CHALLENGE_MARKERS):
        return [], "صفحة تحقق/حماية ظهرت حتى بطلب مباشر — هذا البروفايل غير مناسب لهذا الرابط تحديدًا"
    urls = extract_images_from_html(html, chapter_url)
    if not urls:
        return [], "لم يُعثر على صور في HTML الثابت"
    return urls, ""


def fetch_image_bytes_http_sync(img_url: str, referer: str) -> tuple[bytes | None, str | None]:
    last_reason = "سبب غير معروف"
    for attempt in range(1, IMG_FETCH_RETRIES + 1):
        try:
            resp = requests.get(img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=20)
            ctype = resp.headers.get("content-type", "")
            if resp.ok and (ctype.startswith("image/") or ctype == ""):
                if resp.content and len(resp.content) >= 500:
                    return resp.content, None
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


# ---------------------------- مسار المتصفح (mangatuk / mangatime / auto) ----------------------------

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


async def collect_images_while_scrolling(page, content_selectors: list[str]) -> list[dict]:
    """تمرير تراكمي كامل (مطلوب فقط لمواقع فيها تحميل كسول حقيقي/virtualization
    مثل mangatime — do_scroll=False يتخطى هذا كليًا لصالح لقطة واحدة سريعة)."""
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

    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await page.wait_for_timeout(300)

    start = time.monotonic()
    stable_rounds = 0
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
            items = await page.eval_on_selector_all("img", COLLECT_IMAGES_JS, content_selectors)
            merge(items)
        except Exception:
            pass

    return [{"url": u, "ctx": v["ctx"], "matched": v["matched"]} for u, v in seen.items()]


async def snapshot_images(page, content_selectors: list[str]) -> list[dict]:
    """لقطة واحدة سريعة (بدون تمرير) — تكفي لمواقع لا تستخدم تحميلًا كسولًا
    حقيقيًا مرتبطًا بالتمرير (mangatuk)، وأسرع بكثير من التمرير التراكمي."""
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

    noscript_imgs = await page.eval_on_selector_all("noscript", "els => els.map(e => e.innerHTML)")
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    html = await page.content()
    found = [urljoin(base_url, m.group(0)) for m in
             re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(found)


async def fetch_image_bytes(context, img_url: str, referer: str):
    """تحميل عبر جلسة المتصفح نفسها (كوكيز حقيقية) — ضروري لمواقع مثل
    mangatuk التي ترفض تحميل الصور من خارج جلسة متصفح حقيقية."""
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


async def open_and_collect(browser, chapter_url: str, attempt: int, profile: dict):
    context = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 1000},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
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
        except Exception as e:
            print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): {found_count}")

    t0 = time.monotonic()
    image_urls = await extract_image_urls(page, chapter_url, profile["do_scroll"], profile["do_widget_filter"])
    print(f"  ⏱️ زمن الاستخراج: {time.monotonic() - t0:.1f}ث")
    await page.close()

    # عام لكل المواقع (وليس خاصًا ببروفايل بعينه): الحكم بالنجاح على وجود صور
    # مستخرجة فعليًا، لا على إطلاق حدث goto بذاته — حل مشكلة الفصل الأول في
    # mangatuk حيث كانت الصفحة ترسم محتواها الحقيقي كاملًا رغم تعلّق الحدث
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
    img = img.convert("RGB") if img.mode in ("P", "CMYK") else img

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


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def _read_remote_manifest_sync(commit_dir: str, branch: str) -> dict | None:
    _run_git(["fetch", "origin", branch], commit_dir)
    show = _run_git(["show", f"origin/{branch}:output/manifest.json"], commit_dir)
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
        entry = manifest["manga"].setdefault(mid, {
            "name": mid.split("__", 1)[-1].replace("-", " "),
            "chapters": [],
        })
        chNum = float(r["chapter_num"]) if re.match(r"^\d+(\.\d+)?$", r["chapter_num"]) else 0
        images_cdn = [f"{CDN_BASE}/{p}" for p in r["image_paths"]] if CDN_BASE else r["image_paths"]
        new_chapter = {
            "label": f"الفصل {r['chapter_num']}",
            "chNum": chNum,
            "sourceUrl": r["source_url"],
            "images": images_cdn,
        }
        replaced = False
        for idx, ch in enumerate(entry["chapters"]):
            if ch.get("chNum") == chNum:
                entry["chapters"][idx] = new_chapter
                replaced = True
                break
        if not replaced:
            entry["chapters"].append(new_chapter)

    for mid in manifest["manga"]:
        manifest["manga"][mid]["chapters"].sort(key=lambda c: c["chNum"])
    return manifest


def _commit_and_push_sync(commit_dir: str, branch: str, message: str, max_attempts: int = 5) -> tuple[bool, str]:
    add = _run_git(["add", "output"], commit_dir)
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

        _run_git(["fetch", "origin", branch], commit_dir)
        _run_git(["reset", f"origin/{branch}"], commit_dir)
        _run_git(["add", "output"], commit_dir)
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
    """يعيد (context_أو_None, روابط_الصور, سبب_الفشل) بحسب أسلوب الجلب في
    البروفايل — مسار HTTP مباشر لا يحتاج/ينشئ أي context متصفح إطلاقًا."""
    if profile["fetch_mode"] == "http":
        fail_reason = ""
        for attempt in range(1, RETRY_PER_CHAPTER + 1):
            if attempt > 1:
                print(f"  🔁 إعادة محاولة طلب مباشر #{attempt}")
            image_urls, fail_reason = await asyncio.to_thread(fetch_via_http_simple_sync, chapter_url)
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

    async def download(img_url: str):
        if profile["fetch_mode"] == "http":
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

    result = {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "source_url": chapter_url,
        "image_paths": saved_paths,
    }

    if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR:
        remote = await asyncio.to_thread(_read_remote_manifest_sync, GIT_COMMIT_DIR, GIT_BRANCH)
        merged = merge_manifest_dict(remote or {}, [result])
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await push_now(f"إضافة {manga_id} - الفصل {chapter_num}")

    return result


async def main():
    chapter_urls = [u for u in re.split(r'[\s,،؛;]+', CHAPTER_URLS_RAW.strip()) if u.startswith('http')]
    print(f"📋 تم استخراج {len(chapter_urls)} رابط صالح من المدخلات:")
    for u in chapter_urls:
        print(f"   - {u}")
    if not chapter_urls:
        print("لا توجد روابط فصول في المدخلات (CHAPTER_URLS فارغة)")
        sys.exit(1)

    profile = get_profile()
    print(f"⚙️ بروفايل الموقع: {profile['label']} ({SITE_PROFILE})")

    if profile["fetch_mode"] == "unsupported":
        print(f"🚫 {profile['label']} غير مدعوم تلقائيًا: {profile.get('unsupported_reason', '')}")
        sys.exit(1)

    print(f"⚙️ الدفع التدريجي: {'مفعّل' if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR else 'مُعطَّل (دفعة واحدة بالنهاية)'}")
    print(f"⚙️ فلترة النطاق الصارمة: {'مفعّلة' if STRICT_DOMAIN_FILTER else 'مُعطَّلة'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    if profile["fetch_mode"] == "http":
        # لا حاجة لإطلاق Chromium إطلاقًا لهذا البروفايل — توفير وقت تشغيل حقيقي
        print("🚀 بروفايل HTTP مباشر — لن يُطلَق متصفح Chromium لهذه التشغيلة")
        for i, url in enumerate(chapter_urls, start=1):
            r = await process_chapter(None, url, i, len(chapter_urls), profile)
            if r:
                results.append(r)
    else:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            for i, url in enumerate(chapter_urls, start=1):
                r = await process_chapter(browser, url, i, len(chapter_urls), profile)
                if r:
                    results.append(r)
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
    print(f"\n✅ اكتمل: {len(results)} فصل من أصل {len(chapter_urls)}")
    print(f"manifest.json جاهز في {OUTPUT_DIR}/manifest.json")

    if GIT_COMMIT_DIR:
        ok, msg = await asyncio.to_thread(_commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, "تحديث manifest.json ونتائج التشغيل")
        print(f"{'✅' if ok else '⚠️'} الدفع النهائي: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
