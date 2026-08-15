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

3) الاستخراج يفحص "سياق" كل صورة (أصولها/parents في الـDOM حتى 5 مستويات)
   ويستبعد أي صورة أصلها يحمل class/id يوحي بأنه قسم "مقترح/مشابه/تعليقات/
   إعلان" — لأن بعض القوالب تحقن ودجات كهذي بنفس وسوم <img> الحقيقية دون أي
   إشارة نصية في رابط الصورة نفسه تدل على أنه ودجت.

3.1) الجمع يتم بتمرير تراكمي واحد فقط لكل الصفحة: يجمع كل عناصر <img> ولكل
   عنصر نسجّل أيضًا "أي محدّدات من قائمة معروفة (Madara وما شابه) يطابقها
   فعليًا" (عبر Element.matches) في نفس الجولة. بعد الجمع مرة واحدة: نستبعد
   صور الودجات حسب السياق، ثم نفضّل الصور الواقعة داخل محدّد معروف (بترتيب
   أولويته) إن كان عددها كافيًا، وإلا نستخدم كل الصور المتبقية — بدون أي
   تمرير إضافي (كان تكرار التمرير لكل محدّد على حدة يسبب دقائق طويلة لفصل
   واحد في مواقع لا تطابق أي محدّد معروف).

3.2) التمرير عبر الصفحة تراكمي لا لقطة واحدة أخيرة — يحل مشكلة الصفحات التي
   تُلغي تحميل (unmount) الصور البعيدة عن منطقة العرض (تحميل كسول/
   virtualization)، وله سقف زمني إجمالي (لا سقف خطوات فقط) يحمي من صفحات
   تنمو باستمرار (ودجت "تحميل المزيد" مثلًا).

4) الصورة يُتحقق من عرضها وطولها معًا قبل الضغط، لأن حد WebP الصارم
   (16383 بكسل لأي بعد) قد يُتجاوز حتى لو كان العرض ضمن الحد المطلوب.

5) الحكم بنجاح/فشل تحميل الصفحة يعتمد على وجود صور مستخرجة فعليًا، وليس على
   إطلاق حدث goto (domcontentloaded/load) بذاته — بعض الصفحات ترسم محتواها
   الحقيقي كاملًا حتى لو تعلّق الحدث نفسه بسبب مورد بطيء غير متعلق بالمحتوى.

6) عند فشل تحميل بايتات صورة، يُتحقق من content-type فعليًا قبل تمريرها
   لـ Pillow، ويُطبع السبب الدقيق بدل رسالة Pillow العامة التي لا تفسّر شيئًا.

7) [مُضاف] الدفع التدريجي الفعلي: إن كان ENABLE_INCREMENTAL_PUSH مفعّلًا
   و GIT_COMMIT_DIR مضبوطًا (تمررهما خطوة الـ workflow)، يُنفَّذ commit+push
   حقيقي (git عبر subprocess، في thread منفصل حتى لا يحجب حلقة الأحداث غير
   المتزامنة) فور نجاح كل فصل — لا بعد اكتمال كل الفصول. في نسخة سابقة كانت
   خطوة الـ workflow تمرّر هذين المتغيّرين لكن السكربت لم يكن يقرأهما إطلاقًا
   (خلل: الدفع "التدريجي" لم يكن يحدث فعليًا، والدفع الحقيقي الوحيد كان
   الدفعة الأخيرة في نهاية الـ job). إن كان ENABLE_INCREMENTAL_PUSH مُعطَّلًا،
   لا يُنفَّذ أي أمر git من هنا إطلاقًا، وتبقى خطوة "الدفع الاحتياطي النهائي"
   في الـ workflow هي المسؤولة عن دفعة واحدة بالنهاية.
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

# سقف أمان لعدد خطوات التمرير التراكمي (فصول بمئات الصور تحتاج خطوات أكثر)
SCROLL_MAX_STEPS = int(os.environ.get("SCROLL_MAX_STEPS", "400"))
SCROLL_STEP_WAIT_MS = int(os.environ.get("SCROLL_STEP_WAIT_MS", "350"))
# سقف زمني إجمالي (بالثواني) للتمرير التراكمي بغضّ النظر عن عدد الخطوات
SCROLL_MAX_TOTAL_SEC = int(os.environ.get("SCROLL_MAX_TOTAL_SEC", "90"))

# إذا فُعِّل هذا يتم استبعاد أي صورة من نطاق (domain) غير النطاق الأغلب بين
# صور الفصل — مُعطَّل افتراضيًا لأن بعض المواقع الشرعية توزّع صورها على أكثر
# من نطاق CDN. يُتحكم به الآن من زر في الـ workflow (strict_domain_filter)
STRICT_DOMAIN_FILTER = os.environ.get("STRICT_DOMAIN_FILTER", "0") == "1"

# الدفع التدريجي: commit+push حقيقي بعد كل فصل ناجح (زر enable_incremental_push
# في الـ workflow). يعمل فقط إن كان GIT_COMMIT_DIR مضبوطًا فعليًا.
ENABLE_INCREMENTAL_PUSH = os.environ.get("ENABLE_INCREMENTAL_PUSH", "true").strip().lower() == "true"
GIT_COMMIT_DIR = os.environ.get("GIT_COMMIT_DIR", "").strip() or None
GIT_BRANCH = os.environ.get("GIT_BRANCH", "output").strip() or "output"

# أقصى بعد مسموح لأي صورة (عرض أو طول) قبل إعادة تحجيمه إجباريًا — يحمي من
# فشل ترميز WebP الذي له حد صارم 16383 بكسل، بغضّ النظر عن إعداد العرض الأقصى
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
    """تشخيصي فقط (رقم تقريبي يُطبع في اللوج) — الاستخراج الفعلي يعتمد على
    التمرير التراكمي في collect_images_while_scrolling وليس على هذا العدّ."""
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
    """تمرير تراكمي واحد فقط لكل الصفحة — يجمع كل عناصر <img> ومعها سياقها
    وأي محدّدات معروفة تطابقها، في نفس الجولة."""
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
    """يحمّل الصورة عبر نفس جلسة متصفح Playwright (كوكيز + بصمة حقيقية).
    يعيد (bytes|None, سبب_الفشل|None) مع إعادة محاولة عند الفشل."""
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


def _git_commit_and_push_sync(commit_dir: str, branch: str, message: str) -> tuple[bool, str]:
    """
    ينفَّذ في thread منفصل (استدعاؤه دومًا عبر asyncio.to_thread) لأن
    subprocess.run حاجب (blocking) ولا يجوز تشغيله مباشرة داخل event loop
    غير متزامن — كان سيُجمّد كل تحميل الصور والفصول التالية أثناء انتظار
    الشبكة لعملية git push.
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

    for attempt in range(1, 4):
        push = _run_git(["push", "origin", f"HEAD:{branch}"], commit_dir)
        if push.returncode == 0:
            return True, "تم الدفع"
        _run_git(["fetch", "origin", branch], commit_dir)
        _run_git(["rebase", f"origin/{branch}"], commit_dir)
        time.sleep(attempt * 2)

    return False, "فشل الدفع بعد عدة محاولات (سيُعالجه الدفع الاحتياطي النهائي بالـ workflow)"


async def push_chapter_incrementally(manga_id: str, chapter_num: str) -> None:
    """
    يُستدعى فور نجاح حفظ صور فصل واحد. لا يفعل شيئًا إن كان الدفع التدريجي
    مُعطَّلًا (ENABLE_INCREMENTAL_PUSH=false) أو GIT_COMMIT_DIR غير مضبوط —
    في هذه الحالة، خطوة "الدفع الاحتياطي النهائي" بالـ workflow هي المسؤولة
    عن دفعة واحدة في نهاية التشغيل.
    """
    if not ENABLE_INCREMENTAL_PUSH or not GIT_COMMIT_DIR:
        return
    message = f"إضافة {manga_id} - الفصل {chapter_num}"
    ok, msg = await asyncio.to_thread(_git_commit_and_push_sync, GIT_COMMIT_DIR, GIT_BRANCH, message)
    print(f"  {'✅' if ok else '⚠️'} دفع تدريجي: {msg}")


async def open_and_collect(browser, chapter_url: str, attempt: int):
    """
    محاولة واحدة لفتح الصفحة واستخراج روابط الصور.
    يعيد (context, روابط_الصور, سبب_الفشل).
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

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة عند أعلى الصفحة (تشخيصي): {found_count}")

    t0 = time.monotonic()
    image_urls = await extract_image_urls(page, chapter_url)
    print(f"  ⏱️ زمن الاستخراج (تمرير واحد): {time.monotonic() - t0:.1f}ث")
    await page.close()

    if not image_urls:
        await context.close()
        reason = "لم يتم تحميل الصفحة أصلًا (انتهت المهلة)" if not navigated else "اكتمل تحميل الصفحة لكن لم يُعثر على صور"
        return None, [], reason
    if not navigated:
        print("  ℹ️ ملاحظة: حدث goto لم يُطلَق (انتهت مهلته) لكن المحتوى الحقيقي كان قد اكتمل فعليًا — نُكمل به")
    print(f"  📊 إجمالي الصور بعد التمرير التراكمي: {len(image_urls)}")
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

    await context.close()

    if not saved_paths:
        return None

    # دفع تدريجي فوري لهذا الفصل (إن كان مفعّلًا) — لا ننتظر بقية الفصول
    await push_chapter_incrementally(manga_id, chapter_num)

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

    print(f"⚙️ الدفع التدريجي: {'مفعّل' if ENABLE_INCREMENTAL_PUSH and GIT_COMMIT_DIR else 'مُعطَّل (دفعة واحدة بالنهاية عبر الـ workflow)'}")
    print(f"⚙️ فلترة النطاق الصارمة: {'مفعّلة' if STRICT_DOMAIN_FILTER else 'مُعطَّلة'}")

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

    # دفعة أخيرة تضمن أن manifest.json نفسه (وأي فصل لم يُدفع لأي سبب) يُحفظ،
    # حتى لو كان الدفع التدريجي مفعّلًا — لأنه دُفع سابقًا فصلًا بفصل قبل أن
    # يُكتب manifest.json (يُكتب بعد كل الفصول)، فلازم دفعة أخيرة صريحة له
    if GIT_COMMIT_DIR:
        await push_chapter_incrementally("manifest", "نهائي")


if __name__ == "__main__":
    asyncio.run(main())
   
