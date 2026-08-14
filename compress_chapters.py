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

4) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط، لأن حد WebP الصارم
   (16383 بكسل لأي بعد) قد يُتجاوز حتى لو كان العرض ضمن الحد المطلوب.

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
"""
import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

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

# إذا فُعِّل هذا (STRICT_DOMAIN_FILTER=1) يتم استبعاد أي صورة من نطاق (domain)
# غير النطاق الأغلب بين صور الفصل — بعض المواقع تحمّل ودجات التوصيات من
# نطاق خارجي (شبكة إعلانات/خدمة توصيات) مختلف عن نطاق CDN صور المانهوا نفسه.
# مُعطَّل افتراضيًا لأن بعض المواقع الشرعية توزّع صورها على أكثر من نطاق CDN.
STRICT_DOMAIN_FILTER = os.environ.get("STRICT_DOMAIN_FILTER", "0") == "1"

# أقصى بعد مسموح لأي صورة (عرض أو طول) قبل إعادة تحجيمه إجباريًا — يحمي من
# فشل ترميز WebP الذي له حد صارم 16383 بكسل، بغضّ النظر عن إعداد العرض الأقصى
WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad", re.I)

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


def compress_image(raw_bytes: bytes, max_width: int, quality: int) -> bytes:
    img = Image.open(BytesIO(raw_bytes))
    img = img.convert("RGB") if img.mode in ("P", "CMYK") else img

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

    out = BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


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


async def open_and_collect(browser, chapter_url: str, attempt: int):
    """
    محاولة واحدة لفتح الصفحة واستخراج روابط الصور.
    يعيد (context, روابط_الصور, سبب_الفشل) — الـcontext يبقى مفتوحًا لأن
    تحميل الصور لاحقًا يحتاج نفس الجلسة (كوكيز) التي فتحت الصفحة بنجاح.
    """
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
        await context.close()
        reason = "لم يتم تحميل الصفحة أصلًا (انتهت المهلة)" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        return None, [], reason
    if not navigated:
        print("  ℹ️ ملاحظة: حدث goto لم يُطلَق (انتهت مهلته) لكن المحتوى الحقيقي كان قد اكتمل فعليًا — نُكمل به")
    return context, image_urls, ""


async def process_chapter(browser, chapter_url: str, index: int, total: int):
    print(f"[{index}/{total}] فتح: {chapter_url}")

    context, image_urls, fail_reason = None, [], ""
    for attempt in range(1, RETRY_PER_CHAPTER + 1):
        if attempt > 1:
            print(f"  🔁 إعادة محاولة #{attempt}")
        context, image_urls, fail_reason = await open_and_collect(browser, chapter_url, attempt)
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
            compressed = compress_image(raw, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            print(f"  ✅ {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
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

    await context.close()

    if not saved_paths:
        return None

    return {
        "manga_id": manga_id,
        "chapter_num": chapter_num,
        "source_url": chapter_url,
        "image_paths": saved_paths,
    }


async def main():
    chapter_urls = [u for u in re.split(r'[\s,،؛;]+', CHAPTER_URLS_RAW.strip()) if u.startswith('http')]
    print(f"📋 تم استخراج {len(chapter_urls)} رابط صالح من المدخلات:")
    for u in chapter_urls:
        print(f"   - {u}")
    if not chapter_urls:
        print("لا توجد روابط فصول في المدخلات (CHAPTER_URLS فارغة)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for i, url in enumerate(chapter_urls, start=1):
            r = await process_chapter(browser, url, i, len(chapter_urls))
            if r:
                results.append(r)
        await browser.close()

    manifest = {"manga": {}}
    for r in results:
        mid = r["manga_id"]
        if mid not in manifest["manga"]:
            manifest["manga"][mid] = {
                "name": mid.split("__", 1)[-1].replace("-", " "),
                "chapters": []
            }
        images_cdn = [f"{CDN_BASE}/{p}" for p in r["image_paths"]] if CDN_BASE else r["image_paths"]
        manifest["manga"][mid]["chapters"].append({
            "label": f"الفصل {r['chapter_num']}",
            "chNum": float(r["chapter_num"]) if re.match(r"^\d+(\.\d+)?$", r["chapter_num"]) else 0,
            "sourceUrl": r["source_url"],
            "images": images_cdn,
        })

    for mid in manifest["manga"]:
        manifest["manga"][mid]["chapters"].sort(key=lambda c: c["chNum"])

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ اكتمل: {len(results)} فصل من أصل {len(chapter_urls)}")
    print(f"manifest.json جاهز في {OUTPUT_DIR}/manifest.json")


if __name__ == "__main__":
    asyncio.run(main())
