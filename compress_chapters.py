#!/usr/bin/env python3
"""
يقرأ قائمة روابط فصول (سطر لكل رابط) من متغيرات البيئة، يفتح كل صفحة بمتصفح
Chromium حقيقي مؤتمت (Playwright)، يستخرج روابط الصور، يحمّلها، يضغطها فعليًا
بمكتبة Pillow، ويحفظها في مجلد الإخراج مع ملف manifest.json.

[محدَّث] تم إصلاح مشكلة "cannot identify image file": السبب الجذري كان أن
دالة تحميل الصورة تعتبر أي رد HTTP ناجح بحجم ≥ 500 بايت "صورة صالحة" بدون
التحقق فعليًا من أنها صورة قابلة للفك — فحين يفعّل السيرفر حظر معدل طلبات
مؤقت (rate limiting) ويرد بصفحة تحذير صغيرة بحالة 200 OK، كانت تُقبل خطأً
وتنفجر لاحقًا عند الضغط، دون أن تدخل في نظام إعادة المحاولة أصلًا.
"""
import asyncio
import json
import os
import re
import sys
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

WEBP_HARD_LIMIT = 16000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad", re.I)

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

IMG_SRC_JS = """els => els.map(e => e.getAttribute('data-src') || e.getAttribute('data-lazy-src')
     || e.getAttribute('data-original') || e.currentSrc || e.src).filter(Boolean)"""


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


async def extract_image_urls(page, base_url: str) -> list[str]:
    for selector in CONTENT_SELECTORS:
        try:
            urls = await page.eval_on_selector_all(selector, IMG_SRC_JS)
        except Exception:
            urls = []
        found = [urljoin(base_url, u) for u in urls if u and not u.startswith("data:")]
        if len(found) >= 3:
            return dedupe(found)

    noscript_imgs = await page.eval_on_selector_all("noscript", "els => els.map(e => e.innerHTML)")
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    imgs = await page.eval_on_selector_all("img", IMG_SRC_JS)
    found = [urljoin(base_url, u) for u in imgs if u and not u.startswith("data:")]
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


IMG_FETCH_RETRIES = int(os.environ.get("IMG_FETCH_RETRIES", "5"))
IMG_FETCH_DELAY_MS = int(os.environ.get("IMG_FETCH_DELAY_MS", "450"))
IMG_FETCH_BACKOFF_BASE_S = float(os.environ.get("IMG_FETCH_BACKOFF_BASE_S", "1.5"))


def _looks_like_valid_image(body: bytes) -> bool:
    """
    [مضاف] يتحقق أن البايتات صورة صالحة فعليًا وليست صفحة HTML/JSON صغيرة
    (تحذير حظر معدل طلبات، صفحة خطأ...) تمرّ خطأً من فحص "الحجم ≥ 500 بايت
    + حالة HTTP ناجحة" القديم. Image.verify() يتحقق من سلامة بنية الصورة
    دون فك تشفيرها بالكامل، فهو رخيص وسريع بما يكفي ليُستخدم على كل صورة.
    """
    try:
        img = Image.open(BytesIO(body))
        img.verify()
        return True
    except Exception:
        return False


async def fetch_image_bytes(context, img_url: str, referer: str):
    """
    يحمّل الصورة عبر نفس جلسة متصفح Playwright (كوكيز + بصمة حقيقية).

    [محدَّث] لا يكفي أن يرد السيرفر بحالة HTTP ناجحة وحجم بايتات معقول: عند
    تفعيل حظر معدل الطلبات المؤقت (rate limiting) — وهو الحالة الأشيع في
    الفصول الطويلة (مئات الصور على نفس الجلسة المتتالية) — كثير من
    السيرفرات/الـCDN ترد بحالة 200 OK وجسم استجابة صغير (صفحة تحذير) بدل
    رفض صريح، فيمر هذا الجسم من فحص الحجم القديم بسهولة (أكبر من 500 بايت)
    ويُقبل خطأً كـ"صورة محمّلة بنجاح"، ثم ينفجر لاحقًا عند فك تشفيره فعليًا
    كصورة أثناء الضغط — وهذا بالضبط مصدر أخطاء "cannot identify image file"
    التي كانت لا تُعاد محاولتها أبدًا لأنها كانت تُكتشف بعد فوات الأوان.
    الآن يتم التحقق من صحة الصورة *هنا*، بحيث تدخل هذه الحالة تلقائيًا ضمن
    حلقة إعادة المحاولة والتأخير المتصاعد (backoff) أدناه بدل أن تُفلت منها.

    فاصل التأخير المتصاعد بين المحاولات مُطوَّل عمدًا (1.5s × رقم المحاولة
    بدل 0.6s سابقًا) لإعطاء نافذة الحظر المؤقتة فرصة أكبر للانتهاء فعليًا،
    ولتقليل وتيرة الطلبات شبه الثابتة التي تُسهّل على أي جدار حماية (WAF)
    التعرف على نمط "بوت".
    """
    for attempt in range(1, IMG_FETCH_RETRIES + 1):
        try:
            resp = await context.request.get(
                img_url, headers={"Referer": referer, "User-Agent": UA}, timeout=20000,
            )
            if resp.ok:
                body = await resp.body()
                if body and len(body) >= 500 and _looks_like_valid_image(body):
                    return body
        except Exception:
            pass
        if attempt < IMG_FETCH_RETRIES:
            await asyncio.sleep(IMG_FETCH_BACKOFF_BASE_S * attempt)
    return None


async def open_and_collect(browser, chapter_url: str, attempt: int):
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
        raw = await fetch_image_bytes(context, img_url, chapter_url)
        if not raw:
            print(f"  ⚠️ فشلت صورة {i}: تعذّر تحميل بايتات صورة صالحة بعد {IMG_FETCH_RETRIES} محاولات")
            failed_indices.append(i)
            continue
        try:
            compressed = compress_image(raw, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            print(f"  ✅ {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
        except Exception as e:
            # [محدَّث] الآن نُضيف هذه الحالة أيضًا لقائمة إعادة المحاولة
            # النهائية بدل إهمالها كما كان يحدث سابقًا.
            print(f"  ⚠️ فشلت صورة {i} أثناء الضغط: {e}")
            failed_indices.append(i)
        await asyncio.sleep(IMG_FETCH_DELAY_MS / 1000)

    if failed_indices:
        print(f"  🔁 إعادة محاولة نهائية لـ {len(failed_indices)} صورة فشلت...")
        still_failed = []
        for i in failed_indices:
            img_url = image_urls[i - 1]
            raw = await fetch_image_bytes(context, img_url, chapter_url)
            if raw:
                try:
                    compressed = compress_image(raw, MAX_WIDTH, QUALITY)
                    filename = f"{i:03d}.webp"
                    (chapter_dir / filename).write_bytes(compressed)
                    saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
                    print(f"  ✅ (إعادة محاولة) {i}/{len(image_urls)} — {len(raw)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
                except Exception as e:
                    print(f"  ⚠️ فشلت صورة {i} أثناء الضغط بعد إعادة المحاولة: {e}")
                    still_failed.append(i)
            else:
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
