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
   خارج جلسة المتصفح الحقيقية.

3) الاستخراج يفحص "سياق" كل صورة (أصولها في الـDOM حتى 5 مستويات) ويستبعد
   أي صورة أصلها يوحي بأنه ودجت "مقترح/مشابه/إعلان"، ويجمع كل الصور بتمرير
   تراكمي واحد فقط لكل الصفحة (لا تمرير منفصل لكل محدّد CSS مُخمَّن).

4) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط، لأن حد WebP الصارم
   (16383 بكسل لأي بعد) قد يُتجاوز حتى لو كان العرض ضمن الحد المطلوب.

5) الحكم بنجاح/فشل تحميل الصفحة يعتمد على وجود صور مستخرجة فعليًا، وليس على
   إطلاق حدث goto بذاته.

6) عند فشل تحميل بايتات صورة، يُتحقق من content-type فعليًا قبل تمريرها
   لـ Pillow، ويُطبع السبب الدقيق بدل رسالة Pillow العامة غير المفسِّرة.

7) manifest.json يُدمَج بدل إعادة الكتابة الكاملة (يُجلب أحدث نسخة من الفرع
   البعيد فعليًا قبل الكتابة النهائية، وتُدمج فيها فصول هذه التشغيلة).

8) استراتيجية إعادة محاولة الدفع: fetch + reset مختلط (mixed) + إعادة commit
   فوق أحدث نقطة على البعيد (بلا git rebase، هش جدًا مع JSON مُولَّد بالكامل).

9) الدفع التدريجي الفعلي: إن كان ENABLE_INCREMENTAL_PUSH مفعّلًا و
   GIT_COMMIT_DIR مضبوطًا، يُنفَّذ commit+push حقيقي فور نجاح كل فصل.

10) [إصلاح جذري جديد] تجاوز "جدار مانع الإعلانات": بعض المواقع (مثل
    dilar.tube) تعرض صفحة اعتراضية فورية بعد التحميل تطلب تعطيل أي أداة حظر
    إعلانات، مع رابط "متابعة على أي حال" وعدّ تنازلي — طالما هذا الجدار
    موجود، محتوى القراءة الحقيقي (والصور) لا يوجد بالـDOM إطلاقًا مهما طال
    الانتظار أو أُعيدت المحاولة. يُكتشف الجدار بالبحث عن نص رابط التجاوز
    المعروف، يُنتظَر عدّه التنازلي (هامش أمان ٩ث)، ثم يُضغط تلقائيًا.

11) [تحسين جذري جديد] سياق متصفح واحد (context) لكل التشغيلة كاملة بدل سياق
    منفصل لكل فصل: لو موقع يتذكر تجاوز جدار مانع الإعلانات عبر كوكيز أو
    localStorage (شائع جدًا)، إعادة استخدام نفس السياق عبر كل الفصول تعني
    مواجهة الجدار مرة واحدة بالفصل الأول فقط، وتخطّيه تلقائيًا في كل ما بعده
    — توفير وقت حقيقي، وسلوك تصفح أقرب لمستخدم حقيقي (جلسة واحدة مستمرة).
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

WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad", re.I)

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

# نص رابط/زر "تجاوز جدار مانع الإعلانات" — قابل للتوسعة لاحقًا لو صادفنا
# صيغ نصية أخرى بمواقع جديدة
ADBLOCK_WALL_TEXT_PATTERN = re.compile(
    r"continue anyway|proceed anyway|متابعة على أي حال|المتابعة على أي حال|تجاوز والمتابعة",
    re.I,
)

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


async def dump_adblock_wall_diagnostics(page):
    """تشخيص مباشر من نفس بيئة التشغيل الفعلية (لا تخمين): نطبع HTML الزر
    وسياقه القريب، وكل السكربتات المحمّلة بالصفحة، لفهم الآلية الحقيقية
    اللي يعتمد عليها الموقع لتفعيل زر التجاوز قبل أي محاولة إصلاح جديدة."""
    try:
        info = await page.evaluate("""
            () => {
                const btn = document.querySelector('#_fb_continue');
                let container = btn;
                for (let i = 0; i < 3 && container && container.parentElement; i++) {
                    container = container.parentElement;
                }
                return {
                    btnOuter: btn ? btn.outerHTML : null,
                    containerOuter: container ? container.outerHTML.slice(0, 2500) : null,
                    scripts: Array.from(document.scripts).map(s => s.src || ('(inline, ' + (s.textContent||'').length + ' حرف)')),
                };
            }
        """)
        print("  🔍 [تشخيص] HTML الزر:")
        print("     " + str(info.get('btnOuter'))[:800])
        print("  🔍 [تشخيص] الحاوية المحيطة (أول 2500 حرف):")
        print("     " + str(info.get('containerOuter'))[:2500])
        print("  🔍 [تشخيص] السكربتات المحمّلة بالصفحة:")
        for s in info.get('scripts', []):
            print("     - " + s)
    except Exception as e:
        print(f"  ⚠️ تعذّر جمع التشخيص الإضافي: {e}")


async def dismiss_adblock_wall(page, max_wait_ms: int = 12000) -> bool:
    """يكتشف جدار "مانع إعلانات" (مثل dilar.tube) ويتجاوزه. يرجّع True لو
    وُجد الجدار فعليًا وتم التعامل معه، و False لو ما كان موجودًا أصلًا
    (الحالة الشائعة بعد أول فصل بفضل إعادة استخدام نفس السياق).

    ملاحظة تصميم مهمة: زر التجاوز يُولَد بالـDOM فورًا لكنه disabled وغير
    مرئي حتى ينتهي عدّ تنازلي فعلي بالموقع — والمدة الحقيقية غير معروفة
    مسبقًا (قد تطول داخل GitHub Actions لأن طلبات فحص الإعلانات نفسها
    محجوبة على مستوى الشبكة، فتنتظر انتهاء مهلتها بدل فشل فوري). لذلك
    نَستطلِع (poll) جاهزية الزر فعليًا بدل انتظار مدة ثابتة مخمَّنة."""
    try:
        locator = page.get_by_text(ADBLOCK_WALL_TEXT_PATTERN)
        if await locator.count() == 0:
            return False
        print(f"  🧱 اكتُشف جدار \"مانع إعلانات\" — بانتظار تفعّل زر التجاوز (حتى {max_wait_ms//1000}ث)")
        target = locator.first
        elapsed, poll_ms, ready = 0, 1000, False
        while elapsed < max_wait_ms:
            try:
                if await target.is_visible() and await target.is_enabled():
                    ready = True
                    break
            except Exception:
                pass
            await page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
        if not ready:
            print(f"  ⚠️ الزر لم يصبح جاهزًا خلال {max_wait_ms//1000}ث — سنجمع تشخيصًا قبل محاولة أخيرة")
            await dump_adblock_wall_diagnostics(page)
        try:
            await target.click(timeout=3000)
        except Exception:
            try:
                # ملاذ أخير: ضغط قسري عبر JS مباشرة (يتجاوز فحوصات "مرئي/مفعّل"
                # الخاصة بـPlaywright) — قد لا ينجح لو المعالج نفسه يتحقق من
                # حالة disabled داخليًا، لكنه يستحق المحاولة قبل الاستسلام
                await target.evaluate("el => el.click()")
            except Exception as e2:
                print(f"  ⚠️ فشل حتى الضغط القسري: {e2}")
                return False
        await page.wait_for_timeout(1500)
        return True
    except Exception as e:
        print(f"  ⚠️ تعذّرت محاولة تجاوز جدار مانع الإعلانات: {e}")
        return False


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
        # نعدّ فقط الصور اللي طابقت أحد محدّدات محتوى القراءة الفعلية (مو أي
        # صورة بالصفحة) — لأن أقسام "مقترح لك/مانجا مشابهة" أسفل الصفحة تكبر
        # بلا توقف عبر lazy load أثناء التمرير، فتمنع شرط "استقرار العدد
        # الكلي" من التحقق أبدًا حتى لو صور الفصل الحقيقية اكتملت من زمان
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

        # توقف مبكر: صور محتوى القراءة الفعلية استقرت لعدة جولات متتالية —
        # لا داعي نكمل التمرير حتى لو باقي الصفحة (ودجات مقترحة) لسا يكبر
        if content_stable_rounds >= CONTENT_STABLE_ROUNDS_REQUIRED:
            print(f"  ⏱️ استقرت صور محتوى القراءة الفعلية ({cur_content}) لـ{CONTENT_STABLE_ROUNDS_REQUIRED} جولات متتالية — إيقاف التمرير مبكرًا")
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


async def extract_image_urls(page, base_url: str) -> list[str]:
    try:
        items = await collect_images_while_scrolling(page, CONTENT_SELECTORS)
    except Exception:
        items = []

    filtered = _filter_widget_context(items)

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


IMG_FETCH_RETRIES = int(os.environ.get("IMG_FETCH_RETRIES", "3"))
IMG_FETCH_DELAY_MS = int(os.environ.get("IMG_FETCH_DELAY_MS", "120"))


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
                    return body, None
                last_reason = f"جسم الاستجابة فارغ/صغير جدًا ({len(body) if body else 0} بايت)"
            else:
                last_reason = f"status={resp.status} content-type={ctype!r}"
        except Exception as e:
            last_reason = f"استثناء: {e}"
        if attempt < IMG_FETCH_RETRIES:
            await asyncio.sleep(0.6 * attempt)
    return None, last_reason


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def _read_remote_manifest_sync(commit_dir: str, branch: str) -> dict | None:
    """يقرأ manifest.json كما هو على الفرع البعيد حاليًا (بدون التأثير على
    working tree) عبر git show — لا يعتمد على النسخة المحلية القديمة."""
    _run_git(["fetch", "origin", branch], commit_dir)
    show = _run_git(["show", f"origin/{branch}:output/manifest.json"], commit_dir)
    if show.returncode != 0:
        return None
    try:
        return json.loads(show.stdout)
    except Exception:
        return None


def merge_manifest_dict(base: dict, results: list) -> dict:
    """يدمج نتائج هذه التشغيلة داخل manifest.json موجود مسبقًا (بدل إعادة
    بنائه من الصفر) — يستبدل الفصل لو أُعيد معالجته (نفس chNum)، يضيفه لو
    جديد، ويحافظ على كل مانهوا/فصل آخر لم تمسّه هذه التشغيلة بلا تغيير."""
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
    """
    يدفع أي تغييرات موجودة حاليًا في working tree الخاص بالـworktree.
    عند رفض الدفع (الفرع البعيد تقدّم)، لا نستخدم git rebase — عرضة لتعارضات
    دمج نصي سهلة على ملفات JSON مُولَّدة بالكامل حتى لو كانت التغييرات فعليًا
    متوافقة منطقيًا. بدلًا من ذلك: نجلب أحدث نسخة، ونعمل reset مختلط (mixed)
    يُرجع مؤشر الفرع المحلي لآخر نقطة على البعيد دون لمس ملفات القرص إطلاقًا
    (كل ما كان محليًا يتحوّل تلقائيًا لتغييرات غير مُلتَزمة)، ثم نُعيد
    add+commit لحالة القرص الحالية فوق أحدث نسخة مباشرة — بلا أي آلية دمج.
    """
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


async def open_and_collect(context, chapter_url: str, attempt: int):
    """يفتح صفحة جديدة (page) داخل السياق (context) المشترك المُمرَّر —
    السياق نفسه يُنشأ مرة واحدة فقط لكل التشغيلة بالكامل في main()، ما يعني
    الكوكيز وlocalStorage (بما فيها تجاوز أي جدار مانع إعلانات) تُحفظ
    وتُستخدَم تلقائيًا عبر كل الفصول التالية."""
    page = await context.new_page()

    navigated = False
    wait_strategy = "domcontentloaded" if attempt == 1 else "load"
    try:
        await page.goto(chapter_url, wait_until=wait_strategy, timeout=NAV_TIMEOUT_MS)
        navigated = True
    except Exception as e:
        print(f"  ⚠️ تعذّر تحميل الصفحة ({wait_strategy}): {e}")

    if navigated:
        await dismiss_adblock_wall(page)

        if await looks_like_challenge_page(page):
            print("  🛡️ صفحة تحقق/حماية محتملة (Cloudflare أو ما شابه) — انتظار وإعادة تحميل")
            await page.wait_for_timeout(5000)
            try:
                await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
                await dismiss_adblock_wall(page)
            except Exception as e:
                print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    if found_count == 0 and navigated:
        # احتياط: لو ظهر جدار مانع الإعلانات متأخرًا بعد بدء الانتظار
        if await dismiss_adblock_wall(page):
            found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): {found_count}")

    t0 = time.monotonic()
    image_urls = await extract_image_urls(page, chapter_url)
    print(f"  ⏱️ زمن الاستخراج (تمرير واحد): {time.monotonic() - t0:.1f}ث")
    await page.close()

    if not image_urls:
        reason = "لم يتم تحميل الصفحة أصلًا (انتهت المهلة)" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        return [], reason
    if not navigated:
        print("  ℹ️ ملاحظة: حدث goto لم يُطلَق (انتهت مهلته) لكن المحتوى الحقيقي كان قد اكتمل فعليًا — نُكمل به")
    print(f"  📊 إجمالي الصور بعد التمرير التراكمي: {len(image_urls)}")
    return image_urls, ""


async def process_chapter(context, chapter_url: str, index: int, total: int):
    print(f"[{index}/{total}] فتح: {chapter_url}")

    image_urls, fail_reason = [], ""
    for attempt in range(1, RETRY_PER_CHAPTER + 1):
        if attempt > 1:
            print(f"  🔁 إعادة محاولة #{attempt}")
        image_urls, fail_reason = await open_and_collect(context, chapter_url, attempt)
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
        await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

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

    print(f"⚙️ الدفع التدريجي: {'مفعّل' if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR else 'مُعطَّل (دفعة واحدة بالنهاية)'}")
    print(f"⚙️ فلترة النطاق الصارمة: {'مفعّلة' if STRICT_DOMAIN_FILTER else 'مُعطَّلة'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        # سياق واحد فقط لكل التشغيلة (بدل سياق منفصل لكل فصل) — يحافظ على
        # الكوكيز وlocalStorage عبر كل الفصول، فيتخطى أي جدار "مانع إعلانات"
        # تلقائيًا بعد أول فصل، ويقلل عدد الجلسات المنفصلة المفتوحة على الموقع
        context = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 1000},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        for i, url in enumerate(chapter_urls, start=1):
            r = await process_chapter(context, url, i, len(chapter_urls))
            if r:
                results.append(r)
        await context.close()
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
