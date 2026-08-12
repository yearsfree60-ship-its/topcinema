#!/usr/bin/env python3
"""
يقرأ قائمة روابط فصول (سطر لكل رابط) من متغيرات البيئة، يستخرج روابط الصور،
يحمّلها، يضغطها فعليًا بمكتبة Pillow، ويحفظها في مجلد الإخراج مع ملف
manifest.json يصف كل مانهوا وفصولها وروابط صورها النهائية.

استراتيجية الاستخراج (من الأخف إلى الأثقل):
1) طلب HTTP مباشر بدون متصفح (requests) — أسرع بكثير، ولا يحمل بصمة "متصفح
   مؤتمت" التي تستهدفها بعض أنظمة الحماية (Cloudflare/WAF ونحوها). كثير من
   مواقع المانجا تُخرج الصور مباشرة داخل HTML الأساسي دون أي جافاسكربت، فهذا
   يكفي وحده لمعظم المواقع.
2) إن فشل الطلب المباشر (صفر صور، أو صفحة تحقق/حماية)، ننتقل لمتصفح Chromium
   حقيقي مؤتمت عبر Playwright، وهذا يمرّ تلقائيًا أغلب أنظمة التحميل الكسول
   التي تحتاج تنفيذ جافاسكربت (غير مضمون 100% مع الحماية المتقدمة التي تستهدف
   المتصفحات المؤتمتة بالتحديد).
"""
import asyncio
import json
import os
import re
import sys
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
CDN_BASE = os.environ.get("CDN_BASE", "")  # مثال: https://cdn.jsdelivr.net/gh/USER/REPO@output

# مهلات وسلوك التحميل — قابلة للتعديل عبر متغيرات البيئة بدون تعديل الكود
NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))
CONTENT_WAIT_MS = int(os.environ.get("CONTENT_WAIT_MS", "20000"))
CONTENT_POLL_MS = int(os.environ.get("CONTENT_POLL_MS", "800"))
RETRY_PER_CHAPTER = int(os.environ.get("RETRY_PER_CHAPTER", "2"))
# أقل عدد صور نعتبر عنده نتيجة الطلب المباشر "ناجحة" (يمنع الوقوع في فخ صفحة
# تحقق/حماية تحتوي صورة شعار واحدة فقط)
MIN_IMAGES_HTTP = int(os.environ.get("MIN_IMAGES_HTTP", "2"))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

IGNORE_PATTERN = re.compile(r"logo|icon|avatar|sprite|placeholder|loading\.gif|banner-ad", re.I)
IMG_EXT_PATTERN = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)

# عبارات شائعة في صفحات تحقق/حماية (Cloudflare وما شابه) — لاكتشافها والتعامل معها
CHALLENGE_MARKERS = [
    "just a moment", "checking your browser", "attention required",
    "cf-browser-verification", "ddos protection by", "verifying you are human",
    "enable javascript and cookies",
]


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


def extract_images_from_html(html: str, base_url: str) -> list[str]:
    """
    يستخرج روابط الصور من نص HTML خام (بدون تنفيذ جافاسكربت). يفضّل بدائل
    التحميل الكسول الحقيقية (data-src/data-lazy-src/data-original) إن وجدت
    داخل نفس وسم <img>، وإلا يستخدم src العادي — هذا يغطي أغلب المواقع سواء
    كانت تُخرج الصور مباشرة (كما هو الحال هنا) أو عبر placeholders بسيطة.
    """
    found = []
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
    # احتياط أخير: أي رابط بامتداد صورة داخل الكود الكامل
    found = [urljoin(base_url, m.group(0)) for m in
             re.finditer(r'https?://[^\s"\'<>\\]+?\.(?:jpg|jpeg|png|webp|avif)', html)]
    return dedupe(found)


def fetch_via_http(chapter_url: str) -> list[str]:
    """
    محاولة أولى وأسرع: طلب HTTP مباشر بدون متصفح. لا تحمل بصمة "متصفح مؤتمت"،
    فتتجاوز أنظمة الحماية التي تستهدف تحديدًا Playwright/Selenium ونحوها.
    """
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    }
    try:
        resp = requests.get(chapter_url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ⚠️ فشل الطلب المباشر (HTTP): {e}")
        return []

    html = resp.text
    if any(marker in html.lower() for marker in CHALLENGE_MARKERS):
        print("  🛡️ الطلب المباشر أعاد صفحة تحقق/حماية — سيتم تجربة المتصفح")
        return []

    return extract_images_from_html(html, chapter_url)


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


async def extract_image_urls_from_page(page, base_url: str) -> list[str]:
    noscript_imgs = await page.eval_on_selector_all(
        "noscript", "els => els.map(e => e.innerHTML)"
    )
    found = []
    for html in noscript_imgs:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html):
            found.append(urljoin(base_url, m.group(1)))
    if found:
        return dedupe(found)

    imgs = await page.eval_on_selector_all(
        "img",
        """els => els.map(e => e.getAttribute('data-src') || e.getAttribute('data-lazy-src')
             || e.getAttribute('data-original') || e.currentSrc || e.src)"""
    )
    found = [urljoin(base_url, u) for u in imgs if u and not u.startswith("data:")]
    if found:
        return dedupe(found)

    html = await page.content()
    return extract_images_from_html(html, base_url)


def compress_image(raw_bytes: bytes, max_width: int, quality: int) -> bytes:
    img = Image.open(BytesIO(raw_bytes))
    img = img.convert("RGB") if img.mode in ("P", "CMYK") else img
    if img.width > max_width:
        new_h = int(img.height * (max_width / img.width))
        img = img.resize((max_width, new_h), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


async def open_and_collect_via_browser(browser, chapter_url: str, attempt: int) -> tuple[list[str], str]:
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
        print(f"  ⚠️ تعذّر تحميل الصفحة بالمتصفح ({wait_strategy}): {e}")

    if navigated and await looks_like_challenge_page(page):
        print("  🛡️ صفحة تحقق/حماية محتملة عبر المتصفح — انتظار وإعادة تحميل")
        await page.wait_for_timeout(5000)
        try:
            await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            print(f"  ⚠️ فشلت إعادة التحميل بعد صفحة التحقق: {e}")

    found_count = await wait_for_real_images(page, CONTENT_WAIT_MS, CONTENT_POLL_MS)
    print(f"  🖼️ صور حقيقية مكتشفة عبر المتصفح قبل الاستخراج: {found_count}")

    image_urls = await extract_image_urls_from_page(page, chapter_url)
    await context.close()

    if not navigated:
        return image_urls, "لم يتم تحميل الصفحة أصلًا بالمتصفح (انتهت المهلة)"
    if not image_urls:
        return image_urls, "اكتمل تحميل الصفحة بالمتصفح لكن لم يُعثر على صور"
    return image_urls, ""


async def process_chapter(browser, chapter_url: str, index: int, total: int):
    print(f"[{index}/{total}] فتح: {chapter_url}")

    # الخطوة 1: طلب مباشر بدون متصفح — أسرع ويتجاوز حماية تستهدف المتصفحات المؤتمتة
    print("  🌐 محاولة طلب مباشر (بدون متصفح)...")
    image_urls = await asyncio.to_thread(fetch_via_http, chapter_url)
    fail_reason = ""

    if len(image_urls) >= MIN_IMAGES_HTTP:
        print(f"  ✅ نجح الطلب المباشر: {len(image_urls)} صورة (بدون حاجة لمتصفح)")
    else:
        if image_urls:
            print(f"  ↪️ الطلب المباشر أعاد {len(image_urls)} صورة فقط (أقل من الحد {MIN_IMAGES_HTTP}) — تجربة المتصفح")
        else:
            print("  ↪️ الطلب المباشر لم يفلح — الانتقال إلى المتصفح المؤتمت")
        image_urls = []
        for attempt in range(1, RETRY_PER_CHAPTER + 1):
            if attempt > 1:
                print(f"  🔁 إعادة محاولة بالمتصفح #{attempt}")
            image_urls, fail_reason = await open_and_collect_via_browser(browser, chapter_url, attempt)
            if image_urls:
                break

    if not image_urls:
        print(f"  ❌ {fail_reason or 'لم يُعثر على صور في هذا الفصل'}")
        return None

    manga_id, chapter_num = manga_slug_from_url(chapter_url)
    chapter_dir = OUTPUT_DIR / manga_id / f"ch-{chapter_num}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for i, img_url in enumerate(image_urls, start=1):
        try:
            resp = requests.get(img_url, headers={"User-Agent": UA, "Referer": chapter_url}, timeout=20)
            resp.raise_for_status()
            compressed = compress_image(resp.content, MAX_WIDTH, QUALITY)
            filename = f"{i:03d}.webp"
            (chapter_dir / filename).write_bytes(compressed)
            saved_paths.append(str((chapter_dir / filename).relative_to(OUTPUT_DIR)))
            print(f"  ✅ {i}/{len(image_urls)} — {len(resp.content)//1024}ك.ب ← {len(compressed)//1024}ك.ب")
        except Exception as e:
            print(f"  ⚠️ فشلت صورة {i}: {e}")

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
