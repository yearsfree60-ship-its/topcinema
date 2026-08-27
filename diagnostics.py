#!/usr/bin/env python3
"""
قسم التشخيص الموسّع (DIAGNOSTIC_MODE) — فُصل من compress_chapters.py الأساسي
(كان سابقًا "وضع التشخيص (موسّع)"، الأسطر ~2263-3307 من النسخة الأحادية v19)
إلى ملف مستقل بطلب صريح لتنظيم الكود. تضمّن الفصل أيضًا نقل 5 دوال كانت
موجودة فعليًا ضمن القسم المشترك بالملف الأصلي لكنها تُستخدم حصرًا من
التشخيص (لا استدعاء لها إطلاقًا من مسار الإنتاج العادي أو OCR):
_read_remote_text_sync، _load_diagnostic_history_sync،
_save_diagnostic_history_sync، _diff_diagnostic_snapshots،
_tls_and_server_info_sync، _runner_network_info_sync.

هذا الملف يُستورَد فقط من compress_chapters.py (استيراد مؤجَّل داخل main()
تحديدًا، لا على مستوى الملف — لتفادي استيراد دائري لأن هذا الملف نفسه
يستورد من compress_chapters عدة دوال/ثوابت مشتركة أدناه). لا يُشغَّل هذا
الملف مباشرةً بأي سيناريو إنتاجي.

الاعتماديات على compress_chapters.py (النواة المشتركة، مسار المتصفح
ومسار HTTP بشكل خاص — التشخيص يعيد استخدام نفس دوال الإنتاج الفعلية، لا
نسخة موازية منها، حتى تبقى النتائج ممثِّلة لسلوك الإنتاج الحقيقي):
- مسار المتصفح: classify_challenge_page، probe_challenge_with_extended_wait،
  collect_images_while_scrolling، dismiss_adblock_wall_timed،
  count_real_images، wait_for_real_images، snapshot_images،
  _filter_widget_context، _classify_challenge_html، _looks_like_challenge_html.
- مسار HTTP: extract_images_from_html، _validate_image_bytes، dedupe.
- عامة: slugify، classify_protection_signatures، _suggest_selectors_from_unmatched،
  fetch_image_bytes.
- git/دفع: _commit_and_push_sync، _compute_git_relative_output_dir، _run_git.
- ثوابت: OUTPUT_DIR، RUN_ID، GIT_COMMIT_DIR، GIT_BRANCH، UA، _STEALTH،
  _HTTP_SESSION، CONTENT_SELECTORS، NAV_TIMEOUT_MS، CONTENT_WAIT_MS،
  CONTENT_POLL_MS، MIN_NOSCRIPT_IMAGES، EXTENDED_WAIT_MAX_SEC،
  EXTENDED_CLICK_ATTEMPTS، EXTENDED_CLICK_GAP_SEC،
  PROTECTION_VENDOR_NETWORK_PATTERNS، WIDGET_CONTEXT_PATTERN.

ملاحظة توافق (راجع ذاكرة المحادثة/الفحص السابق): ملف الـworkflow الحالي
(compress-chapters-11.yml) يمرر متغير بيئة DEEP_DIAGNOSTIC، لكن لا هذا
الملف ولا أي جزء من compress_chapters.py يقرأه أو يطبّق أي مسبار
CDP/Runtime.enable بعد — هذه ميزة معلَّقة منفصلة تمامًا عن عملية الفصل
الحالية ولم تُضَف هنا عمدًا.
"""
import asyncio
import json
import re
import socket
import ssl
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import requests.cookies  # لاستخدام RequestsCookieJar في فحص إعادة استخدام الكوكيز
from playwright.async_api import async_playwright

from compress_chapters import (
    CONTENT_POLL_MS,
    CONTENT_SELECTORS,
    CONTENT_WAIT_MS,
    EXTENDED_CLICK_ATTEMPTS,
    EXTENDED_CLICK_GAP_SEC,
    EXTENDED_WAIT_MAX_SEC,
    GIT_BRANCH,
    GIT_COMMIT_DIR,
    MIN_NOSCRIPT_IMAGES,
    NAV_TIMEOUT_MS,
    OUTPUT_DIR,
    PROTECTION_VENDOR_NETWORK_PATTERNS,
    RUN_ID,
    UA,
    WIDGET_CONTEXT_PATTERN,
    _HTTP_SESSION,
    _STEALTH,
    _classify_challenge_html,
    _commit_and_push_sync,
    _compute_git_relative_output_dir,
    _filter_widget_context,
    _looks_like_challenge_html,
    _run_git,
    _suggest_selectors_from_unmatched,
    _validate_image_bytes,
    classify_challenge_page,
    classify_protection_signatures,
    collect_images_while_scrolling,
    count_real_images,
    dedupe,
    dismiss_adblock_wall_timed,
    extract_images_from_html,
    fetch_image_bytes,
    probe_challenge_with_extended_wait,
    slugify,
    snapshot_images,
    wait_for_real_images,
)


# ============================== دوال تاريخ التشخيص (منقولة من القسم المشترك) ==============================

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


