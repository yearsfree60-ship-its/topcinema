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
import base64
import http.client
import json
import os
import re
import socket
import ssl
import time
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse

import requests
import requests.cookies  # لاستخدام RequestsCookieJar في فحص إعادة استخدام الكوكيز
from PIL import Image, ImageFile
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


# ============================== كشف خادم الأصل الحقيقي خلف Cloudflare ==============================
# [إضافة] راجع طلب صريح: عناوين Cloudflare الظاهرة (IP الحافة) ليست
# الخادم الفعلي أبدًا — كل ما جُمِع لحد الآن (cdn-cgi/trace، cf-ray colo،
# شهادة TLS عبر _tls_and_server_info_sync) يصف حافة Cloudflare نفسها، لا
# المصدر خلفها. هذا القسم يحاول استنتاج IP الأصل عبر مصادر خارجية عامة
# (سجلات شهادات SSL تاريخية + Shodan)، ثم يتحقّق ميدانيًا بمحاولة اتصال
# مباشرة بأي IP مُرشَّح — بلا أي افتراض أن الاستنتاج صحيح بالضرورة (مواقع
# كثيرة تُبقي IP الأصل خلف Cloudflare حصرًا بقاعدة جدار ناري صارمة، فمحاولة
# الاتصال المباشر تفشل حتى لو كان IP المُرشَّح صحيحًا فعليًا تاريخيًا).
# كل هذا بيانات خام بحتة للمراجعة اليدوية، بنفس فلسفة بقية هذا الملف —
# لا قرار "استخدم هذا IP بالإنتاج" آليًا هنا إطلاقًا.

_IPV4_LITERAL_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


# ============================== طبقة الجلب المرنة + مصادر كشف الأصل المتعددة ==============================
# [إعادة بناء — بحث محدَّث] كان الكشف يعتمد على مصدر واحد (crt.sh) بمحاولة واحدة
# ومهلة 20ث، فأي عطل مؤقت بخدمتهم (502 موثَّق بكثرة، وصفحات خطأ HTML تحت الضغط،
# وردّ ناجح قد يستغرق 10-20ث) يُنتج candidate_ips=[] فلا يُحاوَل أي اتصال مباشر.
# الآن: (١) جلب مرن بإعادة محاولة وتأخير تصاعدي وjitter وRetry-After وميزانية زمنية،
# (٢) مصادر مستقلة متوازية بعزل تام للأخطاء (فشل واحد لا يُسقط الباقي)،
# (٣) مصدر أدلة لم يكن موجودًا: سجلات A التاريخية للنطاق نفسه (OTX/HackerTarget/urlscan)
# وقرائن SPF/MX — وهي أقوى دليل على الأصل قبل انتقال الموقع إلى Cloudflare،
# (٤) كل ذلك بلا أي اعتمادية جديدة (requests فقط، وDNS عبر DNS-over-HTTPS).
# مفاتيح اختيارية بمتغيرات البيئة (لا يتعطل شيء لو غابت): OTX_API_KEY،
# URLSCAN_API_KEY، CERTSPOTTER_API_KEY، HACKERTARGET_API_KEY،
# CENSYS_API_TOKEN/CENSYS_ORGANIZATION_ID، SECURITYTRAILS_API_KEY.
# Censys وSecurityTrails تكاملان اختياريان: لا يُعتبر غيابهما فشلًا للتشخيص.

import ipaddress
import random
from concurrent.futures import ThreadPoolExecutor


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "").strip() or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _env_key(name: str) -> str:
    return os.environ.get(name, "").strip()


# السقف الزمني الكلي لمرحلة كشف الأصل لكل رابط (قرار المستخدم: دقيقتان).
ORIGIN_DISCOVERY_BUDGET_SEC = _env_float("ORIGIN_DISCOVERY_BUDGET_SEC", 120.0)
_SOURCES_BUDGET_FRACTION = 0.60   # جمع المصادر: حتى ~72ث من 120ث
_RESOLVE_BUDGET_FRACTION = 0.75   # تحليل DNS للأسماء المُكتشَفة: حتى ~90ث
_INTERNETDB_MAX = 8               # عدد المرشحين المُفحوصين بـInternetDB
_DIRECT_PROBE_MAX = 5             # عدد المرشحين المُختبَرين بالاتصال المباشر (بالتوازي)
_HOSTNAMES_TO_RESOLVE_MAX = 25

_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
_HOST_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")


def _parse_retry_after(value) -> float | None:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _resilient_get_sync(url: str, *, deadline: float, params=None, headers=None,
                        max_attempts: int = 5, connect_timeout: float = 8.0,
                        read_timeout: float = 45.0, expect: str = "text",
                        extra_transient_status=(), backoff_base: float = 2.0,
                        backoff_cap: float = 20.0):
    """طلب GET مرن: يعيد (payload, meta). payload=None عند الفشل النهائي.
    يُعيد المحاولة عند: أخطاء الشبكة/المهلة، حالات عابرة (429/5xx وما يُضاف)،
    وJSON غير صالح رغم 200 (crt.sh يُرجع صفحات HTML تحت الحمل). تأخير تصاعدي
    مع jitter، ويحترم Retry-After، ولا يتجاوز deadline (وقت monotonic مطلق)."""
    meta = {"attempts": 0, "status": None, "error": None, "elapsed_sec": None}
    t0 = time.monotonic()
    transient = _TRANSIENT_STATUS | frozenset(extra_transient_status)
    payload = None
    try:
        for attempt in range(1, max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining < 3:
                meta["error"] = meta["error"] or "انتهت الميزانية الزمنية قبل أي محاولة"
                break
            meta["attempts"] = attempt
            retry_after = None
            try:
                resp = requests.get(
                    url, params=params, headers=headers,
                    timeout=(min(connect_timeout, remaining), min(read_timeout, remaining)),
                )
                meta["status"] = resp.status_code
                if resp.status_code in transient:
                    meta["error"] = f"status={resp.status_code}"
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    # 429 بلا Retry-After يعني أن الخدمة طلبت التوقف، وليس
                    # أن إعادة المحاولة السريعة ستزيد جودة الاكتشاف. لا نهدر
                    # ميزانية المصدر/التشخيص كاملة على مزوّد واحد محدود.
                    if resp.status_code == 429 and retry_after is None:
                        break
                elif not resp.ok:
                    meta["error"] = f"status={resp.status_code}"
                    break  # خطأ غير عابر (401/403/404...) — لا فائدة من التكرار
                elif expect == "json":
                    try:
                        payload = resp.json()
                        meta["error"] = None
                        break
                    except ValueError as e:
                        meta["error"] = f"استجابة غير صالحة كـJSON (status={resp.status_code}): {e}"
                else:
                    payload = resp.text
                    meta["error"] = None
                    break
            except requests.exceptions.RequestException as e:
                meta["error"] = f"{type(e).__name__}: {e}"
            if attempt >= max_attempts:
                break
            delay = min(backoff_cap, backoff_base * (2 ** (attempt - 1))) * random.uniform(0.75, 1.25)
            if retry_after is not None:
                if retry_after > deadline - time.monotonic() - 3:
                    meta["error"] = f"{meta['error']} (Retry-After={retry_after:.0f}ث يتجاوز الميزانية)"
                    break
                delay = max(delay, retry_after)
            if delay > deadline - time.monotonic() - 3:
                break
            time.sleep(delay)
    finally:
        meta["elapsed_sec"] = round(time.monotonic() - t0, 2)
    return payload, meta


def _new_source_result(name: str, kind: str) -> dict:
    return {
        "source": name, "kind": kind, "ok": False, "status": None, "attempts": 0,
        "elapsed_sec": None, "error": None, "note": None, "api_key_used": False,
        "hostnames": [], "ips": [],
    }


def _finish_source(res: dict, meta: dict, ok: bool) -> dict:
    res["ok"] = ok
    res["status"] = meta.get("status")
    res["attempts"] = meta.get("attempts", 0)
    res["elapsed_sec"] = meta.get("elapsed_sec")
    res["error"] = None if ok else (meta.get("error") or "فشل غير محدد")
    return res


def _clean_host(name) -> str | None:
    n = (name or "").strip().lower().rstrip(".")
    while n.startswith("*."):
        n = n[2:]
    if not n or "*" in n or not _HOST_PATTERN.match(n):
        return None
    return n


def _in_domain(host: str, domain: str) -> bool:
    d = domain.lower()
    return host == d or host.endswith("." + d)


def _parse_ipv4(ip) -> "ipaddress.IPv4Address | None":
    try:
        a = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    return a if a.version == 4 else None


# ---------- مصادر الأسماء (Certificate Transparency) ----------

def _src_crtsh_sync(domain: str, deadline: float) -> dict:
    """crt.sh — مصدر CT الأساسي. مهلة قراءة 60ث و6 محاولات (404 العابر مُدرَج
    ضمن العابر: يُرجعه crt.sh أحيانًا تحت الحمل ثم ينجح نفس الطلب لاحقًا)."""
    res = _new_source_result("crt.sh", "names")
    data, meta = _resilient_get_sync(
        "https://crt.sh/", params={"q": f"%.{domain}", "output": "json"},
        deadline=deadline, max_attempts=6, read_timeout=60.0, expect="json",
        extra_transient_status=(404,),
    )
    if not isinstance(data, list):
        _finish_source(res, meta, False)
        if data is not None:
            res["error"] = f"شكل استجابة غير متوقع: {type(data).__name__}"
        return res
    hostnames: set[str] = set()
    ips: list[dict] = []
    seen_ips: set[str] = set()
    for cert in data:
        if not isinstance(cert, dict):
            continue
        for line in (cert.get("name_value") or "").split("\n"):
            line = line.strip().lower()
            if not line:
                continue
            if _IPV4_LITERAL_PATTERN.match(line):
                if line not in seen_ips:
                    seen_ips.add(line)
                    ips.append({"ip": line, "hostname": None,
                                "first_seen": cert.get("not_before"), "last_seen": cert.get("not_after")})
                continue
            h = _clean_host(line)
            if h and _in_domain(h, domain):
                hostnames.add(h)
    res["hostnames"] = sorted(hostnames)
    res["ips"] = ips
    res["certificates_found"] = len(data)
    _finish_source(res, meta, True)
    return res


def _src_certspotter_sync(domain: str, deadline: float) -> dict:
    """CertSpotter (SSLMate) — CT مستقل عن crt.sh؛ يعيد الشهادات غير المنتهية فقط
    وحدّه المجاني محدود بالساعة (لذا 3 محاولات فقط وصفحات محدودة)."""
    res = _new_source_result("CertSpotter", "names")
    headers = {"Accept": "application/json"}
    key = _env_key("CERTSPOTTER_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
        res["api_key_used"] = True
    hostnames: set[str] = set()
    after = None
    pages = 0
    total_attempts = 0
    first_meta = None
    t0 = time.monotonic()
    while pages < 6 and deadline - time.monotonic() >= 3:
        params = {"domain": domain, "include_subdomains": "true", "expand": "dns_names"}
        if after:
            params["after"] = after
        data, meta = _resilient_get_sync(
            "https://api.certspotter.com/v1/issuances", params=params, headers=headers,
            deadline=deadline, max_attempts=3, read_timeout=30.0, expect="json",
        )
        total_attempts += meta.get("attempts", 0)
        first_meta = first_meta or meta
        if not isinstance(data, list):
            if pages == 0:
                meta = dict(meta, attempts=total_attempts, elapsed_sec=round(time.monotonic() - t0, 2))
                return _finish_source(res, meta, False)
            res["note"] = f"توقّف الترقيم بعد {pages} صفحة: {meta.get('error')}"
            break
        pages += 1
        if not data:
            break
        for iss in data:
            for n in (iss.get("dns_names") or []) if isinstance(iss, dict) else []:
                h = _clean_host(n)
                if h and _in_domain(h, domain):
                    hostnames.add(h)
        after = data[-1].get("id") if isinstance(data[-1], dict) else None
        if not after:
            break
    if pages == 0:
        meta = {"status": None, "attempts": total_attempts, "error": "انتهت الميزانية قبل أول صفحة",
                "elapsed_sec": round(time.monotonic() - t0, 2)}
        return _finish_source(res, meta, False)
    res["hostnames"] = sorted(hostnames)
    meta = {"status": (first_meta or {}).get("status"), "attempts": total_attempts,
            "elapsed_sec": round(time.monotonic() - t0, 2)}
    _finish_source(res, meta, True)
    return res


def _src_anubis_sync(domain: str, deadline: float) -> dict:
    """AnubisDB (jldc.me) — مصدر أسماء مجاني بلا مفتاح ذُكر ثابتًا بأدوات 2026.
    [ملاحظة] لم تُتحقَّق نقطة نهايته حيًّا من بيئة التطوير (لا شبكة)؛ فشله معزول
    تمامًا ويظهر بجدول المصادر، ولا يؤثر على غيره."""
    res = _new_source_result("AnubisDB", "names")
    data, meta = _resilient_get_sync(
        f"https://jldc.me/anubis/subdomains/{domain}", deadline=deadline,
        max_attempts=3, read_timeout=25.0, expect="json",
    )
    if meta.get("status") == 404:
        res["note"] = "لا سجلات (404)"
        return _finish_source(res, meta, True)
    if not isinstance(data, list):
        _finish_source(res, meta, False)
        if data is not None:
            res["error"] = f"شكل استجابة غير متوقع: {type(data).__name__}"
        return res
    hostnames = {h for h in (_clean_host(x) for x in data if isinstance(x, str)) if h and _in_domain(h, domain)}
    res["hostnames"] = sorted(hostnames)
    return _finish_source(res, meta, True)


# ---------- مصادر عناوين IP التاريخية (Passive DNS) ----------

def _src_otx_passive_dns_sync(domain: str, deadline: float) -> dict:
    """AlienVault OTX passive DNS with a small private time budget."""
    res = _new_source_result("OTX passive DNS", "history")
    headers = {}
    key = _env_key("OTX_API_KEY")
    if key:
        headers["X-OTX-API-KEY"] = key
        res["api_key_used"] = True
    local_deadline = min(deadline, time.monotonic() + (25.0 if key else 12.0))
    hostnames: set[str] = set(); ips: list[dict] = []; ok_targets = 0; errors = []
    attempts = 0; last_status = None; t0 = time.monotonic()
    for kind, host in (("domain", domain), ("hostname", f"www.{domain}")):
        if time.monotonic() >= local_deadline:
            errors.append(f"{host}: انتهت الميزانية الخاصة بـOTX"); break
        data, meta = _resilient_get_sync(
            f"https://otx.alienvault.com/api/v1/indicators/{kind}/{host}/passive_dns",
            headers=headers or None, deadline=local_deadline,
            max_attempts=1 if not key else 2, read_timeout=8.0 if not key else 12.0,
            expect="json", backoff_base=1.0, backoff_cap=2.0,
        )
        attempts += meta.get("attempts", 0); last_status = meta.get("status") or last_status
        if meta.get("status") == 404:
            ok_targets += 1; continue
        if not isinstance(data, dict):
            errors.append(f"{host}: {meta.get('error')}")
            if meta.get("status") in (429, 408) or "Timeout" in str(meta.get("error") or ""):
                break
            continue
        ok_targets += 1
        for rec in data.get("passive_dns") or []:
            if not isinstance(rec, dict) or rec.get("record_type") != "A": continue
            hn = _clean_host(rec.get("hostname")) or host; ip = _parse_ipv4(rec.get("address"))
            if _in_domain(hn, domain) and ip:
                hostnames.add(hn); ips.append({"ip": str(ip), "hostname": hn, "first_seen": rec.get("first"), "last_seen": rec.get("last")})
    res["hostnames"] = sorted(hostnames); res["ips"] = ips
    meta = {"status": last_status, "attempts": attempts, "elapsed_sec": round(time.monotonic()-t0,2), "error": "; ".join(errors) or None}
    if ok_targets == 0: return _finish_source(res, meta, False)
    if errors: res["note"] = "جزئي — " + "; ".join(errors)
    return _finish_source(res, meta, True)


def _src_robtex_passive_dns_sync(domain: str, deadline: float) -> dict:
    """Robtex public passive DNS; returns NDJSON A-record observations."""
    res = _new_source_result("Robtex passive DNS", "history"); t0=time.monotonic()
    data, meta = _resilient_get_sync(
        f"https://freeapi.robtex.com/pdns/forward/{domain}", params={"type":"a"},
        deadline=min(deadline,t0+12.0), max_attempts=1, connect_timeout=4.0, read_timeout=8.0, expect="text")
    if not isinstance(data,str): return _finish_source(res,meta,False)
    hostnames=set(); ips=[]
    for raw in data.splitlines():
        try: rec=json.loads(raw)
        except Exception: continue
        if not isinstance(rec,dict) or str(rec.get("rrtype","")).upper()!="A": continue
        hn=_clean_host(rec.get("rrname")); ip=_parse_ipv4(rec.get("rrdata"))
        if hn and ip and _in_domain(hn,domain):
            hostnames.add(hn); ips.append({"ip":str(ip),"hostname":hn,"first_seen":rec.get("time_first"),"last_seen":rec.get("time_last")})
    res["hostnames"]=sorted(hostnames); res["ips"]=ips
    if not ips: res["note"]="لا سجلات A تاريخية عامة أعادها Robtex"
    return _finish_source(res,meta,True)


def _src_mnemonic_passive_dns_sync(domain: str, deadline: float) -> dict:
    """Mnemonic public PassiveDNS; tolerate common JSON response layouts."""
    res=_new_source_result("Mnemonic passive DNS","history"); t0=time.monotonic()
    data,meta=_resilient_get_sync(
        f"https://api.mnemonic.no/pdns/v3/{domain}", params={"rrType":"A","limit":"1000"},
        deadline=min(deadline,t0+12.0), max_attempts=1, connect_timeout=4.0, read_timeout=8.0, expect="json")
    if data is None: return _finish_source(res,meta,False)
    records=data if isinstance(data,list) else []
    if isinstance(data,dict):
        for key in ("records","results","data","answer","answers"):
            if isinstance(data.get(key),list): records=data[key]; break
    hostnames=set(); uniq={}
    def walk(obj):
        if isinstance(obj,dict):
            typ=str(obj.get("rrtype") or obj.get("record_type") or obj.get("type") or "").upper()
            hn=_clean_host(obj.get("rrname") or obj.get("name") or obj.get("hostname"))
            value=obj.get("rrdata") or obj.get("rdata") or obj.get("address") or obj.get("ip") or obj.get("answer")
            ip=_parse_ipv4(value)
            if typ=="A" and hn and ip and _in_domain(hn,domain):
                hostnames.add(hn); uniq[(str(ip),hn)]={"ip":str(ip),"hostname":hn,"first_seen":obj.get("time_first") or obj.get("first_seen"),"last_seen":obj.get("time_last") or obj.get("last_seen")}
            for v in obj.values():
                if isinstance(v,(dict,list)): walk(v)
        elif isinstance(obj,list):
            for v in obj: walk(v)
    walk(records)
    res["hostnames"]=sorted(hostnames); res["ips"]=list(uniq.values())
    if not res["ips"]: res["note"]="لم تُستخرج سجلات A تاريخية من استجابة Mnemonic"
    return _finish_source(res,meta,True)


def _src_hackertarget_sync(domain: str, deadline: float) -> dict:
    """HackerTarget hostsearch — أسماء + IPs من مسحهم (مجاني ~100 طلب/يوم بلا مفتاح).
    يُرجع أخطاءه كنص بحالة 200 (مثل تجاوز الحد)، فتُفحَص محتوياتها صراحةً."""
    res = _new_source_result("HackerTarget", "history")
    params = {"q": domain}
    key = _env_key("HACKERTARGET_API_KEY")
    if key:
        params["apikey"] = key
        res["api_key_used"] = True
    text, meta = _resilient_get_sync(
        "https://api.hackertarget.com/hostsearch/", params=params, deadline=deadline,
        max_attempts=2, read_timeout=25.0, expect="text",
    )
    if text is None:
        return _finish_source(res, meta, False)
    body = text.strip()
    low = body.lower()
    if low.startswith("error") or "api count exceeded" in low:
        meta = dict(meta, error=f"رفض من الخدمة: {body[:120]}")
        return _finish_source(res, meta, False)
    if low.startswith("no records") or not body:
        res["note"] = "لا سجلات"
        return _finish_source(res, meta, True)
    hostnames: set[str] = set()
    ips: list[dict] = []
    for line in body.splitlines():
        host_part, _, ip_part = line.partition(",")
        h = _clean_host(host_part)
        if h and _in_domain(h, domain):
            hostnames.add(h)
            if _parse_ipv4(ip_part):
                ips.append({"ip": ip_part.strip(), "hostname": h, "first_seen": None, "last_seen": None})
    res["hostnames"] = sorted(hostnames)
    res["ips"] = ips
    return _finish_source(res, meta, True)


def _src_urlscan_sync(domain: str, deadline: float) -> dict:
    """urlscan.io search — فحوصات عامة سابقة للنطاق؛ page.ip قد يحفظ IP ما قبل
    Cloudflare. يعمل بلا مفتاح بحدود أقل؛ URLSCAN_API_KEY يرفعها."""
    res = _new_source_result("urlscan.io", "history")
    headers = {}
    key = _env_key("URLSCAN_API_KEY")
    if key:
        headers["API-Key"] = key
        res["api_key_used"] = True
    data, meta = _resilient_get_sync(
        "https://urlscan.io/api/v1/search/", params={"q": f"domain:{domain}", "size": 100},
        headers=headers or None, deadline=deadline, max_attempts=3, read_timeout=25.0, expect="json",
    )
    if not isinstance(data, dict):
        _finish_source(res, meta, False)
        if data is not None:
            res["error"] = f"شكل استجابة غير متوقع: {type(data).__name__}"
        return res
    hostnames: set[str] = set()
    ips: list[dict] = []
    rejected = 0
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        page = r.get("page") or {}
        task = r.get("task") or {}
        h = _clean_host(page.get("domain"))
        apex = _clean_host(page.get("apexDomain"))
        task_host = _clean_host(urlparse(str(task.get("url") or "")).hostname)
        # urlscan قد يعيد نتائج فيها موارد/تحويلات خارجية رغم استعلام domain:.
        # لا يجوز ربط page.ip بالنطاق إلا إذا كانت الصفحة الأساسية نفسها مرتبطة
        # بالنطاق الهدف (أو كانت task.url داخله). هذا يمنع false-positive مثل
        # Google IPs التي ظهرت في تشغيل سابق للنطاق المستهدف.
        relevant = (h and _in_domain(h, domain)) or (apex == domain) or (task_host and _in_domain(task_host, domain))
        if not relevant:
            rejected += 1
            continue
        if h and _in_domain(h, domain):
            hostnames.add(h)
        elif task_host and _in_domain(task_host, domain):
            hostnames.add(task_host)
        candidate_ip = _parse_ipv4(page.get("ip"))
        if candidate_ip:
            when = task.get("time") or r.get("indexedAt")
            host_for_ip = h if h and _in_domain(h, domain) else (task_host if task_host and _in_domain(task_host, domain) else domain)
            ips.append({"ip": str(candidate_ip), "hostname": host_for_ip, "first_seen": when, "last_seen": when})
    res["records_rejected_out_of_domain"] = rejected
    res["hostnames"] = sorted(hostnames)
    res["ips"] = ips
    return _finish_source(res, meta, True)


# ---------- مصادر تاريخية اختيارية عالية القيمة (Censys / SecurityTrails) ----------

def _src_censys_dns_history_sync(domain: str, deadline: float) -> dict:
    """Censys Platform Active DNS: historical A resolutions when credentials and
    a plan with Global Data access are available. The integration is deliberately
    optional; 401/403/409 are reported as capability/auth limitations, not as a
    diagnostic failure of the target."""
    res = _new_source_result("Censys historical DNS", "history")
    token = _env_key("CENSYS_API_TOKEN")
    org = _env_key("CENSYS_ORGANIZATION_ID")
    if not token or not org:
        res["note"] = "تخطي اختياري: CENSYS_API_TOKEN و/أو CENSYS_ORGANIZATION_ID غير مضبوط"
        res["optional_unconfigured"] = True
        return _finish_source(res, {"status": None, "attempts": 0, "elapsed_sec": 0.0, "error": None}, True)
    days = max(1, min(3650, int(_env_float("CENSYS_HISTORY_DAYS", 365.0))))
    end = time.time()
    start = end - days * 86400
    from datetime import datetime, timezone
    start_s = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = datetime.fromtimestamp(end, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    hostnames = set(); ips = []; seen = set(); t0 = time.monotonic()
    # Apex + www are the highest-value historical DNS names. Subdomains are
    # handled later through the CT/PDNS hostname queue to keep API use bounded.
    for name in (domain, f"www.{domain}"):
        if time.monotonic() >= deadline - 2:
            break
        params = {"organization_id": org, "start_time": start_s, "end_time": end_s,
                  "record_types": "A", "page_size": "100"}
        data, meta = _resilient_get_sync(
            f"https://api.platform.censys.io/v3/global/dns/resolutions/{name}/bounds",
            params=params, headers=headers, deadline=deadline, max_attempts=2,
            connect_timeout=5.0, read_timeout=12.0, expect="json", backoff_base=1.0, backoff_cap=3.0)
        if not isinstance(data, dict):
            if meta.get("status") in (401, 403, 409):
                res["note"] = f"Censys غير متاح بهذه الخطة/الصلاحيات (HTTP {meta.get('status')})"
                res["capability_limited"] = True
                break
            res["error"] = meta.get("error")
            continue
        # Response schema may evolve; walk nested records but only accept explicit A records
        # whose query/name is the requested in-domain hostname.
        def walk(obj):
            if isinstance(obj, dict):
                typ = str(obj.get("record_type") or obj.get("recordType") or obj.get("type") or "").upper()
                name0 = _clean_host(obj.get("name") or obj.get("query") or obj.get("domain") or obj.get("hostname"))
                value = obj.get("value") or obj.get("answer") or obj.get("ip") or obj.get("address") or obj.get("record")
                vals = value if isinstance(value, list) else [value]
                if typ == "A" and name0 and _in_domain(name0, domain):
                    hostnames.add(name0)
                    for v in vals:
                        a = _parse_ipv4(v)
                        if a:
                            key=(str(a),name0)
                            if key not in seen:
                                seen.add(key)
                                ips.append({"ip":str(a),"hostname":name0,
                                            "first_seen":obj.get("first_seen") or obj.get("firstSeen") or obj.get("first_seen_at"),
                                            "last_seen":obj.get("last_seen") or obj.get("lastSeen") or obj.get("last_seen_at")})
                for v in obj.values():
                    if isinstance(v,(dict,list)): walk(v)
            elif isinstance(obj,list):
                for v in obj: walk(v)
        walk(data)
    res["hostnames"] = sorted(hostnames); res["ips"] = ips
    if not ips and not res.get("capability_limited") and not res.get("error"):
        res["note"] = f"لا سجلات A تاريخية عامة ضمن آخر {days} يومًا"
    res["history_window_days"] = days
    return _finish_source(res, {"status": 200 if ips or res.get("note") else None,
                                "attempts": 1, "elapsed_sec": round(time.monotonic()-t0,2),
                                "error": res.get("error")}, True if not res.get("error") else False)


def _src_securitytrails_dns_history_sync(domain: str, deadline: float) -> dict:
    """SecurityTrails historical A records for apex/www when an API key is set."""
    res = _new_source_result("SecurityTrails historical DNS", "history")
    key = _env_key("SECURITYTRAILS_API_KEY")
    if not key:
        res["note"] = "تخطي اختياري: SECURITYTRAILS_API_KEY غير مضبوط"
        res["optional_unconfigured"] = True
        return _finish_source(res, {"status": None, "attempts": 0, "elapsed_sec": 0.0, "error": None}, True)
    headers = {"APIKEY": key, "Accept": "application/json"}
    hostnames=set(); ips=[]; seen=set(); t0=time.monotonic(); statuses=[]
    for name in (domain, f"www.{domain}"):
        if time.monotonic() >= deadline - 2: break
        data, meta = _resilient_get_sync(
            f"https://api.securitytrails.com/v1/history/{name}/dns/a",
            headers=headers, deadline=deadline, max_attempts=2, connect_timeout=5.0,
            read_timeout=12.0, expect="json", backoff_base=1.0, backoff_cap=3.0)
        statuses.append(meta.get("status"))
        if not isinstance(data, dict):
            res["error"] = meta.get("error")
            if meta.get("status") in (401,403,429): break
            continue
        records = data.get("records") or data.get("data") or []
        if isinstance(records, dict):
            records = records.get("values") or records.get("records") or []
        for rec in records if isinstance(records,list) else []:
            if not isinstance(rec,dict): continue
            ip = rec.get("ip") or rec.get("value") or rec.get("address")
            a = _parse_ipv4(ip)
            if not a: continue
            hn = _clean_host(rec.get("hostname") or rec.get("name")) or name
            if not _in_domain(hn, domain): continue
            hostnames.add(hn); k=(str(a),hn)
            if k not in seen:
                seen.add(k)
                ips.append({"ip":str(a),"hostname":hn,
                            "first_seen":rec.get("first_seen") or rec.get("firstSeen") or rec.get("first_seen_at"),
                            "last_seen":rec.get("last_seen") or rec.get("lastSeen") or rec.get("last_seen_at")})
    res["hostnames"]=sorted(hostnames); res["ips"]=ips; res["api_key_used"]=True
    if not ips and not res.get("error"): res["note"]="لم تُرجع SecurityTrails سجلات A تاريخية قابلة للاستخدام"
    return _finish_source(res,{"status":next((x for x in reversed(statuses) if x is not None),None),
                               "attempts":len(statuses),"elapsed_sec":round(time.monotonic()-t0,2),
                               "error":res.get("error")},not bool(res.get("error")))


# ---------- قرائن DNS الحالية (DNS-over-HTTPS بلا مكتبة جديدة) ----------

_DOH_ENDPOINTS = (
    ("https://dns.google/resolve", None),
    ("https://cloudflare-dns.com/dns-query", {"Accept": "application/dns-json"}),
)
_DNS_TYPE_CODES = {"A": 1, "MX": 15, "TXT": 16}


def _doh_query_sync(name: str, rtype: str, deadline: float):
    """يعيد (answers, error): answers قائمة نصوص data (فارغة لو NXDOMAIN/بلا سجل)،
    أو None لو فشل كل المزوّدين. أدق من socket.gethostbyname: مهلة صريحة وبلا
    تعليق على محلّل الـrunner."""
    last_err = None
    code = _DNS_TYPE_CODES[rtype]
    for endpoint, hdrs in _DOH_ENDPOINTS:
        data, meta = _resilient_get_sync(
            endpoint, params={"name": name, "type": rtype}, headers=hdrs, deadline=deadline,
            max_attempts=2, connect_timeout=5.0, read_timeout=8.0, expect="json",
            backoff_base=1.0, backoff_cap=3.0,
        )
        if not isinstance(data, dict):
            last_err = meta.get("error")
            continue
        if data.get("Status") not in (0, 3):  # 0=NOERROR، 3=NXDOMAIN؛ غيرهما (SERVFAIL...) نجرّب المزوّد التالي
            last_err = f"DNS Status={data.get('Status')}"
            continue
        return [a.get("data", "") for a in (data.get("Answer") or []) if a.get("type") == code], None
    return None, last_err


def _resolve_a_all_sync(host: str, deadline: float) -> list[str]:
    answers, _ = _doh_query_sync(host, "A", deadline)
    if answers is not None:
        return [ip for ip in answers if _parse_ipv4(ip)]
    if time.monotonic() >= deadline:
        return []
    try:  # احتياط أخير لو تعذّر DoH كليًا (مثلًا حجب مزوّديه)
        return sorted(set(socket.gethostbyname_ex(host)[2]))
    except Exception:
        return []


def _src_live_dns_hints_sync(domain: str, deadline: float) -> dict:
    """قرائن من DNS الحالي للنطاق نفسه: عناوين ip4 داخل سجل SPF (خوادم البريد كثيرًا
    ما تكون على نفس الأصل)، وMX المستضاف داخل النطاق نفسه (mail.example.com)."""
    res = _new_source_result("SPF + MX (DoH)", "live")
    t0 = time.monotonic()
    txt, err_txt = _doh_query_sync(domain, "TXT", deadline)
    mx, err_mx = _doh_query_sync(domain, "MX", deadline)
    n_queries = 2
    if txt is None and mx is None:
        meta = {"status": None, "attempts": n_queries, "elapsed_sec": round(time.monotonic() - t0, 2),
                "error": f"تعذّر DoH بالكامل: {err_txt or err_mx}"}
        return _finish_source(res, meta, False)
    ips: list[dict] = []
    for rec in txt or []:
        rec = re.sub(r'"\s*"', "", rec).strip('"')
        if "v=spf1" not in rec.lower():
            continue
        for tok in rec.split():
            tok = tok.lstrip("+")
            if not tok.lower().startswith("ip4:"):
                continue
            addr, _, prefix = tok[4:].partition("/")
            try:
                if prefix and int(prefix) < 24:
                    continue  # نطاق واسع = مزوّد مشترك لا خادم بعينه
            except ValueError:
                continue
            if _parse_ipv4(addr):
                ips.append({"ip": addr, "hostname": domain, "first_seen": None, "last_seen": None, "via": "spf"})
    hostnames: set[str] = set()
    for rec in mx or []:
        parts = rec.split()
        h = _clean_host(parts[-1]) if parts else None
        if not h or not _in_domain(h, domain) or h == domain:
            continue
        hostnames.add(h)
        n_queries += 1
        for ip in _resolve_a_all_sync(h, deadline):
            ips.append({"ip": ip, "hostname": h, "first_seen": None, "last_seen": None, "via": "mx_self"})
    res["hostnames"] = sorted(hostnames)
    res["ips"] = ips
    meta = {"status": 200, "attempts": n_queries, "elapsed_sec": round(time.monotonic() - t0, 2)}
    _finish_source(res, meta, True)
    if not ips:
        res["note"] = "لا ip4 في SPF ولا MX داخلي"
    return res


# ---------- توافق خلفي: الدالتان القديمتان بنفس الشكل ----------

def _ssl_history_probe_sync(domain: str) -> dict:
    """[محفوظة للتوافق] نفس الشكل القديم، لكن فوق crt.sh المرن بدل محاولة واحدة."""
    src = _src_crtsh_sync(domain, time.monotonic() + 90.0)
    return {
        "domain": domain, "tested": src["attempts"] > 0,
        "certificates_found": src.get("certificates_found", 0),
        "historical_ips_literal": sorted({i["ip"] for i in src["ips"]}),
        "subdomains_seen": sorted(src["hostnames"])[:40], "error": src["error"],
    }


def _dns_history_resolve_sync(hostnames: list[str], deadline: float | None = None) -> dict:
    """تحليل A متوازٍ بمهلة صريحة (كان تسلسليًا بلا مهلة). الشكل القديم محفوظ
    (resolved: اسم→أول IP) مع إضافة resolved_all: اسم→كل عناوين IPv4."""
    result = {"resolved": {}, "resolved_all": {}, "unresolved": [], "error": None}
    if not hostnames:
        return result
    if deadline is None:
        deadline = time.monotonic() + 30.0
    ex = ThreadPoolExecutor(max_workers=8)
    try:
        futs = [(h, ex.submit(_resolve_a_all_sync, h, deadline)) for h in hostnames]
        for host, fut in futs:
            try:
                ips = fut.result(timeout=max(0.5, deadline - time.monotonic()))
            except Exception:
                ips = []
            if ips:
                result["resolved"][host] = ips[0]
                result["resolved_all"][host] = ips
            else:
                result["unresolved"].append(host)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return result


# ---------- أولوية الأسماء + تجميع وترتيب المرشحين ----------

_ORIGIN_NAME_STRONG = ("origin", "direct", "backend", "real", "server", "srv", "vps", "dedicated", "master", "node")
_ORIGIN_NAME_WEAK = ("mail", "smtp", "imap", "pop", "webmail", "ftp", "sftp", "cpanel", "whm", "plesk",
                     "ssh", "old", "dev", "staging", "stage", "test", "admin", "panel", "api", "host")


def _origin_name_score(host: str, domain: str) -> int:
    label = host[: -(len(domain) + 1)] if host.endswith("." + domain) else ""
    tokens = [t for t in re.split(r"[.\-_0-9]+", label) if t]
    if any(t in _ORIGIN_NAME_STRONG for t in tokens):
        return 3
    if any(t in _ORIGIN_NAME_WEAK for t in tokens):
        return 1
    return 0


def _prioritize_hostnames(hosts, domain: str, limit: int) -> list[str]:
    """ترتيب دلالي قبل الاقتطاع (كان الاقتطاع أبجديًا فيُسقط origin/direct بنطاق كبير)."""
    dom = domain.lower()
    pool = {h for h in hosts if h and h not in (dom, f"www.{dom}")}
    return sorted(pool, key=lambda h: (-_origin_name_score(h, dom), len(h), h))[:limit]


# عائلات الأدلة: spf وmx_self وdns_live كلها من آلية DNS الحيّ نفسها (دليل واحد
# لا ثلاثة مستقلة)، فتُحتسب عائلة واحدة كي لا يتضخم ترتيب خادم بريد بلا أساس.
_EVIDENCE_FAMILY = {"spf": "live_dns", "mx_self": "live_dns", "dns_live": "live_dns"}


def _collect_candidates(domain: str, source_results: list, dns_hist: dict | None):
    """يجمع الأدلة لكل IPv4 عام: عائلات الأدلة المستقلة، الأسماء، أول/آخر ظهور،
    وعلامة apex_history (سجل A تاريخي للنطاق الرئيسي أو www من مصدر Passive DNS —
    أقوى دليل على IP ما قبل Cloudflare). يعيد (evidence, non_public):
    non_public = خاص/محجوز/غير عالمي (لا يُختبَر)."""
    evidence: dict[str, dict] = {}
    non_public: set[str] = set()
    apex_names = {domain.lower(), f"www.{domain.lower()}"}

    def add(ip_str, label, kind, hostname, first, last):
        a = _parse_ipv4(ip_str)
        if a is None:
            return
        ip = str(a)
        if not a.is_global:
            non_public.add(ip)
            return
        ev = evidence.setdefault(ip, {"sources": set(), "families": set(), "hostnames": set(),
                                      "first_seen": None, "last_seen": None, "apex_history": False})
        ev["sources"].add(label)
        ev["families"].add(_EVIDENCE_FAMILY.get(label, label))
        if hostname:
            ev["hostnames"].add(hostname)
            if kind == "history" and hostname in apex_names:
                ev["apex_history"] = True
        if first:
            f = str(first)[:19]
            ev["first_seen"] = f if ev["first_seen"] is None else min(ev["first_seen"], f)
        if last:
            l = str(last)[:19]
            ev["last_seen"] = l if ev["last_seen"] is None else max(ev["last_seen"], l)

    for r in source_results:
        for e in r.get("ips") or []:
            via = e.get("via")
            add(e.get("ip"), via or r["source"], "live" if via else r["kind"],
                e.get("hostname"), e.get("first_seen"), e.get("last_seen"))
    for host, ips in ((dns_hist or {}).get("resolved_all") or {}).items():
        for ip in ips:
            add(ip, "dns_live", "live", host, None, None)
    return evidence, non_public


def _score_candidate(ev: dict, domain: str) -> int:
    """3 لكل عائلة أدلة مستقلة، +2 لو ثبت بـDNS الحيّ الحالي، +4 لسجل A تاريخي
    للنطاق الرئيسي/www، + دلالة الاسم (origin/direct=3، mail/ftp/...=1)، +1 لظهور حديث."""
    score = 3 * len(ev["families"])
    if "live_dns" in ev["families"]:
        score += 2
    if ev.get("apex_history"):
        score += 4
    score += max((_origin_name_score(h, domain.lower()) for h in ev["hostnames"]), default=0)
    if ev.get("last_seen"):
        try:
            age_days = (time.time() - time.mktime(time.strptime(ev["last_seen"][:10], "%Y-%m-%d"))) / 86400
            if age_days <= 400:
                score += 1
        except Exception:
            pass
    return score


def _public_source_view(r: dict) -> dict:
    return {
        "source": r["source"], "kind": r["kind"], "ok": r["ok"], "status": r["status"],
        "attempts": r["attempts"], "elapsed_sec": r["elapsed_sec"], "error": r["error"],
        "note": r["note"], "api_key_used": r["api_key_used"],
        "hostnames_count": len(r.get("hostnames") or []), "ips_count": len(r.get("ips") or []),
    }


# ---------- ذاكرة احتياطية لآخر مرشحين ناجحين ----------

def _origin_cache_relpath(domain: str) -> str:
    return f"diagnostics/history/origin-cache-{re.sub(r'[^a-z0-9.-]+', '-', domain.lower())}.json"


def _load_origin_cache_sync(domain: str) -> dict | None:
    relpath = _origin_cache_relpath(domain)
    texts = []
    if GIT_COMMIT_DIR:
        git_rel_output = _compute_git_relative_output_dir(GIT_COMMIT_DIR)
        if git_rel_output:
            texts.append(_read_remote_text_sync(GIT_COMMIT_DIR, GIT_BRANCH, f"{git_rel_output}/{relpath}"))
    local_path = OUTPUT_DIR / relpath
    if local_path.exists():
        try:
            texts.append(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    for text in texts:
        if not text:
            continue
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("candidates"), list):
                return data
        except Exception:
            continue
    return None


def _save_origin_cache_sync(domain: str, details: list) -> None:
    path = OUTPUT_DIR / _origin_cache_relpath(domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": domain, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidates": [
            {k: d.get(k) for k in ("ip", "score", "sources", "hostnames", "first_seen", "last_seen")}
            for d in details[:10]
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _shodan_internetdb_probe_sync(ip: str) -> dict:
    """[معدَّل — بحث محدَّث] الإصدار القديم استخدم /shodan/host/{ip} الذي
    بات (منتصف 2026) يتطلب Shodan Membership مدفوعًا حتى بمفتاح صالح —
    مفتاح مجاني عادي يُرجَع له غالبًا 401. البديل الرسمي المجاني بلا أي
    مفتاح هو InternetDB (raw.internetdb.shodan.io توثيقًا حديثًا: بلا
    مصادقة، حد أعلى مرتفع جدًا (~10000 طلب/ث)، تحديث أسبوعي، ويتضمن حقل
    tags الذي قد يحوي 'cdn' — إشارة مباشرة أن IP هذا نفسه خلف/هو CDN لا
    خادم أصل حقيقي، تُستخدَم لاحقًا لاستبعاده من قائمة الاعتماد). بلا أي
    مفتاح أو إعداد مطلوب من المستخدم إطلاقًا."""
    result = {
        "ip": ip, "tested": False, "org": None, "isp": None,
        "country": None, "ports_open": [], "services_sample": [],
        "hostnames": [], "tags": [], "vulns": [],
        "last_update": None, "error": None,
    }
    try:
        resp = requests.get(f"https://internetdb.shodan.io/{ip}", timeout=15)
        result["tested"] = True
        if resp.status_code == 404:
            result["error"] = "لا بيانات مفهرَسة بـInternetDB لهذا الـIP (404) — طبيعي لخوادم كثيرة"
            return result
        if not resp.ok:
            result["error"] = f"status={resp.status_code}"
            return result
        data = resp.json()
        result["ports_open"] = sorted(set(data.get("ports") or []))
        result["hostnames"] = data.get("hostnames") or []
        result["tags"] = data.get("tags") or []
        result["vulns"] = data.get("vulns") or []
        result["services_sample"] = (data.get("cpes") or [])[:8]
    except Exception as e:
        result["error"] = f"{e}"
    return result


# [إبقاء اختياري] /shodan/host/{ip} الرسمي — يتطلب Membership فعليًا
# بحسابات كثيرة الآن، فلا يُستدعى إطلاقًا إلا لو ضُبط SHODAN_API_KEY صراحةً
# بمتغيرات البيئة (المستخدم من يقرر تفعيله، لا افتراضي). فشله بأي 401/403
# لا يوقف التشخيص — InternetDB أعلاه هو المصدر الافتراضي المستقل عنه كليًا.
def _shodan_host_api_probe_sync(ip: str) -> dict:
    result = {
        "ip": ip, "tested": False, "org": None, "isp": None,
        "country": None, "ports_open": [], "services_sample": [],
        "last_update": None, "error": None,
    }
    shodan_key = os.environ.get("SHODAN_API_KEY", "").strip()
    if not shodan_key:
        result["error"] = "SHODAN_API_KEY غير مضبوط — تخطّي (اختياري، InternetDB أعلاه يكفي غالبًا)"
        return result
    try:
        resp = requests.get(
            f"https://api.shodan.io/shodan/host/{ip}", params={"key": shodan_key}, timeout=15,
        )
        result["tested"] = True
        if resp.status_code == 401:
            result["error"] = "مفتاح مرفوض (401) — الأرجح يتطلب Shodan Membership مدفوعًا لهذه النقطة تحديدًا"
            return result
        if resp.status_code == 404:
            result["error"] = "لا بيانات مفهرَسة بـShodan لهذا الـIP (404)"
            return result
        if not resp.ok:
            result["error"] = f"status={resp.status_code}"
            return result
        data = resp.json()
        result["org"] = data.get("org")
        result["isp"] = data.get("isp")
        result["country"] = data.get("country_name")
        result["last_update"] = data.get("last_update")
        ports = sorted(set(data.get("ports") or []))
        result["ports_open"] = ports
        services = {}
        for item in data.get("data") or []:
            p = item.get("port")
            if p is not None and p not in services:
                services[p] = item.get("product") or item.get("_shodan", {}).get("module") or "؟"
        result["services_sample"] = [f"{p}/{services[p]}" for p in sorted(services)][:8]
    except Exception as e:
        result["error"] = f"{e}"
    return result

# [إضافة — بحث محدَّث] قائمة نطاقات Cloudflare الرسمية IPv4 (نادرًا ما
# تتغيّر، آخر توثيق رسمي متاح وقت الكتابة — راجع cloudflare.com/ips).
# مصدر حي (_cloudflare_ipv4_ranges أدناه) هو الأساس؛ هذه القائمة احتياط
# فقط عند فشل الجلب الحي (لا شبكة/انقطاع خدمة)، فتُستبعد المرشحين
# الواقعين ضمن حافة Cloudflare نفسها قبل استهلاك خانات التحقق الميداني
# الثلاث المحدودة — مرشَّح بهذا النطاق مضمون الفشل دلاليًا (هو الحافة لا
# الأصل)، فتضييعه لا يفيد التشخيص إطلاقًا.
_CLOUDFLARE_IPV4_FALLBACK = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
)
_CF_RANGES_CACHE: dict = {"nets": None, "fetched_at": 0.0}


def _cloudflare_ipv4_networks() -> list:
    """[إضافة] يجلب نطاقات Cloudflare الحية من واجهتها الرسمية العامة
    (بلا مفتاح) مرة واحدة لكل تشغيلة ويخزّنها مؤقتًا، ويسقط للقائمة
    الاحتياطية أعلاه عند أي فشل شبكي — أدق من قائمة ثابتة قد تصبح قديمة،
    بلا نقطة فشل واحدة لو انقطع الاتصال بواجهة Cloudflare نفسها."""
    import ipaddress
    if _CF_RANGES_CACHE["nets"] is not None:
        return _CF_RANGES_CACHE["nets"]
    cidrs = None
    try:
        resp = requests.get("https://api.cloudflare.com/client/v4/ips", timeout=10)
        if resp.ok:
            data = resp.json()
            cidrs = (data.get("result") or {}).get("ipv4_cidrs")
    except Exception:
        pass
    if not cidrs:
        cidrs = list(_CLOUDFLARE_IPV4_FALLBACK)
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except Exception:
            continue
    _CF_RANGES_CACHE["nets"] = nets
    return nets


def _is_cloudflare_ip(ip: str) -> bool:
    """[إضافة] True لو IP يقع ضمن أي نطاق Cloudflare معروف — يُستخدَم
    لاستبعاد مرشحين مضمونين الفشل قبل محاولة الاتصال الميداني بهم."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    return any(addr in net for net in _cloudflare_ipv4_networks())


def _direct_ip_tls_probe_sync(ip: str, sni_hostname: str, port: int = 443) -> dict:
    """تحقق مباشر من مرشح أصل مع فصل واضح بين TCP/TLS/HTTP.

    الوجهة الشبكية هي IP، بينما SNI وHost هما اسم النطاق. لا نستخدم
    requests.get(https://IP) لأن ذلك قد يجعل طبقة TLS تتعامل مع IP بدل SNI.
    تُقرأ الشهادة بصيغة DER ثم تُحلَّل إن توفرت cryptography؛ وهذا يتجنب
    مشكلة getpeercert() الفارغ عند CERT_NONE. فشل تحليل الشهادة لا يلغي
    قيمة اختبار TCP/TLS/HTTP نفسه، بل يسجله كإشارة ناقصة.
    """
    result = {
        "target_ip": ip, "port": port, "sni_used": sni_hostname,
        "tcp_reachable": False, "tls_handshake_ok": False,
        "tls_cert_cn": None, "tls_cert_san": [], "tls_cert_issuer_org": None,
        "cert_matches_target_domain": None,
        "http_head_status": None, "http_head_server_header": None,
        "elapsed_sec": None, "error": None,
    }
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((ip, port), timeout=10)
        result["tcp_reachable"] = True
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with ctx.wrap_socket(sock, server_hostname=sni_hostname) as ssock:
                result["tls_handshake_ok"] = True
                cert_der = ssock.getpeercert(binary_form=True)
                if cert_der:
                    try:
                        from cryptography import x509
                        cert = x509.load_der_x509_certificate(cert_der)
                        try:
                            result["tls_cert_cn"] = cert.subject.get_attributes_for_oid(
                                x509.NameOID.COMMON_NAME
                            )[0].value
                        except Exception:
                            pass
                        try:
                            result["tls_cert_issuer_org"] = cert.issuer.get_attributes_for_oid(
                                x509.NameOID.ORGANIZATION_NAME
                            )[0].value
                        except Exception:
                            pass
                        try:
                            san = cert.extensions.get_extension_for_class(
                                x509.SubjectAlternativeName
                            ).value
                            result["tls_cert_san"] = san.get_values_for_type(x509.DNSName)
                        except Exception:
                            result["tls_cert_san"] = []
                    except Exception as e:
                        result["error"] = f"تعذّر تحليل شهادة TLS: {type(e).__name__}: {e}"
                else:
                    result["error"] = "تمت مصافحة TLS لكن الخادم لم يُرجع شهادة قابلة للقراءة"
        except Exception as e:
            result["error"] = f"فشلت مصافحة TLS: {type(e).__name__}: {e}"
    except socket.timeout:
        result["error"] = "انتهاء المهلة الزمنية (المنفذ لا يستجيب — قد يكون محجوبًا بجدار ناري)"
    except ConnectionRefusedError:
        result["error"] = "رُفض الاتصال صراحةً (المنفذ مغلق على هذا IP)"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    if result["tls_handshake_ok"]:
        all_names = ([result["tls_cert_cn"]] if result["tls_cert_cn"] else []) + result["tls_cert_san"]
        target_l = sni_hostname.lower()
        result["cert_matches_target_domain"] = any(
            n and (n.lower() == target_l or (n.lower().startswith("*.") and target_l.endswith(n.lower()[1:])))
            for n in all_names
        ) if all_names else None

        # HTTP/1.1 عبر نفس semantics: IP هو destination، والـHost هو الهدف.
        # _OriginIPConnection يضع SNI الصحيح عند إنشاء TLS socket.
        conn = None
        try:
            conn = _OriginIPConnection(ip, sni_hostname, port=port, timeout=15)
            conn.request("GET", "/", headers={
                "Host": sni_hostname,
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Connection": "close",
            })
            resp = conn.getresponse()
            result["http_head_status"] = resp.status
            result["http_head_server_header"] = resp.getheader("Server")
            # لا نحتاج الجسم هنا؛ القراءة المحدودة تساعد على إغلاق الاتصال
            # بصورة نظيفة مع بعض الخوادم التي لا تنهي الاستجابة إلا بعد read.
            resp.read(1024)
        except Exception as e:
            msg = f"فشل طلب HTTP مباشر مع SNI/Host الصحيح: {type(e).__name__}: {e}"
            result["error"] = ((result["error"] + " | ") if result["error"] else "") + msg
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    result["elapsed_sec"] = round(time.monotonic() - t0, 2)
    return result


_ORIGIN_SOURCES = (
    _src_crtsh_sync, _src_certspotter_sync, _src_anubis_sync,
    _src_otx_passive_dns_sync, _src_robtex_passive_dns_sync,
    _src_mnemonic_passive_dns_sync, _src_hackertarget_sync,
    _src_urlscan_sync, _src_censys_dns_history_sync,
    _src_securitytrails_dns_history_sync, _src_live_dns_hints_sync,
)
_ORIGIN_SOURCE_LABELS = {
    "_src_crtsh_sync": ("crt.sh", "names"),
    "_src_certspotter_sync": ("CertSpotter", "names"),
    "_src_anubis_sync": ("AnubisDB", "names"),
    "_src_otx_passive_dns_sync": ("OTX passive DNS", "history"),
    "_src_robtex_passive_dns_sync": ("Robtex passive DNS", "history"),
    "_src_mnemonic_passive_dns_sync": ("Mnemonic passive DNS", "history"),
    "_src_hackertarget_sync": ("HackerTarget", "history"),
    "_src_urlscan_sync": ("urlscan.io", "history"),
    "_src_censys_dns_history_sync": ("Censys historical DNS", "history"),
    "_src_securitytrails_dns_history_sync": ("SecurityTrails historical DNS", "history"),
    "_src_live_dns_hints_sync": ("SPF + MX (DoH)", "live"),
}

_VERDICT_EXPLANATIONS = {
    "strong_candidates_unverified": "مرشح قوي استنادًا إلى أدلة متعددة أو تحقق TLS/HTTP؛ لا يُسمّى Origin نهائيًا إلا بعد مطابقة المحتوى/البصمة، لأن الحجب أو الجدار الناري قد يمنع الاتصال المباشر",
    "historical_candidates_unverified": "وُجدت عناوين عامة مرتبطة تاريخيًا/بمصادر OSINT، لكنها لم تحقق مستوى الدليل الكافي لتسميتها Origin",
    "candidates_found": "وُجد مرشَّحون عامّون غير تابعين لـCloudflare من مصدر حيّ واحد على الأقل",
    "candidates_from_cache": "فشلت كل المصادر الحيّة؛ استُخدم آخر مرشحين ناجحين محفوظين (قد يكونون قديمين)",
    "all_sources_failed": "فشلت كل المصادر (عطل خدمات/شبكة) ولا ذاكرة احتياطية — لا علاقة لذلك بحجب الموقع نفسه",
    "only_cloudflare_or_non_public": "المصادر ردّت لكن كل العناوين إمّا Cloudflare نفسها أو خاصة/غير عامة — الأصل غالبًا مخفي بالكامل",
    "no_candidates_some_sources_failed": "لا مرشحين، وبعض المصادر فشلت — النتيجة غير حاسمة؛ أعد التشغيل لاحقًا",
    "no_public_records": "كل المصادر ردّت بنجاح ولا سجلات عامة تكشف الأصل — الأصل مخفي فعليًا",
    "no_domain": "تعذّر استخراج اسم النطاق من الرابط",
}


def _probe_timeout_placeholder(ip: str, sni: str, reason: str) -> dict:
    return {
        "target_ip": ip, "port": 443, "sni_used": sni, "tcp_reachable": False,
        "tls_handshake_ok": False, "tls_cert_cn": None, "tls_cert_san": [],
        "tls_cert_issuer_org": None, "cert_matches_target_domain": None,
        "http_head_status": None, "http_head_server_header": None,
        "elapsed_sec": None, "error": reason,
    }


async def _origin_server_discovery(url: str) -> dict:
    """[معاد بناؤه] المسار الكامل لكشف خادم الأصل خلف Cloudflare — مرة واحدة لكل
    رابط (بصمة الاستضافة على مستوى النطاق). المراحل ضمن سقف زمني كلي
    (ORIGIN_DISCOVERY_BUDGET_SEC، افتراضي 120ث):
      ١) 11 مصدرًا مستقلًا بالتوازي وبعزل أخطاء كامل (CT، Passive DNS، urlscan،
         Censys/SecurityTrails الاختياريان، SPF/MX)،
      ٢) تحليل DNS متوازٍ للأسماء المُكتشَفة بعد ترتيبها دلاليًا (origin/direct أولًا)،
      ٣) تجميع الأدلة وترتيب المرشحين + استبعاد Cloudflare والعناوين غير العامة،
      ٤) InternetDB لأعلى المرشحين (وسم cdn يخفض الترتيب)، ثم اتصال مباشر متوازٍ،
      ٥) حكم تشخيصي صريح (discovery_verdict) وجدول حالة لكل مصدر (source_status)
         يفرّق بين فشل المصدر وغياب السجلات وكون كل العناوين Cloudflare.
    بيانات خام للمراجعة — لا قرار تلقائي 'هذا هو الأصل' هنا. الاحتياط: لو فشلت
    كل المصادر تُستخدم آخر قائمة مرشحين ناجحة محفوظة (وسمها candidates_from_cache)."""
    domain = (urlparse(url).hostname or "").lower()
    result = {
        "domain": domain, "ssl_certificate_history": None, "dns_history_resolve": None,
        "shodan_probes": [], "direct_connection_attempts": [], "candidate_ips": [],
        "candidate_ips_excluded_as_cloudflare": [], "candidate_ips_excluded_non_public": [],
        "candidate_details": [], "candidates_from_cache": False,
        "source_status": [], "discovery_verdict": None, "verdict_explanation": None,
        "budget_sec": ORIGIN_DISCOVERY_BUDGET_SEC, "elapsed_sec": None,
    }
    if not domain:
        result["discovery_verdict"] = "no_domain"
        result["verdict_explanation"] = _VERDICT_EXPLANATIONS["no_domain"]
        return result

    t0 = time.monotonic()
    hard_deadline = t0 + ORIGIN_DISCOVERY_BUDGET_SEC
    # Stage deadlines are bounded by the same hard deadline. The old design
    # used independent absolute fractions (72s + 90s), which could silently
    # exceed the advertised 120s budget when both stages consumed their caps.
    sources_deadline = min(hard_deadline, t0 + ORIGIN_DISCOVERY_BUDGET_SEC * _SOURCES_BUDGET_FRACTION)
    resolve_deadline = min(hard_deadline, max(sources_deadline, t0 + ORIGIN_DISCOVERY_BUDGET_SEC * _RESOLVE_BUDGET_FRACTION))

    # ملء كاش نطاقات Cloudflare مسبقًا خارج حلقة الأحداث (الجلب متزامن).
    await asyncio.to_thread(_cloudflare_ipv4_networks)

    # ---- ١) المصادر بالتوازي ----
    async def _run_source(fn):
        label, kind = _ORIGIN_SOURCE_LABELS[fn.__name__]
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, domain, sources_deadline),
                timeout=max(5.0, sources_deadline - time.monotonic() + 5.0),
            )
        except asyncio.TimeoutError:
            r = _new_source_result(label, kind)
            r["error"] = "تجاوز السقف الزمني لمرحلة المصادر (timeout)"
            return r
        except Exception as e:  # عزل تام: أي استثناء غير متوقع بمصدر لا يُسقط الباقي
            r = _new_source_result(label, kind)
            r["error"] = f"استثناء غير متوقع: {type(e).__name__}: {e}"
            return r

    source_results = list(await asyncio.gather(*[_run_source(fn) for fn in _ORIGIN_SOURCES]))
    result["source_status"] = [_public_source_view(r) for r in source_results]

    crt = next((r for r in source_results if r["source"] == "crt.sh"), None)
    if crt is not None:
        result["ssl_certificate_history"] = {
            "domain": domain, "tested": crt["attempts"] > 0,
            "certificates_found": crt.get("certificates_found", 0),
            "historical_ips_literal": sorted({i["ip"] for i in crt["ips"]}),
            "subdomains_seen": _prioritize_hostnames(crt["hostnames"], domain, 40),
            "error": crt["error"],
        }

    # ---- ٢) تحليل DNS للأسماء (مرتّبة دلاليًا قبل الاقتطاع) ----
    all_names: set[str] = set()
    for r in source_results:
        all_names.update(r.get("hostnames") or [])
    # النطاق الرئيسي وwww لهما قيمة تشخيصية خاصة: حتى لو كانت عناوينهما
    # الحالية Cloudflare، يجب تسجيلها صراحةً ومقارنتها مع السجلات التاريخية
    # بدل إسقاطهما من مرحلة DNS قبل بناء evidence graph.
    priority_names = _prioritize_hostnames(all_names, domain, _HOSTNAMES_TO_RESOLVE_MAX)
    apex_names = [domain, f"www.{domain}"]
    to_resolve = list(dict.fromkeys(apex_names + priority_names))
    dns_hist = None
    if to_resolve:
        dns_hist = await asyncio.to_thread(_dns_history_resolve_sync, to_resolve, resolve_deadline)
    result["dns_history_resolve"] = dns_hist

    # ---- ٣) تجميع الأدلة والاستبعاد والترتيب ----
    evidence, non_public = _collect_candidates(domain, source_results, dns_hist)
    cf_excluded = sorted(ip for ip in evidence if _is_cloudflare_ip(ip))
    # لا نعتبر Cloudflare IP مرشح أصل، لكن نحتفظ بتفاصيل أدلته حتى يعرف
    # التقرير لماذا ظهر العنوان وماذا يعني استبعاده. هذا يمنع فقدان السياق.
    result["candidate_ips_excluded_as_cloudflare"] = cf_excluded
    result["cloudflare_excluded_details"] = [
        {
            "ip": ip,
            "score": _score_candidate(evidence[ip], domain),
            "sources": sorted(evidence[ip]["sources"]),
            "hostnames": sorted(evidence[ip]["hostnames"])[:8],
            "first_seen": evidence[ip]["first_seen"],
            "last_seen": evidence[ip]["last_seen"],
            "apex_history": bool(evidence[ip].get("apex_history")),
        }
        for ip in cf_excluded
    ]
    for ip in cf_excluded:
        evidence.pop(ip, None)
    result["candidate_ips_excluded_non_public"] = sorted(non_public)

    details = []
    for ip, ev in evidence.items():
        details.append({
            "ip": ip, "score": _score_candidate(ev, domain), "sources": sorted(ev["sources"]),
            "hostnames": sorted(ev["hostnames"])[:6], "first_seen": ev["first_seen"],
            "last_seen": ev["last_seen"], "internetdb_tags": None, "from_cache": False,
        })
    details.sort(key=lambda d: (-d["score"], d["ip"]))

    required_results = [r for r in source_results if not r.get("optional_unconfigured")]
    n_ok = sum(1 for r in required_results if r["ok"])
    all_failed = bool(required_results) and n_ok == 0
    result["source_summary"] = {
        "total": len(source_results),
        "required": len(required_results),
        "ok": n_ok,
        "optional_unconfigured": sum(1 for r in source_results if r.get("optional_unconfigured")),
        "capability_limited": sum(1 for r in source_results if r.get("capability_limited")),
    }
    if details:
        await asyncio.to_thread(_save_origin_cache_sync, domain, details)
    elif all_failed:
        cached = await asyncio.to_thread(_load_origin_cache_sync, domain)
        for c in (cached or {}).get("candidates") or []:
            a = _parse_ipv4(c.get("ip"))
            if a is None or not a.is_global or _is_cloudflare_ip(str(a)):
                continue
            details.append({
                "ip": str(a), "score": c.get("score") or 0, "sources": list(c.get("sources") or []),
                "hostnames": list(c.get("hostnames") or []), "first_seen": c.get("first_seen"),
                "last_seen": c.get("last_seen"), "internetdb_tags": None, "from_cache": True,
            })
        if details:
            result["candidates_from_cache"] = True
            result["cache_saved_at"] = (cached or {}).get("saved_at")

    # ---- ٤) InternetDB ثم الاتصال المباشر (بالتوازي وضمن السقف) ----
    async def _bounded(coro_fn, *args, fallback):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(coro_fn, *args), timeout=max(5.0, hard_deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            return fallback

    if details:
        top = details[:_INTERNETDB_MAX]

        async def _idb(d):
            fb = {"ip": d["ip"], "tested": False, "error": "تجاوز السقف الزمني الكلي", "tags": [], "ports_open": [], "hostnames": []}
            idb = await _bounded(_shodan_internetdb_probe_sync, d["ip"], fallback=fb)
            paid = None
            if _env_key("SHODAN_API_KEY"):
                paid = await _bounded(_shodan_host_api_probe_sync, d["ip"], fallback=None)
            return idb, paid

        idb_pairs = await asyncio.gather(*[_idb(d) for d in top])
        for d, (idb, paid) in zip(top, idb_pairs):
            result["shodan_probes"].append(idb)
            if paid is not None:
                result.setdefault("shodan_host_api_probes", []).append(paid)
            d["internetdb_tags"] = idb.get("tags") or []
            if "cdn" in d["internetdb_tags"]:
                d["score"] -= 5  # CDN آخر لا خادم أصل: يُخفَض ولا يُستبعد
        details.sort(key=lambda d: (-d["score"], d["ip"]))

    result["candidate_details"] = details[:15]
    result["candidate_ips"] = [d["ip"] for d in details]

    if result["candidate_ips"]:
        probe_ips = result["candidate_ips"][:_DIRECT_PROBE_MAX]
        probes = await asyncio.gather(*[
            _bounded(_direct_ip_tls_probe_sync, ip, domain,
                     fallback=_probe_timeout_placeholder(ip, domain, "تجاوز السقف الزمني الكلي لمرحلة الكشف"))
            for ip in probe_ips
        ])
        result["direct_connection_attempts"] = list(probes)

    # ---- ٥) الحكم التشخيصي ----
    direct = result.get("direct_connection_attempts") or []
    strong_direct = [d for d in direct if d.get("tls_handshake_ok") and
                     (d.get("cert_matches_target_domain") is True or d.get("http_head_status") in (200, 206, 301, 302, 307, 308))]
    top_score = details[0]["score"] if details else 0
    if result["candidates_from_cache"]:
        verdict = "candidates_from_cache"
    elif strong_direct:
        verdict = "strong_candidates_unverified"
    elif details and top_score >= 7:
        verdict = "strong_candidates_unverified"
    elif details:
        verdict = "historical_candidates_unverified"
    elif all_failed:
        verdict = "all_sources_failed"
    elif cf_excluded or non_public:
        verdict = "only_cloudflare_or_non_public"
    elif n_ok < len(required_results):
        verdict = "no_candidates_some_sources_failed"
    else:
        verdict = "no_public_records"
    result["discovery_verdict"] = verdict
    result["verdict_explanation"] = _VERDICT_EXPLANATIONS[verdict]
    direct = result.get("direct_connection_attempts") or []
    result["verification_summary"] = {
        "attempted": bool(direct),
        "tls_reachable_count": sum(1 for d in direct if d.get("tls_handshake_ok")),
        "http_responsive_count": sum(1 for d in direct if d.get("http_head_status") is not None),
        "verified_content_ip": None,
        "note": (
            "تم العثور على مرشحين واختبارهم ميدانيًا؛ فشل الاتصال لا يثبت أن المرشح غير صحيح."
            if result.get("candidate_ips") and direct else
            "لم تُوجد مرشحات غير Cloudflare قابلة للاختبار في هذه التشغيلية."
        ),
    }
    result["elapsed_sec"] = round(time.monotonic() - t0, 2)
    return result


# ============================== الوصول المباشر عبر IP الأصل (بديل محاولات النقر) ==============================
# [إضافة] عند ظهور solvable_challenge كان التشخيص ينتظر ثم ينفّذ عدة محاولات
# نقر (EXTENDED_CLICK_ATTEMPTS). إن أمكن جلب الصفحة نفسها فعليًا من IP الأصل
# المُكتشَف (SNI + Host = نطاق الهدف) وحصلنا على محتوى حقيقي بلا صفحة تحقق،
# فلا حاجة لأي نقر: نتخطّاه ونوثّق السبب بالتقرير. عند الفشل يبقى المسار القديم
# (انتظار + نقر) احتياطيًا كما كان بلا أي تغيير.

class _OriginIPConnection(http.client.HTTPSConnection):
    """اتصال HTTPS بعنوان IP مباشرة مع SNI = اسم النطاق الحقيقي (requests
    وحده يرسل SNI = الـIP فيُرفض أو يُعاد شهادة افتراضية). التحقق من الشهادة
    معطَّل عمدًا هنا: صلاحية الشهادة تُفحَص مسبقًا في _direct_ip_tls_probe_sync
    (cert_matches_target_domain)، وهذا الاتصال للتشخيص فقط."""

    def __init__(self, ip: str, sni_hostname: str, port: int = 443, timeout: float = 20):
        super().__init__(ip, port, timeout=timeout)
        self._sni_hostname = sni_hostname

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.sock = ctx.wrap_socket(sock, server_hostname=self._sni_hostname)


_CANONICAL_HREF_PATTERN = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I,
)
_OG_URL_PATTERN = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I,
)


def _page_identity_matches_domain(html: str, target_domain: str) -> dict:
    """[إضافة — بحث محدَّث] معيار هوية إضافي أقوى من مجرد '200 + بلا تحدٍّ
    + صور': استضافة مشتركة (Shared Hosting) قد تُرجع صفحة موقع آخر تمامًا
    على نفس IP بلا أي رفض. نبحث عن canonical/og:url يطابقان النطاق فعليًا،
    وإلا نتحقق من ورود اسم النطاق حرفيًا داخل الصفحة (أضعف لكن أفضل من
    لا شيء). فشل هذا الفحص لا يُسقط usable وحده — يُسجَّل كعلامة ثقة
    إضافية بالتقرير للمراجعة اليدوية."""
    result = {"canonical_or_og_match": None, "domain_mentioned_in_html": False}
    target_l = target_domain.lower()
    for pattern in (_CANONICAL_HREF_PATTERN, _OG_URL_PATTERN):
        m = pattern.search(html)
        if m:
            try:
                found_host = (urlparse(m.group(1)).hostname or "").lower()
            except Exception:
                found_host = ""
            if found_host:
                result["canonical_or_og_match"] = (found_host == target_l or found_host.endswith("." + target_l))
                break
    result["domain_mentioned_in_html"] = target_l in html.lower()
    return result


def _fetch_page_via_origin_ip_sync(ip: str, url: str, port: int = 443,
                                   max_bytes: int = 3_000_000) -> dict:
    """يجلب صفحة الفصل نفسها من IP الأصل مباشرة ويطبّق نفس تصنيف/استخراج مسار
    HTTP الإنتاجي (_classify_challenge_html + extract_images_from_html).
    usable=True فقط لو: 200 + بلا صفحة تحقق + صور مستخرَجة فعليًا. روابط
    الصور المستخرَجة تبقى نسبةً لنطاق الهدف (لا تُستبدل بالـIP)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    result = {
        "target_ip": ip, "status_code": None, "location": None, "server_header": None,
        "protection_category": None, "protection_signatures": [],
        "extracted_image_count": 0, "extracted_sample_urls": [],
        "usable": False, "elapsed_sec": None, "error": None,
    }
    t0 = time.monotonic()
    conn = None
    html = ""
    try:
        conn = _OriginIPConnection(ip, host, port=port, timeout=20)
        conn.request("GET", path, headers={
            "Host": host, "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        resp = conn.getresponse()
        result["status_code"] = resp.status
        result["location"] = resp.getheader("Location")
        result["server_header"] = resp.getheader("Server")
        raw = resp.read(max_bytes)
        html = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        result["elapsed_sec"] = round(time.monotonic() - t0, 2)

    if html:
        result["protection_category"] = _classify_challenge_html(html)
        result["protection_signatures"] = classify_protection_signatures(html)
        extracted = extract_images_from_html(html, url)
        result["extracted_image_count"] = len(extracted)
        result["extracted_sample_urls"] = extracted[:3]
        # [إضافة — بحث محدَّث] معيار هوية إضافي: يُسجَّل دومًا لو توفّر HTML،
        # ويُشترَط صراحةً فقط لو canonical/og:url موجودان وواضح أنهما يشيران
        # لنطاق مختلف تمامًا (استضافة مشتركة تخدم موقعًا آخر) — غياب
        # canonical/og:url كليًا لا يُسقط usable (كثير من المواقع لا تضعهما).
        identity = _page_identity_matches_domain(html, host)
        result["page_identity"] = identity
        identity_conflict = identity["canonical_or_og_match"] is False
        result["usable"] = (
            result["status_code"] == 200
            and result["protection_category"] == "none"
            and len(extracted) > 0
            and not identity_conflict
        )
    return result


async def _verify_origin_ip_access(url: str, origin_discovery: dict, max_ips: int = 3) -> dict:
    """يجرّب جلب الصفحة عبر كل IP أصل مؤهَّل (مصافحة TLS ناجحة + شهادة تطابق
    النطاق) ويتوقف عند أول نجاح فعلي. لا يفترض صحة IP تاريخي: النجاح يُقاس
    بمحتوى الصفحة المُستلَم لا بمجرد الاتصال."""
    result = {"attempted": False, "attempts": [], "verified_ip": None}
    # [معدَّل — بحث محدَّث] الأهلية الآن تُشترط فقط مصافحة TLS ناجحة، لا
    # تطابق الشهادة أيضًا — أصول كثيرة تخدم شهادة افتراضية/ذاتية التوقيع
    # على IP مباشرة بينما شهادة النطاق الحقيقية تُضاف فقط عبر Cloudflare
    # نفسها (SNI-based routing على الحافة، لا على الأصل). اشتراط تطابق
    # الشهادة هنا كان يُسقط أصولًا صحيحة فعليًا. النجاح الحقيقي يُقاس لاحقًا
    # بمحتوى الصفحة (usable) لا بالشهادة — لكن نرتّب الأولوية: مرشَّح
    # بشهادة مطابقة يُجرَّب أولًا (أقوى إشارة ثقة قبل أي محتوى)، ثم البقية.
    tls_ok = [
        d for d in (origin_discovery.get("direct_connection_attempts") or [])
        if d.get("tls_handshake_ok")
    ]
    tls_ok.sort(key=lambda d: not d.get("cert_matches_target_domain"))
    eligible = [d["target_ip"] for d in tls_ok]
    if not eligible:
        return result
    result["attempted"] = True
    for ip in eligible[:max_ips]:
        r = await asyncio.to_thread(_fetch_page_via_origin_ip_sync, ip, url)
        result["attempts"].append(r)
        if r["usable"]:
            result["verified_ip"] = ip
            break
    return result


# ============================== تشخيص عميق (DEEP_DIAGNOSTIC) ==============================
# [إضافة] الخيار موجود فعليًا بملف الـworkflow (compress-chapters-11.yml،
# متغيّر deep_diagnostic) ويُمرَّر كمتغيّر بيئة DEEP_DIAGNOSTIC منذ إضافته،
# لكن لم يكن يُقرأ أو يُستخدَم بأي جزء من الكود حتى الآن — هذا هو التفعيل
# الفعلي الأول له. يعمل فقط لو diagnostic_mode مفعّلًا أصلًا (كما موثَّق
# بوصف الخيار بالـYAML).
DEEP_DIAGNOSTIC = os.environ.get("DEEP_DIAGNOSTIC", "").strip().lower() in ("1", "true", "yes")


async def _runtime_enable_ab_probe(url: str) -> dict:
    """[إضافة — DEEP_DIAGNOSTIC] مقارنة A/B فعلية لتسريب أمر CDP
    'Runtime.enable' — توثيق منشور منذ 2024 (Antoine Vastel/DataDome)
    ومؤكَّد بمصادر أحدث يُثبت أن مكتبات الأتمتة الشائعة (Playwright/
    Puppeteer ومنها Playwright نفسه المُستخدَم بالممر الرئيسي هنا) تُصدر
    هذا الأمر تلقائيًا عند إدارة سياقات تنفيذ الصفحة، وأن هذا الإصدار
    نفسه — بمعزل تام عن أي بصمة JS مثل navigator.webdriver التي يُصحّحها
    stealth — إشارة أتمتة يعتمدها Cloudflare/DataDome فعليًا.

    الفحص هنا مستقل تمامًا عن stealth_comparison الموجود مسبقًا (ذاك يقيس
    أثر تصحيح خصائص JS فقط، لا مستوى بروتوكول CDP نفسه): يُشغَّل هنا متصفح
    منفصل كليًا عبر حزمة patchright (بديل مطابق لواجهة Playwright، مساحة
    استيراد مختلفة تمامًا — patchright.async_api — فلا تعارض مع حزمة
    playwright الأصلية المُثبَّتة بنفس البيئة)، والتي تتفادى بنية المكتبة
    نفسها استدعاء Runtime.enable. تُعاد استخدام classify_challenge_page
    وprobe_challenge_with_extended_wait الموجودتين فعليًا حرفيًا بلا أي
    نسخة موازية — كلاهما يستدعيان واجهة Page عامة فقط (title/query_selector/
    inner_text/wait_for_timeout/reload)، وpatchright مصمَّم كبديل مطابق
    لهذه الواجهة تمامًا فتعمل بلا أي تعديل.

    حقل خام بالكامل: النتيجة تُقارَن يدويًا (بالتقرير) بنتيجة browser_probe
    الرئيسي لنفس الرابط — لا حكم/استنتاج مُدمَج هنا حول "هل هذا هو السبب".
    لو حزمة patchright غير مثبَّتة، يُسجَّل ذلك بحقل error بدل كسر التشخيص
    كله (استيراد كسول داخل الدالة تحديدًا لهذا السبب)."""
    result = {
        "tested": False, "patchright_available": False,
        "protection_category": None, "challenge_detected": None,
        "resolved_after_reload": None, "elapsed_sec": None, "error": None,
    }
    try:
        from patchright.async_api import async_playwright as _patchright_async_playwright
    except ImportError as e:
        result["error"] = f"حزمة patchright غير مثبَّتة بهذه البيئة: {e}"
        return result
    result["patchright_available"] = True

    t0 = time.monotonic()
    try:
        async with _patchright_async_playwright() as pr:
            pr_browser = await pr.chromium.launch()
            try:
                pr_context = await pr_browser.new_context(
                    user_agent=UA, viewport={"width": 1280, "height": 1000}, locale="en-US",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
                )
                pr_page = await pr_context.new_page()
                try:
                    await pr_page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                except Exception as e:
                    result["error"] = f"فشل التحميل الأولي عبر patchright: {e}"

                category = await classify_challenge_page(pr_page)
                result["tested"] = True
                result["protection_category"] = category
                result["challenge_detected"] = category != "none"

                if category == "solvable_challenge":
                    probe = await probe_challenge_with_extended_wait(pr_page)
                    final = probe["final_after_reload"]
                    if final["attempted"]:
                        result["protection_category"] = final["category"] or category
                        result["resolved_after_reload"] = bool(final["resolved"])
                    elif probe["pure_wait"]["resolved_during_pure_wait"]:
                        result["resolved_after_reload"] = True
                        result["protection_category"] = probe["pure_wait"]["final_category_after_wait"]
                else:
                    result["resolved_after_reload"] = category == "none"

                await pr_context.close()
            finally:
                await pr_browser.close()
    except Exception as e:
        result["error"] = ((result["error"] + " | ") if result["error"] else "") + f"استثناء عام بمتصفح patchright: {e}"
    result["elapsed_sec"] = round(time.monotonic() - t0, 2)
    return result


SOURCE_URL_LEAK_JS = """() => {
    try { throw new Error('diagnostic-source-url-probe'); }
    catch (e) { return e.stack || null; }
}"""


async def _source_url_leak_probe(browser, url: str) -> dict:
    """[إضافة — DEEP_DIAGNOSTIC] بصمة stack خام لاستدعاء page.evaluate واحد
    داخل الصفحة — سكربتات page.evaluate/addInitScript المُحقَنة عبر CDP
    تحمل بصمة sourceURL اصطناعية (مصدر مكتبة الأتمتة نفسها، لا الصفحة)
    يمكن لأي سكربت حماية يعمل بنفس الصفحة قراءتها بفحص .stack لاستثناء
    مُلتقَط — هذا ما تصحّحه rebrowser-patches/patchright تحديدًا (sourceURL
    عام مميَّز). تسجيل خام فقط هنا: النص الكامل لـ.stack كما وصل، بلا أي
    مطابقة لسلسلة 'معروفة' مفترَضة — القرار اليدوي لاحقًا يحدد هل يحمل
    توقيعًا مميِّزًا فعليًا لهذا الموقع تحديدًا."""
    result = {"tested": False, "stack_sample": None, "error": None}
    try:
        context = await browser.new_context(user_agent=UA)
    except Exception as e:
        result["error"] = f"فشل فتح سياق منفصل: {e}"
        return result
    try:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            result["error"] = f"فشل التحميل الأولي: {e}"
        try:
            result["stack_sample"] = await page.evaluate(SOURCE_URL_LEAK_JS)
            result["tested"] = True
        except Exception as e:
            result["error"] = ((result["error"] + " | ") if result["error"] else "") + f"فشل evaluate: {e}"
    finally:
        await context.close()
    return result


async def _deep_diagnostic_probes(browser, url: str, main_protection_category: str) -> dict:
    """[إضافة — DEEP_DIAGNOSTIC] يُستدعى فقط لو DEEP_DIAGNOSTIC مفعّل
    وmain_protection_category == 'solvable_challenge' لهذا الرابط تحديدًا
    (نتيجة browser_probe الرئيسي) — لا فائدة تشخيصية من تشغيله على رابط
    غير محجوب أصلًا أو محظور حظرًا نهائيًا لا علاقة له بتسريبات CDP.
    يُجمِّع مسبارين خامّين فقط (راجع تعليق كل دالة) بلا أي طبقة استنتاج/
    تسمية إضافية مُدمَجة بالكود."""
    print("🧬 تشخيص عميق (DEEP_DIAGNOSTIC) — تسريب Runtime.enable (A/B عبر patchright) + بصمة sourceURL...")
    runtime_r = await _runtime_enable_ab_probe(url)
    if runtime_r["error"]:
        print(f"   ⚠️ مسبار Runtime.enable: {runtime_r['error']}")
    elif runtime_r["tested"]:
        print(f"   نتيجة عبر patchright (بلا تسريب Runtime.enable): تصنيف={runtime_r['protection_category']} "
              f"| انحل بعد الإعادة={runtime_r['resolved_after_reload']} | زمن={runtime_r['elapsed_sec']}ث")
        print(f"   ↔️ للمقارنة المباشرة — نتيجة الممر الرئيسي (Playwright عادي، بتسريب Runtime.enable): "
              f"تصنيف={main_protection_category}")

    source_r = await _source_url_leak_probe(browser, url)
    if source_r["error"]:
        print(f"   ⚠️ مسبار sourceURL: {source_r['error']}")
    elif source_r["tested"]:
        print(f"   بصمة stack مُلتقَطة (أول 120 حرفًا): {(source_r['stack_sample'] or '')[:120]!r}")

    return {
        "runtime_enable_leak_probe": runtime_r,
        "source_url_leak_probe": source_r,
    }


# ============================== وضع التشخيص (موسّع) ==============================

def _classify_extraction_tier(noscript_count: int, img_tag_attrs_count: int) -> str:
    """[إضافة — سد فجوة ١، راجع الطلب السابق] extract_images_from_html
    الإنتاجي (مُعاد استخدامه حرفيًا هنا وبـ_curl_cffi_probe_one_sync أدناه،
    لا نسخة موازية من منطق الاستخراج نفسه) يُرجع عددًا إجماليًا واحدًا فقط
    (extracted_image_count) بلا أي إشارة لأي طبقة من تتاليه الداخلي فعليًا
    أنتجت هذا العدد. هذه الدالة تصنّف الطبقة فقط، اعتمادًا على نفس شروط
    الأولوية حرفيًا (noscript إن بلغ MIN_NOSCRIPT_IMAGES ← وإلا data-src/
    data-lazy-src/data-original أو src عادي داخل وسوم <img> ← وإلا noscript
    دون الحد الأدنى ← وإلا آخر ملاذ: regex عام على نص/JSON الصفحة كاملة
    بلا حدود وسم <img> إطلاقًا). الطبقة الأخيرة هي الأعلى خطرًا لالتقاط صور
    دخيلة (OG/SEO thumbnails، ودجات، نسخ معاينة مكررة) بلا أي allowlist —
    حالة procomic الفعلية احتاجت http_content_pattern يدوي تحديدًا بسببها.
    حقل خام بالكامل: تسمية الطبقة فقط، بلا أي قرار allowlist تلقائي."""
    if noscript_count >= MIN_NOSCRIPT_IMAGES:
        return "noscript"
    if img_tag_attrs_count > 0:
        return "img_tag_attrs"
    if noscript_count > 0:
        return "noscript_below_threshold"
    return "last_resort_regex_whole_page"


def _noscript_and_imgtag_img_counts(html: str, url: str) -> tuple[int, int]:
    """[إضافة] عدّ خفيف (noscript_count، img_tag_attrs_count) لتغذية
    _classify_extraction_tier فقط — يُستخدَم بمسارات لا تحتاج تفصيل
    images_via_data_attr/images_via_plain_src المنفصل (كـ_curl_cffi_probe_one_sync
    أدناه)؛ _static_probe_sync يحتفظ بحلقتيه الأصليتين لأنه يعرض ذاك
    التفصيل أيضًا بحقول مستقلة."""
    noscript_blocks = re.findall(r"<noscript>(.*?)</noscript>", html, re.I | re.S)
    ns_imgs = []
    for block in noscript_blocks:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', block):
            ns_imgs.append(urljoin(url, m.group(1)))
    ns_imgs = dedupe(ns_imgs)

    tag_imgs = []
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
            tag_imgs.append(urljoin(url, u))
    tag_imgs = dedupe(tag_imgs)
    return len(ns_imgs), len(tag_imgs)


def _token_pagewide_frequency(html: str, token: str) -> int:
    """[إضافة — سد فجوة ٢، راجع الطلب السابق] suggested_selectors (عبر
    _suggest_selectors_from_unmatched الإنتاجية) يقترح توكنات CSS متكررة
    ضمن سياق الصور غير المطابقة فقط — بلا أي مؤشر هل هذا التوكن نادر
    ومميِّز لسياق الصور تحديدًا، أم توكن utility عام (كـTailwind:
    flex/w-full/relative) يطابق عناصر تنقّل/أزرار بكل الصفحة أيضًا. حالة
    mangatime الفعلية احتاجت فرزًا يدويًا كاملًا بين النوعين لهذا السبب
    بالضبط. هذه الدالة تعدّ فقط: كم عنصر HTML (أي وسم، لا الصور فقط) يحمل
    هذا التوكن بكامل الصفحة — رقم مرتفع (عشرات/مئات) يرجّح توكن عام، رقم
    منخفض/محصور يرجّح توكنًا دلاليًا مميِّزًا. عدّ خام فقط، بلا حكم
    "اقبل/ارفض" مُدمَج هنا."""
    pattern = re.compile(r'class\s*=\s*["\'][^"\']*\b' + re.escape(token) + r'\b[^"\']*["\']', re.I)
    return len(pattern.findall(html))


def _probe_alternate_paths_sync(url: str) -> dict:
    """[جديد] فحص مسارات/نطاقات فرعية بديلة قد لا تغطيها نفس قاعدة WAF —
    راجع تحذير Cloudflare الرسمي نفسه (توثيقهم يضرب مثالًا يستثني /api/
    صراحة من قاعدة تخفيف). قراءة عادية لمحتوى عام فقط بكل الحالات — بعمد
    لا اكتشاف IP أصلي ولا اتصال مباشر بخادم يتجاوز حافة Cloudflare كليًا؛
    ذاك خارج النطاق عمدًا لأنه يُبطل حماية DDoS التي وضعها صاحب الموقع
    وقد يُحمِّل خادمه الحقيقي فعليًا — لا علاقة له بهدف قراءة محتوى عام.

    يفحص: wp-json (REST API — قوالب WordPress/Madara تعرضه افتراضيًا
    ونادرًا ما يُستثنى صراحة بقواعد WAF المبنية على مسارات الصفحات)،
    نسخة AMP (لاحقة /amp/)، feed/ (RSS)، وقائمة قصيرة من نطاقات فرعية
    شائعة فعليًا (لا مسح عدواني ولا قوائم كلمات ضخمة)."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = {
        "wp_json": f"{base}/wp-json/",
        "amp": url.rstrip("/") + "/amp/",
        "rss_feed": f"{base}/feed/",
    }
    host_parts = parsed.netloc.split(".")
    root_host = ".".join(host_parts[-2:]) if len(host_parts) >= 2 else parsed.netloc
    for sub in ["m", "mobile", "api", "cdn", "img", "static", "assets"]:
        candidates[f"subdomain_{sub}"] = f"{parsed.scheme}://{sub}.{root_host}{parsed.path}"

    results = {}
    for key, candidate_url in candidates.items():
        entry = {
            "url": candidate_url, "status_code": None, "error": None,
            "protection_category": None, "cf_mitigation": None, "looks_promising": False,
        }
        try:
            resp = _HTTP_SESSION.get(candidate_url, headers={"User-Agent": UA}, timeout=10, allow_redirects=True)
            entry["status_code"] = resp.status_code
            html = resp.text if resp.ok else ""
            entry["protection_category"] = _classify_challenge_html(html) if html else None
            entry["cf_mitigation"] = _classify_cf_mitigation(
                resp.headers.get("cf-mitigated"), resp.status_code,
                "cloudflare" in resp.headers.get("server", "").lower(),
            )
            if resp.ok and entry["protection_category"] in (None, "none"):
                if key == "wp_json":
                    entry["looks_promising"] = html.strip().startswith("{")
                elif key.startswith("subdomain_"):
                    entry["looks_promising"] = len(extract_images_from_html(html, candidate_url)) > 0
                else:
                    entry["looks_promising"] = len(html) > 200
        except Exception as e:
            entry["error"] = f"{e}"
        results[key] = entry
    return results


def _classify_cf_mitigation(cf_mitigated_value: str | None, status_code: int | None,
                             is_cloudflare: bool) -> dict:
    """[جديد] تصنيف قيمة ترويسة cf-mitigated حسب توثيق Cloudflare الرسمي +
    مصادر تقنية حديثة (2026): القيم "challenge"/"jschallenge"/
    "managed_challenge"/"rate_limited" تعني تحديًا JS "قابلًا للحل نظريًا"
    (نفس الجلسة/البصمة قد تنجح بمحاولة لاحقة) — بينما "block" (أو غياب
    الترويسة كليًا رغم 403 من Cloudflare) يعني الرفض حدث **قبل** مرحلة تسجيل
    نقاط بوت-مانجمنت أصلًا (على الأرجح قاعدة WAF/IP Access Rule صريحة ضد
    نطاق IP)، فلا معنى فعليًا لأي محاولة "بصمة أفضل" — القرار سابق لفحص أي
    بصمة إطلاقًا. هذا الفرق حاسم عمليًا: يحدّد هل تستحق تجربة patchright/
    curl_cffi أصلًا، أم أن المشكلة IP بحتة بصرف النظر عن أي بصمة.

    راجع: developers.cloudflare.com/waf (توثيق رسمي)، ومصادر مستقلة مؤكِّدة
    (PR فعلي بمشروع مفتوح المصدر مايو 2026 يميّز نفس القيم بالضبط)."""
    if not is_cloudflare:
        return {"cf_mitigated_value": cf_mitigated_value, "mitigation_category": "not_cloudflare"}
    if cf_mitigated_value:
        v = cf_mitigated_value.strip().lower()
        if v in ("challenge", "jschallenge", "managed_challenge", "rate_limited"):
            category = "recoverable_challenge"
        elif v == "block":
            category = "hard_block_bot_management"
        else:
            category = f"unknown_value:{v}"
        return {"cf_mitigated_value": cf_mitigated_value, "mitigation_category": category}
    if status_code and status_code >= 400:
        # Cloudflare (عبر ترويسة server) رفض الطلب لكن بلا ترويسة cf-mitigated
        # إطلاقًا — إشارة قوية على قاعدة WAF/Firewall/IP Access Rule صريحة
        # (لا تمر عبر محرك بوت-مانجمنت الذي يضع هذه الترويسة أصلًا).
        return {"cf_mitigated_value": None, "mitigation_category": "waf_or_ip_rule_block_no_header"}
    return {"cf_mitigated_value": None, "mitigation_category": "no_mitigation_observed"}


def _fetch_cdn_cgi_trace_sync(base_url: str) -> dict:
    """[جديد] يجلب /cdn-cgi/trace من نفس نطاق الهدف تحديدًا (لا
    cloudflare.com العام — كل نطاق يستخدم Cloudflare يعرض هذا المسار
    بنفسه، ويعكس بالضبط كيف يرى حافة Cloudflare اتصالنا لنفس المنطقة/
    التوجيه المستخدَمة فعليًا لطلبات هذا الموقع). يكشف: عنوان IP كما تراه
    Cloudflare (قد يختلف عمّا نظنه لو خلفنا وكيل/NAT)، رمز مركز البيانات
    (colo) الذي وجّه إليه طلبنا، نسخة TLS/HTTP المتفاوَض عليها فعليًا —
    بيانات أرضية موثوقة بدل افتراضها. هذا المسار عادة يستجيب حتى لو كان
    الموقع نفسه محجوبًا بقاعدة WAF على مستوى المنطقة (مسار داخلي بحافة
    Cloudflare، لا يمر بمنطق WAF الخاص بالنطاق بالضرورة) — لكن هذا افتراض
    يُختبَر لا يُعتمَد عليه بلا تحقق، فالنتيجة (نجاح/فشل) بحد ذاتها بيانات
    تشخيصية بقدر أهمية محتواها."""
    parsed = urlparse(base_url)
    trace_url = f"{parsed.scheme}://{parsed.netloc}/cdn-cgi/trace"
    result = {"trace_url": trace_url, "status_code": None, "fields": {}, "error": None, "elapsed_sec": None}
    _t0 = time.monotonic()
    try:
        resp = _HTTP_SESSION.get(trace_url, headers={"User-Agent": UA}, timeout=15)
        result["elapsed_sec"] = round(time.monotonic() - _t0, 2)
        result["status_code"] = resp.status_code
        if resp.ok:
            for line in resp.text.splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    result["fields"][k.strip()] = v.strip()
    except Exception as e:
        result["elapsed_sec"] = round(time.monotonic() - _t0, 2)
        result["error"] = f"{e}"
    return result


def _parse_cf_colo(cf_ray_value: str | None) -> str | None:
    """[جديد] cf-ray بصيغة '<16-hex>-<COLO>' — اللاحقة رمز مركز بيانات
    Cloudflare الذي عالج الطلب فعليًا (مثلًا IAD = واشنطن العاصمة). مقارنة
    هذا الرمز بين مسابير مختلفة (ساكن/curl_cffi/متصفح) وبين تشغيلات مختلفة
    تكشف: هل يُوجَّه رانر GitHub Actions دومًا لنفس مركز البيانات (توجيه
    Anycast ثابت حسب مصدر الشبكة)، أم يتنقّل — قد يفسّر أي تفاوت بالنتائج."""
    if not cf_ray_value or "-" not in cf_ray_value:
        return None
    return cf_ray_value.rsplit("-", 1)[-1] or None


def _static_probe_sync(url: str) -> dict:
    result = {
        "status_code": None, "headers_of_interest": {}, "challenge_detected": False,
        "protection_category": "none",
        "protection_signatures": [], "images_via_noscript": 0, "images_via_data_attr": 0,
        "images_via_plain_src": 0, "extracted_image_count": 0, "extracted_sample_urls": [],
        "extraction_tier_used": None,
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
    # [جديد] تصنيف مباشر لطبقة الرفض — راجع تبرير كامل بترويسة _classify_cf_mitigation.
    result["cf_mitigation"] = _classify_cf_mitigation(
        result["headers_of_interest"].get("cf-mitigated"),
        result["status_code"],
        "cloudflare" in result["headers_of_interest"].get("server", "").lower(),
    )
    result["cf_colo"] = _parse_cf_colo(result["headers_of_interest"].get("cf-ray"))

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

    # [إصلاح] "images_at_t0"/"images_after_wait" عدّ خام لكل <img> بالصفحة
    # (شامل الودجات/الشريط الجانبي)، وقريب من الصفر دائمًا فور domcontentloaded
    # — استخدامه لتقرير "هل يحتاج تمريرًا؟" يجعل الشرط صحيحًا شبه دائمًا حتى
    # لمواقع لا تحتاج تمريرًا إطلاقًا. نأخذ بدلًا منه لقطة صور مطابقة فعليًا
    # لمحددات المحتوى (CONTENT_SELECTORS) *قبل* أي تمرير — وهي نفس المقارنة
    # المستخدَمة لاتخاذ قرار do_scroll الحقيقي في الإنتاج.
    extracted = extract_images_from_html(html, url)
    result["extracted_image_count"] = len(extracted)
    result["extracted_sample_urls"] = extracted[:3]
    result["signed_url_params"] = _detect_signed_url_params(extracted)
    result["extraction_tier_used"] = _classify_extraction_tier(len(ns_imgs), len(data_imgs) + len(plain_imgs))

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


CURL_CFFI_IMPERSONATE_PROFILES = ("chrome", "firefox", "safari")


# ============== [إضافة — بحث معمَّق: قدرات تشخيص 2026] ==============
# بصمة JA4 (خليفة JA3 منذ 2023 عبر FoxIO) صارت الإشارة الأهم لدى معظم
# مزوّدي الحماية الكبار (Cloudflare Bot Management، Akamai، DataDome،
# HUMAN/PerimeterX) بحلول 2026 — ومطابقة JA3 وحدها لم تعد كافية: مطابقة
# JA4 دون JA4H (بصمة طبقة HTTP/2 فوقها) تُصنَّف كـ"Chrome بشكل خاطئ"
# وتُحظَر رغم بصمة TLS صحيحة ظاهريًا. هذا القسم يقيس البصمة الحقيقية التي
# يراها أي خادم فعليًا من كل مسار من مسارات الجلب الثلاثة لدينا (طلب
# Python خام، curl_cffi، متصفح الإنتاج الفعلي) — لا افتراضًا نظريًا بأن
# curl_cffi/المتصفح "يُفترَض أن يعمل"، بل قياسًا مباشرًا عبر خدمة تحليل
# عامة معروفة ومُستخدَمة على نطاق واسع لهذا الغرض تحديدًا (tls.peet.ws).
TLS_FINGERPRINT_ECHO_URL = "https://tls.peet.ws/api/all"

# بصمة JA3 القياسية المعروفة تمامًا لمكتبة Python requests/urllib3 (بلا أي
# تخصيص) — موثَّقة كإشارة حظر فورية لدى عدة WAFs بصرف النظر عن أي ترويسات
# User-Agent مصطنعة فوقها (راجع Scrappey: "Chrome/128 but the JA3 hash is
# cd08e31494f9531f560d64c695473da9 — the well-known Python requests
# fingerprint"). مرجع ثابت للمقارنة الفورية بلا حاجة تفسير.
KNOWN_GIVEAWAY_JA3_HASHES = {
    "cd08e31494f9531f560d64c695473da9": "بصمة Python requests/urllib3 القياسية (تُكشَف فورًا لدى معظم WAFs بصرف النظر عن أي User-Agent مُزيَّف فوقها)",
}


def _extract_tls_fingerprint_fields(data: dict) -> dict:
    """يستخرج الحقول الأهم من استجابة tls.peet.ws/api/all — يحتفظ
    بالقاموسين الفرعيين tls/http2 كاملين خامَين أيضًا (لا فقط الحقول
    المُستخرَجة) لأن أسماء الحقول الدقيقة قد تتغيّر مستقبلًا بتحديثات
    الخدمة، وأي حقل إضافي مفيد لا يستحق فقدانه بانتقاء صارم مسبقًا."""
    tls = data.get("tls") or {}
    http2 = data.get("http2") or {}
    ja3_hash = tls.get("ja3_hash")
    return {
        "ja3_hash": ja3_hash,
        "ja4": tls.get("ja4"),
        "peetprint_hash": tls.get("peetprint_hash"),
        "akamai_http2_fingerprint": http2.get("akamai_fingerprint"),
        "akamai_http2_fingerprint_hash": http2.get("akamai_fingerprint_hash"),
        "negotiated_http_version": data.get("http_version") or http2.get("http_version"),
        "known_giveaway_signature": KNOWN_GIVEAWAY_JA3_HASHES.get(ja3_hash),
        "raw_tls": tls, "raw_http2": http2,
    }


def _tls_fingerprint_echo_static_sync() -> dict:
    """[إضافة] بصمة _HTTP_SESSION (Python requests/urllib3 — نفس ما
    يستخدمه static_probe وfetch_mode=http الإنتاجي) كما تراها خدمة تحليل
    خارجية فعليًا، لا كافتراض نظري. يُشغَّل مرة واحدة فقط لكل تشغيلة
    تشخيص كاملة (بصمة عميلنا لا تختلف باختلاف الرابط المُشخَّص) احترامًا
    لكونها خدمة عامة مجانية لطرف ثالث — فشلها لا يوقف بقية التشخيص."""
    try:
        resp = _HTTP_SESSION.get(TLS_FINGERPRINT_ECHO_URL, timeout=15)
        return _extract_tls_fingerprint_fields(resp.json())
    except Exception as e:
        return {"error": f"{e}"}


def _tls_fingerprint_echo_curl_cffi_sync(impersonate: str) -> dict:
    """[إضافة] نفس القياس، لكل بصمة curl_cffi (chrome/firefox/safari) على
    حدة — إثبات فعلي هل انتحال curl_cffi يُنتج JA4/JA4H مطابقَين فعليًا
    لمتصفح حقيقي بهذه البيئة تحديدًا (إصدار curl_cffi ومكتبة TLS
    الأساسية قد يؤثران)، لا افتراض أن الانتحال "يُفترَض أن يعمل"."""
    try:
        from curl_cffi import requests as _curl_requests
    except ImportError as e:
        return {"error": f"حزمة curl_cffi غير مثبَّتة: {e}"}
    try:
        resp = _curl_requests.get(TLS_FINGERPRINT_ECHO_URL, impersonate=impersonate, timeout=15)
        return _extract_tls_fingerprint_fields(resp.json())
    except Exception as e:
        return {"error": f"{e}"}


async def _tls_fingerprint_echo_browser(context) -> dict:
    """[إضافة] عبر context.request — مكدّس شبكة Chromium الفعلي نفسه الذي
    يستخدمه page.goto بالإنتاج (لا مكتبة بايثون منفصلة بديلة عنه) — هذه
    هي البصمة الحقيقية التي يراها أي موقع فعليًا من متصفح الإنتاج بإعداداته
    الحالية (_STEALTH + فلاجات الإطلاق --disable-blink-features)."""
    try:
        resp = await context.request.get(TLS_FINGERPRINT_ECHO_URL, timeout=15000)
        data = await resp.json()
        return _extract_tls_fingerprint_fields(data)
    except Exception as e:
        return {"error": f"{e}"}
# =====================================================================


def _curl_cffi_probe_one_sync(url: str, impersonate: str) -> dict:
    """[إضافة — بصمة TLS/HTTP جديدة، مسبار مقارَن بجانب الموجود لا شجرة
    تستبعده] static_probe (مكتبة requests العادية) يحمل بصمة TLS/HTTP2
    بايثونية قياسية يسهل تمييزها عن متصفح حقيقي، وbrowser_probe يشغّل
    متصفحًا كاملًا (أبطأ بكثير، ويُشغَّل بصرف النظر عن نتيجة static_probe
    أصلًا لنفس سبب مقارنة هذا المسبار هنا). curl_cffi (عبر curl-impersonate)
    يحاكي بصمة TLS/JA3 وترتيب/قيم ترويسات HTTP2 لمتصفح حقيقي فعليًا بلا أي
    تنفيذ JS — يفصل مباشرة نوعًا من الأدلة لا يوفّره أي مسبار آخر هنا: هل
    الحظر يعتمد على بصمة الشبكة/TLS وحدها (فينجح هذا رغم غياب JS) أم يحتاج
    تنفيذ JS فعليًا (فيفشل هذا رغم بصمة TLS مطابقة لمتصفح حقيقي)؟ يُجرَّب
    لكل رابط عبر 3 بصمات متصفح مختلفة (chrome/firefox/safari) — بيانات خام
    أشمل للـAI الذي سينشئ البروفايل، بتكلفة زمن أطول قليلًا (قرار صريح: خُذ
    الأشمل رغم البطء الإضافي)."""
    result = {
        "impersonate": impersonate, "status_code": None, "headers_of_interest": {},
        "challenge_detected": None, "protection_category": None, "protection_signatures": [],
        "extracted_image_count": None, "extracted_sample_urls": [], "extraction_tier_used": None,
        "elapsed_sec": None, "error": None,
    }
    t0 = time.monotonic()
    try:
        from curl_cffi import requests as _curl_requests
    except ImportError as e:
        result["error"] = f"حزمة curl_cffi غير مثبَّتة بهذه البيئة: {e}"
        result["elapsed_sec"] = round(time.monotonic() - t0, 2)
        return result
    try:
        resp = _curl_requests.get(
            url, impersonate=impersonate,
            headers={"Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}, timeout=20,
        )
        result["status_code"] = resp.status_code
        for h in ("server", "cf-ray", "cf-mitigated", "cf-cache-status", "content-type",
                   "set-cookie", "retry-after", "x-sucuri-id", "x-datadome", "x-iinfo"):
            if h in resp.headers:
                result["headers_of_interest"][h] = str(resp.headers[h])[:150]
        html = resp.text
        result["protection_category"] = _classify_challenge_html(html)
        result["challenge_detected"] = result["protection_category"] != "none"
        result["protection_signatures"] = classify_protection_signatures(html)
        result["cf_mitigation"] = _classify_cf_mitigation(
            result["headers_of_interest"].get("cf-mitigated"),
            result["status_code"],
            "cloudflare" in result["headers_of_interest"].get("server", "").lower(),
        )
        result["cf_colo"] = _parse_cf_colo(result["headers_of_interest"].get("cf-ray"))
        extracted = extract_images_from_html(html, url)
        result["extracted_image_count"] = len(extracted)
        result["extracted_sample_urls"] = extracted[:3]
        _ns_count, _tag_count = _noscript_and_imgtag_img_counts(html, url)
        result["extraction_tier_used"] = _classify_extraction_tier(_ns_count, _tag_count)
    except Exception as e:
        result["error"] = f"{e}"
    result["elapsed_sec"] = round(time.monotonic() - t0, 2)
    return result


async def _curl_cffi_fingerprint_probe(url: str) -> dict:
    """يُشغِّل _curl_cffi_probe_one_sync لكل بصمة (chrome/firefox/safari)
    بتوازٍ فعلي — راجع تعليق تلك الدالة للتبرير الكامل. بيانات خام فقط،
    بلا أي حكم/اختيار "أفضل بصمة" مُدمَج هنا."""
    results = await asyncio.gather(*[
        asyncio.to_thread(_curl_cffi_probe_one_sync, url, profile)
        for profile in CURL_CFFI_IMPERSONATE_PROFILES
    ])
    return {"probes": list(results)}


def _wayback_availability_probe_sync(url: str) -> dict:
    """[إضافة — DEEP_DIAGNOSTIC، لأي موقع لا like_manga فقط] فحص خام فقط
    عبر availability API العام لأرشيف الإنترنت (بلا مصادقة، بلا أي محاولة
    SPN2 تصوير جديد): هل توجد أصلًا نسخة مؤرشَفة لهذا الرابط تحديدًا؟ بنية
    الـWayback proxy الكاملة (_wayback_fetch_html بـcompress_chapters.py،
    تصوير SPN2 + مصادقة S3-style + استطلاع دقائق) كانت مربوطة حصرًا
    ببروفايل like_manga_wayback_test، فلا معلومة عن جدوى نفس الفكرة لأي
    موقع آخر يُشخَّص. حقل خام بالكامل: توفّر نسخة/طابعها الزمني/رابطها/
    حالتها فقط، بلا أي قرار use_wayback_proxy مبني عليه هنا — ذاك قرار
    بشري لاحق بعد مراجعة التقرير."""
    result = {"tested": False, "available": None, "snapshot_timestamp": None,
              "snapshot_url": None, "status": None, "error": None}
    try:
        resp = requests.get("https://archive.org/wayback/available", params={"url": url}, timeout=15)
        result["tested"] = True
        resp.raise_for_status()
        data = resp.json()
        snap = data.get("archived_snapshots", {}).get("closest", {})
        result["available"] = bool(snap.get("available"))
        result["snapshot_timestamp"] = snap.get("timestamp")
        result["snapshot_url"] = snap.get("url")
        result["status"] = snap.get("status")
    except Exception as e:
        result["error"] = f"{e}"
    return result


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


# [إضافة — تمييز أحجام الصور، راجع الطلب الأخير] أبعاد إعلانات قياسية
# موثَّقة (IAB Display Ad Unit Portfolio) — تطابق تام لأحد هذه الأزواج
# إشارة أقوى من "شاذ عن أغلب صور هذا الموقع بالذات" لأنها لا تعتمد على
# توزيع الموقع المحدَّد، بل على معيار صناعي عام.
IAB_STANDARD_AD_SIZES = {
    (300, 250), (336, 280), (728, 90), (300, 600), (320, 50), (320, 100),
    (160, 600), (970, 250), (970, 90), (250, 250), (200, 200), (180, 150),
    (120, 600), (300, 1050), (320, 480), (240, 400), (468, 60), (234, 60),
    (88, 31), (120, 90), (120, 60), (120, 240), (125, 125), (220, 250),
    (600, 314), (300, 100), (580, 400),
}


def _analyze_image_dimensions(image_metadata_probe: list[dict]) -> dict:
    """[إضافة — تمييز أحجام الصور لمعرفة ما ليس من المانهوا] يُحسَب بالكامل
    من image_metadata_probe الموجود أصلًا (naturalWidth/naturalHeight بعد
    تحميل كل صورة فعليًا بالمتصفح) — بلا أي طلب شبكي إضافي. توزيع
    (width, height) الفعلي لكل الصور المطابقة، مع العرض الأكثر تكرارًا
    (الأرجح كونه عرض صفحة المحتوى القياسي لهذا الموقع)، وعلم منفصل لكل
    صورة تطابق أحد أبعاد IAB القياسية تمامًا.
    [تنبيه صريح — حدود الفكرة] العرض وحده هو الإشارة الأثبت لمواقع
    الويبتون (تمرير عمودي، الطول يتفاوت طبيعيًا بين الصفحات بحسب تقطيع
    الشريط) — الاعتماد على الطول هناك يُخرج صفحات حقيقية كثيرة كشاذة خطأً.
    لمواقع المانجا المقطَّعة صفحات، نسبة العرض/الطول أدق من العرض وحده.
    صفحة استثنائية شرعية (ملوّنة إضافية/مزدوجة spread) شذوذ حجمي حقيقي
    لكنها محتوى صحيح — لذا هذا كله بيانات خام للمراجعة، بلا أي استبعاد
    تلقائي مُدمَج هنا، بنفس فلسفة كل الحقول المُضافة سابقًا."""
    dims = [
        (it.get("natural_width"), it.get("natural_height"))
        for it in image_metadata_probe
        if it.get("natural_width") and it.get("natural_height")
    ]
    dim_counts = Counter(dims)
    width_counts = Counter(w for w, _h in dims)
    most_common_width = width_counts.most_common(1)[0][0] if width_counts else None

    iab_matches = []
    for it in image_metadata_probe:
        w, h = it.get("natural_width"), it.get("natural_height")
        if w and h and (w, h) in IAB_STANDARD_AD_SIZES:
            iab_matches.append({"width": w, "height": h, "src": it.get("current_src") or it.get("src_attr")})

    return {
        "dimension_distribution": {f"{w}x{h}": c for (w, h), c in dim_counts.most_common(20)},
        "most_common_width": most_common_width,
        "widths_differing_from_most_common": sorted({
            w for w, _h in dims if most_common_width is not None and w != most_common_width
        }),
        "iab_standard_ad_size_matches": iab_matches,
    }


IMAGE_METADATA_JS = """(selectors) => {
    const seen = new Set();
    const out = [];
    for (const sel of selectors) {
        let els;
        try { els = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
        for (const e of els) {
            if (seen.has(e)) continue;
            seen.add(e);
            const rawSrc = e.getAttribute('src') || '';
            const curSrc = e.currentSrc || '';
            const picture = e.closest('picture');
            let pictureSources = [];
            if (picture) {
                pictureSources = Array.from(picture.querySelectorAll('source')).map(s => ({
                    type: s.getAttribute('type') || null,
                    srcset: s.getAttribute('srcset') || s.getAttribute('data-srcset') || null,
                }));
            }
            const checkUrl = curSrc || rawSrc;
            let urlKind = 'http';
            if (checkUrl.startsWith('blob:')) urlKind = 'blob';
            else if (checkUrl.startsWith('data:')) urlKind = 'data';
            out.push({
                src_attr: rawSrc || null,
                current_src: curSrc || null,
                src_differs_from_current_src: !!(rawSrc && curSrc && rawSrc !== curSrc),
                srcset: e.getAttribute('srcset') || e.getAttribute('data-srcset') || null,
                sizes: e.getAttribute('sizes') || null,
                loading_attr: e.getAttribute('loading') || null,
                decoding_attr: e.getAttribute('decoding') || null,
                natural_width: e.naturalWidth || 0,
                natural_height: e.naturalHeight || 0,
                complete: !!e.complete,
                url_kind: urlKind,
                inside_picture: !!picture,
                picture_sources: pictureSources,
            });
        }
    }
    return out;
}"""


CANVAS_ELEMENTS_JS = """() => Array.from(document.querySelectorAll('canvas')).map(c => ({
    width: c.width, height: c.height,
    class_name: (c.className && c.className.toString) ? c.className.toString() : '',
    id: c.id || null,
}))"""


BLOB_DATA_EXTRACT_JS = """async (targetSrc) => {
    try {
        const resp = await fetch(targetSrc);
        const buf = await resp.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = '';
        const chunk = 8192;
        for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return { ok: true, base64: btoa(binary), byte_length: bytes.length,
                 content_type: resp.headers.get('content-type') };
    } catch (e) {
        return { ok: false, error: String(e) };
    }
}"""


CANVAS_EXTRACT_JS = """(idx) => {
    try {
        const c = document.querySelectorAll('canvas')[idx];
        if (!c) return { ok: false, error: 'canvas غير موجود بهذا الفهرس' };
        const dataUrl = c.toDataURL('image/png');
        return { ok: true, data_url_prefix: dataUrl.slice(0, 40),
                 base64_length: dataUrl.length, width: c.width, height: c.height };
    } catch (e) {
        // [مهم] canvas "ملوَّث" (tainted) — رُسمت عليه صورة من نطاق مختلف
        // بلا crossorigin='anonymous' — يرمي SecurityError هنا تحديدًا،
        // ويمنع toDataURL/toBlob كليًا؛ إشارة خام حاسمة: لو ظهر هذا الخطأ،
        // القراءة المباشرة من canvas غير ممكنة إطلاقًا لهذا الموقع، ويحتاج
        // مقاربة مختلفة كليًا (مثل لقطة شاشة مقصوصة بحدود الـcanvas).
        return { ok: false, error: String(e) };
    }
}"""


async def _service_worker_registrations(page) -> list | None:
    """[إضافة] Service Worker مسجَّل قد يعترض طلبات الصور (fetch event) قبل
    وصولها للشبكة فعليًا — واجهة navigator.serviceWorker.getRegistrations
    غير متزامنة، فتُستدعى منفصلة بصيغة async. بيانات خام (نطاق كل تسجيل)
    بلا أي محاولة تفسير محتوى الاعتراض نفسه."""
    try:
        return await page.evaluate(
            "async () => (navigator.serviceWorker ? "
            "(await navigator.serviceWorker.getRegistrations()).map(r => r.scope) : null)"
        )
    except Exception:
        return None


IMAGE_RANGE_PROBE_MAX_SAMPLE = 15
IMAGE_RANGE_PROBE_BYTES = 32000


def _pick_evenly_distributed_urls(urls: list[str], n: int) -> list[str]:
    """[إضافة — سد الفجوة ب، موازنة صريحة بين الشمولية والزمن] عيّنة موزّعة
    بالتساوي عبر كامل قائمة صور الفصل (لا أول/وسط/أخير فقط كـ
    _pick_sample_urls) — حتى n رابطًا مُغطّيًا طول الفصل كله تقريبًا، بسقف
    ثابت يمنع تشغيلة تشخيص لموقع بـ150+ صفحة من التمدد زمنيًا بلا داعٍ."""
    urls = dedupe(urls)
    if len(urls) <= n:
        return urls
    if n <= 1:
        return urls[:1]
    step = (len(urls) - 1) / (n - 1)
    idxs = sorted({round(i * step) for i in range(n)})
    return [urls[i] for i in idxs]


def _image_range_probe_one_sync(img_url: str, referer: str) -> dict:
    """[إضافة — سد الفجوة ب] يقرأ أول ~32 كيلوبايت فقط من كل رابط صورة —
    عبر قراءة streaming مُقفَلة يدويًا عند هذا الحد (تعمل حتى لو تجاهل
    الخادم ترويسة Range وأرسل 200 كاملة، إذ نتوقف عن القراءة من المقبس
    بصرف النظر عمّا ينوي الخادم إرساله)، ثم تُمرَّر البايتات لـ
    PIL.ImageFile.Parser لاستخراج الأبعاد والصيغة الفعلية من رأس الملف
    مباشرة — أرخص بعشرات المرات من تحميل كل صفحة كاملة. يكشف دفعة واحدة:
    توزيع أبعاد كل صفحات الفصل (خروج شاذ = ودجت/إعلان اختلط خطأً بالمحتوى)،
    والصيغة الفعلية المُقدَّمة فعليًا (قد تخالف امتداد الرابط نفسه)."""
    result = {
        "sample_url": img_url, "width": None, "height": None, "format": None,
        "bytes_read": 0, "status_code": None, "range_request_honored": None,
        "content_length_header": None, "error": None,
    }
    try:
        resp = _HTTP_SESSION.get(
            img_url,
            headers={"User-Agent": UA, "Referer": referer, "Range": f"bytes=0-{IMAGE_RANGE_PROBE_BYTES}"},
            timeout=15, stream=True,
        )
        result["status_code"] = resp.status_code
        result["range_request_honored"] = resp.status_code == 206
        result["content_length_header"] = resp.headers.get("content-length")
        raw = resp.raw.read(IMAGE_RANGE_PROBE_BYTES, decode_content=True)
        resp.close()
        result["bytes_read"] = len(raw)
        parser = ImageFile.Parser()
        parser.feed(raw)
        if parser.image:
            result["width"], result["height"] = parser.image.size
            result["format"] = parser.image.format
        else:
            result["error"] = "تعذّر استخراج الأبعاد من أول البايتات المقروءة (قد تحتاج حجمًا أكبر لهذه الصيغة)"
    except Exception as e:
        result["error"] = f"{e}"
    return result


async def _image_dimensions_probe(image_urls: list[str], referer: str) -> dict:
    """يُشغِّل _image_range_probe_one_sync بتوازٍ فعلي على عيّنة موزّعة
    (راجع _pick_evenly_distributed_urls) — بيانات خام فقط، زائد min/max
    عرض وتعداد الصيغ الفعلية (تجميع مباشر لا استنتاج، بنفس نمط
    domain_distribution الموجود مسبقًا)."""
    sample = _pick_evenly_distributed_urls(image_urls, IMAGE_RANGE_PROBE_MAX_SAMPLE)
    results = list(await asyncio.gather(*[
        asyncio.to_thread(_image_range_probe_one_sync, u, referer) for u in sample
    ]))
    widths = [r["width"] for r in results if r["width"]]
    formats = Counter(r["format"] for r in results if r["format"])
    return {
        "total_images_available": len(dedupe(image_urls)),
        "sample_size": len(sample),
        "probes": results,
        "distinct_formats_seen": dict(formats),
        "width_min": min(widths) if widths else None,
        "width_max": max(widths) if widths else None,
    }


_URL_QUALITY_PARAM_NAMES = {
    "quality", "q", "type", "w", "width", "h", "height", "size", "resize",
    "fit", "format", "dpr", "compress", "optimize", "scale",
}


def _url_quality_param_probe_sync(img_url: str, referer: str) -> dict:
    """[إضافة — البند ج] حالة موثَّقة فعليًا: webtoons.com يُضمّن ?type=q90
    (ضغط JPEG بجودة 90) بروابط صور القارئ، وحذف هذا المعامل يرجّع الصورة
    الأصلية الكاملة مجانًا بلا أي مقابل. هذه الدالة تفحص هل رابط الصورة
    يحمل أي معامل استعلام من قائمة أسماء شائعة عبر عدة CDNs (جودة/حجم/
    صيغة)، ولو وُجد، تقارن Content-Length الفعلي (عبر HEAD) بين الرابط
    الأصلي والرابط بعد حذف كل هذه المعاملات معًا. بيانات خام فقط: فرق
    الحجم إن وُجد، وهل الرابط المُجرَّد لا يزال صالحًا أصلًا (بعض الـCDNs
    تتطلب المعامل ولا تعمل بدونه) — بلا أي قرار تلقائي لاستخدام الرابط
    المُجرَّد بالإنتاج."""
    result = {
        "original_url": img_url, "suspicious_params_found": [], "stripped_url": None,
        "original_content_length": None, "stripped_content_length": None,
        "stripped_url_status_code": None, "tested": False, "error": None,
    }
    parsed = urlparse(img_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    suspicious = [k for k, _ in query_pairs if k.lower() in _URL_QUALITY_PARAM_NAMES]
    result["suspicious_params_found"] = suspicious
    if not suspicious:
        return result
    stripped_query = urlencode([(k, v) for k, v in query_pairs if k.lower() not in _URL_QUALITY_PARAM_NAMES])
    stripped_url = urlunparse(parsed._replace(query=stripped_query))
    result["stripped_url"] = stripped_url
    result["tested"] = True
    headers = {"User-Agent": UA, "Referer": referer}
    try:
        r1 = _HTTP_SESSION.head(img_url, headers=headers, timeout=15, allow_redirects=True)
        result["original_content_length"] = r1.headers.get("content-length")
    except Exception as e:
        result["error"] = f"فشل HEAD للرابط الأصلي: {e}"
    try:
        r2 = _HTTP_SESSION.head(stripped_url, headers=headers, timeout=15, allow_redirects=True)
        result["stripped_url_status_code"] = r2.status_code
        result["stripped_content_length"] = r2.headers.get("content-length")
    except Exception as e:
        result["error"] = ((result["error"] + " | ") if result["error"] else "") + f"فشل HEAD للرابط المُجرَّد: {e}"
    return result


async def _browser_probe(browser, url: str, diag_dir: Path, slug: str,
                         skip_click_reason: str | None = None) -> dict:
    result = {
        "click_attempts_skipped_reason": None,
        "navigated": False, "title": None, "challenge_detected": False,
        "protection_category": "none",
        "challenge_resolved_after_reload": None, "protection_signatures": [],
        "images_at_t0": None, "images_after_wait": None, "images_after_scroll": None,
        "selector_match_counts": {}, "unmatched_img_count": 0, "widget_excluded_count": 0,
        "widget_excluded_samples": [], "suggested_selectors": [], "suggested_selectors_pagewide_frequency": {},
        "domain_distribution": {},
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
        # [إضافة — سد فجوة "بيانات كل الصور"] راجع تعليقات الدوال أعلاه
        # (IMAGE_METADATA_JS، _image_dimensions_probe، إلخ) للتبرير الكامل.
        "image_metadata_probe": [], "image_url_kind_counts": {}, "image_dimension_analysis": {},
        "canvas_elements": [], "service_worker_scopes": None,
        "blob_data_extraction_probe": None, "canvas_extraction_probe": None,
        "image_dimensions_probe": None, "url_quality_param_probe": None,
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
    elif result["protection_category"] == "solvable_challenge" and skip_click_reason:
        # [تعديل] الوصول عبر IP الأصل مؤكَّد فعليًا — لا انتظار صافٍ ولا نقر.
        print(f"  🎯 تحدٍّ قابل للحل، لكن {skip_click_reason} — تخطّي الانتظار الصافي ومحاولات النقر")
        result["click_attempts_skipped_reason"] = skip_click_reason
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
    if result["suggested_selectors"]:
        # [إضافة — سد فجوة ٢] لا حاجة لتمرير إضافي على الصفحة — full_page_html
        # يُحسَب مرة واحدة هنا فقط لو وُجدت توكنات مُقترَحة أصلًا.
        try:
            _full_page_html = await page.content()
        except Exception:
            _full_page_html = ""
        result["suggested_selectors_pagewide_frequency"] = {
            tok: _token_pagewide_frequency(_full_page_html, tok.lstrip("."))
            for tok in result["suggested_selectors"]
        } if _full_page_html else {}

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

    # ============== [إضافة — سد فجوة "بيانات كل الصور"] ==============
    # راجع IMAGE_METADATA_JS/CANVAS_ELEMENTS_JS/_image_dimensions_probe
    # وما يليها أعلى الملف للتبرير الكامل لكل حقل هنا.
    try:
        result["image_metadata_probe"] = await page.evaluate(IMAGE_METADATA_JS, list(CONTENT_SELECTORS))
    except Exception as e:
        result["image_metadata_probe"] = []
        print(f"  ⚠️ تعذّر مسبار بيانات الصور (IMAGE_METADATA_JS): {e}")
    result["image_url_kind_counts"] = dict(
        Counter(it.get("url_kind") for it in (result["image_metadata_probe"] or []))
    )
    result["image_dimension_analysis"] = _analyze_image_dimensions(result["image_metadata_probe"] or [])

    try:
        result["canvas_elements"] = await page.evaluate(CANVAS_ELEMENTS_JS)
    except Exception:
        result["canvas_elements"] = []
    result["service_worker_scopes"] = await _service_worker_registrations(page)

    # [إضافة — طلب صريح: عيّنة استخراج فعلي واحدة عند اكتشاف blob:/data:]
    blob_or_data_items = [
        it for it in (result["image_metadata_probe"] or []) if it.get("url_kind") in ("blob", "data")
    ]
    if blob_or_data_items:
        target = blob_or_data_items[0].get("current_src") or blob_or_data_items[0].get("src_attr")
        proof = {"target": target, "ok": None, "error": None}
        if target:
            try:
                extract_r = await page.evaluate(BLOB_DATA_EXTRACT_JS, target)
            except Exception as e:
                extract_r = {"ok": False, "error": str(e)}
            proof["ok"] = extract_r.get("ok")
            proof["error"] = extract_r.get("error")
            proof["byte_length"] = extract_r.get("byte_length")
            proof["content_type"] = extract_r.get("content_type")
            if extract_r.get("ok") and extract_r.get("base64"):
                try:
                    raw_bytes = base64.b64decode(extract_r["base64"])
                    valid, why = _validate_image_bytes(raw_bytes)
                    proof["decoded_and_validated_as_real_image"] = valid
                    if not valid:
                        proof["validation_failure_reason"] = why
                    else:
                        with Image.open(BytesIO(raw_bytes)) as im:
                            proof["decoded_dimensions"] = im.size
                            proof["decoded_format"] = im.format
                except Exception as e:
                    proof["decode_error"] = str(e)
        result["blob_data_extraction_probe"] = proof

    # [إضافة — طلب صريح: عيّنة استخراج فعلي واحدة عند وجود canvas]
    if result["canvas_elements"]:
        try:
            result["canvas_extraction_probe"] = await page.evaluate(CANVAS_EXTRACT_JS, 0)
        except Exception as e:
            result["canvas_extraction_probe"] = {"ok": False, "error": str(e)}

    # [إضافة — سد فجوة ب: مسبار Range موزّع عبر كامل صور الفصل]
    _all_content_urls = dedupe([it["url"] for it in filtered if it.get("url")])
    if _all_content_urls:
        result["image_dimensions_probe"] = await _image_dimensions_probe(_all_content_urls, url)
        # [إضافة — البند ج] فحص معامل جودة/حجم برابط الصورة الأولى فقط —
        # خاصية على مستوى نمط الرابط نفسه (لا تختلف عادةً بين صور الفصل
        # الواحد)، فعيّنة واحدة كافية.
        result["url_quality_param_probe"] = await asyncio.to_thread(
            _url_quality_param_probe_sync, _all_content_urls[0], url
        )
    # ====================================================================

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

    # [إضافة] كشف خادم الأصل الحقيقي خلف Cloudflare — يُشغَّل هنا (مباشرة
    # بعد المعلومات الشبكية الأساسية ①⓪، وقبل أي مسبار HTTP/متصفح) لأنه
    # مستقل تمامًا عن حالة الحماية بهذا الرابط تحديدًا (لا ينتظر تصنيف
    # solvable_challenge/final_block كـ_deep_diagnostic_probes) — بصمة
    # الاستضافة خاصية على مستوى النطاق نفسه لا الرابط المفرد. راجع تبرير
    # كامل بتعليقات _origin_server_discovery وما يستدعيه أعلى الملف.
    print("⓪-ب كشف خادم الأصل الحقيقي خلف Cloudflare (CT متعدد المصادر + DNS تاريخي + SPF/MX + InternetDB)...")
    origin_discovery = await _origin_server_discovery(url)
    for _s in origin_discovery.get("source_status") or []:
        _key = " 🔑" if _s.get("api_key_used") else ""
        if _s["ok"]:
            _note = f" | {_s['note']}" if _s.get("note") else ""
            print(f"   ✅ [{_s['source']}{_key}] أسماء={_s['hostnames_count']} IPs={_s['ips_count']} "
                  f"| محاولات={_s['attempts']} | {_s['elapsed_sec']}ث{_note}")
        else:
            print(f"   ❌ [{_s['source']}{_key}] {_s['error']} | محاولات={_s['attempts']} | {_s['elapsed_sec']}ث")
    print(f"   🧾 حكم الكشف: {origin_discovery.get('discovery_verdict')} — {origin_discovery.get('verdict_explanation')} "
          f"(زمن={origin_discovery.get('elapsed_sec')}ث من سقف {origin_discovery.get('budget_sec')}ث)")
    if origin_discovery.get("candidates_from_cache"):
        print(f"   ⚠️ المرشحون التاليون من الذاكرة الاحتياطية (محفوظة بتاريخ {origin_discovery.get('cache_saved_at')}) — قد يكونون قديمين")
    _nonpub = origin_discovery.get("candidate_ips_excluded_non_public") or []
    if _nonpub:
        print(f"   🚫 استُبعِد {len(_nonpub)} عنوان خاص/غير عام: {_nonpub[:5]}")
    cf_excluded = origin_discovery.get("candidate_ips_excluded_as_cloudflare") or []
    if cf_excluded:
        print(f"   🚫 استُبعِد {len(cf_excluded)} مرشَّح يقع ضمن نطاقات Cloudflare نفسها (لا فائدة من اختباره): {cf_excluded[:5]}")
    if origin_discovery.get("candidate_ips"):
        print(f"   🎯 IPs مُرشَّحة بعد الاستبعاد ({len(origin_discovery['candidate_ips'])}): {origin_discovery['candidate_ips'][:5]}")
        for _d in (origin_discovery.get("candidate_details") or [])[:5]:
            print(f"     [ترتيب] {_d['ip']}: درجة={_d['score']} | مصادر={_d['sources']} | مضيفات={_d['hostnames'][:3]} "
                  f"| ظهور={_d.get('first_seen')}→{_d.get('last_seen')}" + (" | ⚠️ من الذاكرة الاحتياطية" if _d.get("from_cache") else ""))
        for idb_r in origin_discovery.get("shodan_probes") or []:
            if idb_r.get("tested"):
                cdn_flag = " ⚠️ الوسم يشير لكونه CDN آخر (Fastly/Akamai/...) لا أصلًا" if "cdn" in (idb_r.get("tags") or []) else ""
                print(f"     [InternetDB] {idb_r['ip']}: منافذ={idb_r.get('ports_open', [])} "
                      f"| مضيفات={idb_r.get('hostnames', [])[:3]} | وسوم={idb_r.get('tags', [])}{cdn_flag}")
            elif idb_r.get("error") and "404" not in idb_r["error"]:
                print(f"     [InternetDB] {idb_r['ip']}: ⚠️ {idb_r['error']}")
        for paid_r in origin_discovery.get("shodan_host_api_probes") or []:
            if paid_r.get("tested"):
                print(f"     [Shodan API مدفوع] {paid_r['ip']}: {paid_r.get('org', '؟')} ({paid_r.get('country', '؟')})")
            elif paid_r.get("error"):
                print(f"     [Shodan API مدفوع] {paid_r['ip']}: ⚠️ {paid_r['error']}")
        for direct_r in origin_discovery.get("direct_connection_attempts") or []:
            if direct_r.get("tls_handshake_ok"):
                match_flag = "✅ يطابق النطاق" if direct_r.get("cert_matches_target_domain") else "⚠️ لا يطابق النطاق (لا يُسقِط الأهلية وحده)"
                print(f"     [اتصال مباشر] {direct_r['target_ip']}: مصافحة TLS نجحت — "
                      f"CN={direct_r.get('tls_cert_cn')!r} ({match_flag}) — "
                      f"HTTP={direct_r.get('http_head_status')} — الجهة المُصدِرة={direct_r.get('tls_cert_issuer_org')!r}")
            else:
                print(f"     [اتصال مباشر] {direct_r['target_ip']}: ❌ {direct_r.get('error')}")
    else:
        print(f"   ℹ️ لا IPs مُرشَّحة للأصل الحقيقي — {origin_discovery.get('verdict_explanation')}")

    print("⓪-ج جلب الصفحة فعليًا عبر IP الأصل (SNI + Host = النطاق) بدل محاولات النقر...")
    origin_access = await _verify_origin_ip_access(url, origin_discovery)
    skip_click_reason = None
    if not origin_access["attempted"]:
        print("   ℹ️ لا IP بمصافحة TLS ناجحة — تبقى محاولات النقر احتياطًا عند ظهور تحدٍّ")
    else:
        for att in origin_access["attempts"]:
            if att["error"] and att["status_code"] is None:
                print(f"   ❌ {att['target_ip']}: {att['error']}")
            else:
                identity = att.get("page_identity") or {}
                identity_note = ""
                if identity.get("canonical_or_og_match") is False:
                    identity_note = " ⚠️ canonical/og:url يشير لنطاق مختلف — استضافة مشتركة محتملة، استُبعِد"
                print(f"   {'✅' if att['usable'] else '⚠️'} {att['target_ip']}: HTTP={att['status_code']} "
                      f"| تصنيف الحماية={att['protection_category']} | صور مستخرَجة={att['extracted_image_count']} "
                      f"| زمن={att['elapsed_sec']}ث{identity_note}")
        if origin_access["verified_ip"]:
            skip_click_reason = f"الوصول المباشر عبر IP الأصل {origin_access['verified_ip']} مؤكَّد بمحتوى فعلي"
            print(f"   🎯 {skip_click_reason} — لن تُنفَّذ محاولات النقر")
        else:
            print("   ⚠️ لم يُثمر أي IP عن صفحة صالحة — تبقى محاولات النقر احتياطًا")

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
        print(f"   🧭 الطبقة الفعلية التي أنتجت هذا العدد: {static_r['extraction_tier_used']!r}"
              + (" ⚠️ آخر ملاذ (regex عام بلا حدود وسم <img>) — راجع العيّنات يدويًا؛ صور دخيلة (OG/ودجات) ممكنة بلا allowlist"
                 if static_r['extraction_tier_used'] == "last_resort_regex_whole_page" else ""))
        if static_r["sample_image_urls"]:
            print("   عينة روابط صور من HTML الثابت:")
            for u in static_r["sample_image_urls"]:
                print(f"     - {u}")
        if static_r["signed_url_params"]:
            print(f"   🔑 روابط تحمل معاملات توقيع/انتهاء صلاحية: {static_r['signed_url_params']}")

    print("①-ب فحص بصمة curl_cffi (TLS/HTTP٢ لمتصفح حقيقي، بلا أي تنفيذ JS — 3 بصمات: chrome/firefox/safari)...")
    curl_cffi_r = await _curl_cffi_fingerprint_probe(url)
    for pr in curl_cffi_r["probes"]:
        if pr["error"]:
            print(f"   ⚠️ [{pr['impersonate']}] {pr['error']}")
        else:
            print(f"   [{pr['impersonate']}] حالة={pr['status_code']} | تحدٍّ مكتشَف={pr['challenge_detected']} "
                  f"| صور مستخرَجة={pr['extracted_image_count']} (طبقة: {pr['extraction_tier_used']!r}) | زمن={pr['elapsed_sec']}ث")
            if pr["headers_of_interest"]:
                print(f"       ترويسات ملفتة: {pr['headers_of_interest']}")

    print("② فحص متصفح كامل (تحميل + جدار إعلانات + انتظار + تمرير تراكمي)...")
    browser_r = await _browser_probe(browser, url, diag_dir, slug, skip_click_reason=skip_click_reason)
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
        _freq = browser_r.get("suggested_selectors_pagewide_frequency") or {}
        if _freq:
            print(f"      🔢 تكرار كل توكن عبر الصفحة كاملة (لا الصور فقط) — رقم مرتفع يرجّح توكن CSS عام لا دلاليًا مميِّزًا: {_freq}")
    if browser_r["widget_excluded_count"]:
        print(f"   🧹 فلتر الودجات استبعد {browser_r['widget_excluded_count']} صورة — عينات سياق: {browser_r['widget_excluded_samples']}")
    else:
        print("   🧹 فلتر الودجات لم يستبعد أي صورة")
    if browser_r["domain_distribution"]:
        print(f"   توزيع النطاقات: {browser_r['domain_distribution']}")
    if browser_r["signed_url_params"]:
        print(f"   🔑 روابط تحمل معاملات توقيع/انتهاء صلاحية عبر المتصفح: {browser_r['signed_url_params']}")

    print("②-ب بيانات كل الصور (بادئة الرابط، srcset/picture، canvas، Service Worker)...")
    print(f"   تصنيف بادئة روابط الصور (http/blob/data): {browser_r.get('image_url_kind_counts')}")
    _im_meta = browser_r.get("image_metadata_probe") or []
    if _im_meta:
        _differs = sum(1 for it in _im_meta if it.get("src_differs_from_current_src"))
        _in_pic = sum(1 for it in _im_meta if it.get("inside_picture"))
        _incomplete = sum(1 for it in _im_meta if not it.get("complete") or not it.get("natural_width"))
        print(f"   من أصل {len(_im_meta)} عنصر <img> مطابق: currentSrc يخالف src بـ{_differs} | "
              f"داخل <picture> بـ{_in_pic} | لم يكتمل تحميله فعليًا (naturalWidth=0) بـ{_incomplete}")
    _dim = browser_r.get("image_dimension_analysis") or {}
    if _dim.get("dimension_distribution"):
        print(f"   📏 توزيع أبعاد الصور (عرضxطول): {_dim['dimension_distribution']}")
        print(f"      العرض الأكثر تكرارًا (الأرجح عرض صفحة المحتوى القياسي): {_dim['most_common_width']}px"
              + (f" | عروض أخرى ظهرت: {_dim['widths_differing_from_most_common']}"
                 if _dim.get("widths_differing_from_most_common") else ""))
        if _dim.get("iab_standard_ad_size_matches"):
            print(f"      🚩 صور تطابق أبعاد إعلانات قياسية (IAB) تمامًا: {_dim['iab_standard_ad_size_matches']}")
    if browser_r.get("canvas_elements"):
        print(f"   🖼️ عناصر <canvas> موجودة بالصفحة ({len(browser_r['canvas_elements'])}): {browser_r['canvas_elements'][:3]}")
    if browser_r.get("service_worker_scopes"):
        print(f"   ⚙️ Service Worker مسجَّل — النطاقات: {browser_r['service_worker_scopes']}")
    bdp = browser_r.get("blob_data_extraction_probe")
    if bdp:
        print(f"   🧪 عيّنة استخراج فعلي (blob:/data:) — الهدف: {bdp.get('target')}")
        if bdp.get("ok"):
            print(f"      ✅ نجح الاستخراج داخل سياق الصفحة — {bdp.get('byte_length')} بايت "
                  f"({bdp.get('content_type')}) — صورة صالحة فعليًا: {bdp.get('decoded_and_validated_as_real_image')}"
                  + (f" — أبعاد: {bdp.get('decoded_dimensions')} صيغة: {bdp.get('decoded_format')}"
                     if bdp.get("decoded_and_validated_as_real_image") else ""))
        else:
            print(f"      ❌ فشل — {bdp.get('error')}")
    cep = browser_r.get("canvas_extraction_probe")
    if cep:
        if cep.get("ok"):
            print(f"   🧪 عيّنة استخراج فعلي (canvas) — نجح toDataURL — أبعاد: {cep.get('width')}x{cep.get('height')}")
        else:
            print(f"   🧪 عيّنة استخراج فعلي (canvas) — فشل toDataURL — {cep.get('error')} "
                  "(canvas ملوَّث على الأرجح — راجع تعليق CANVAS_EXTRACT_JS)")
    idp = browser_r.get("image_dimensions_probe")
    if idp:
        print(f"   📐 مسبار أبعاد Range — عيّنة {idp['sample_size']} من أصل {idp['total_images_available']} صورة: "
              f"عرض من {idp['width_min']} إلى {idp['width_max']}px | صيغ فعلية مُقدَّمة: {idp['distinct_formats_seen']}")
        _range_ignored = [p for p in idp["probes"] if p.get("status_code") == 200 and not p.get("error")]
        if _range_ignored:
            print(f"      ℹ️ {len(_range_ignored)} من العيّنة تجاهل الخادم ترويسة Range لها (رجع 200 لا 206)")
    uqp = browser_r.get("url_quality_param_probe")
    if uqp and uqp.get("tested"):
        print(f"   🔧 معاملات رابط مشتبَهة (جودة/حجم): {uqp['suspicious_params_found']} — "
              f"الحجم الأصلي: {uqp['original_content_length']} بايت | "
              f"بعد الحذف: {uqp['stripped_content_length']} بايت (status={uqp['stripped_url_status_code']})")
        if uqp.get("error"):
            print(f"      ⚠️ {uqp['error']}")

    print("②-تكرار إعادة فحص كامل بجلسة نظيفة ثانية (فحص اتساق)...")
    browser_r2 = await _browser_probe(browser, url, diag_dir, slug + "-run2", skip_click_reason=skip_click_reason)
    consistency_diffs = _diff_browser_probes(browser_r, browser_r2)
    if consistency_diffs:
        print("   🎲 فروقات مكتشَفة بين التكرارين:")
        for d in consistency_diffs:
            print(f"     - {d}")
    else:
        print("   ✅ النتيجة متطابقة بين التكرارين")

    deep_diag = None
    if DEEP_DIAGNOSTIC:
        deep_diag = {}
        print("🧬 فحص Wayback (DEEP_DIAGNOSTIC، أي موقع) — توفر نسخة مؤرشَفة سابقًا لهذا الرابط تحديدًا...")
        wayback_r = await asyncio.to_thread(_wayback_availability_probe_sync, url)
        deep_diag["wayback_availability_probe"] = wayback_r
        if wayback_r["error"]:
            print(f"   ⚠️ {wayback_r['error']}")
        elif wayback_r["tested"]:
            print(f"   نسخة متوفرة: {wayback_r['available']} | طابع زمني: {wayback_r['snapshot_timestamp']} "
                  f"| status: {wayback_r['status']}"
                  + (f" | رابط: {wayback_r['snapshot_url']}" if wayback_r['snapshot_url'] else ""))

        if browser_r.get("protection_category") == "solvable_challenge":
            cdp_probes = await _deep_diagnostic_probes(browser, url, browser_r.get("protection_category"))
            deep_diag.update(cdp_probes)
        else:
            print(f"🧬 تشخيص عميق (تسريب Runtime.enable/sourceURL): تخطّي — تصنيف الرابط الحالي "
                  f"{browser_r.get('protection_category')!r} (يعمل فقط على solvable_challenge)")

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

    print("⑦ فحص /cdn-cgi/trace (بيانات أرضية من حافة Cloudflare مباشرة)...")
    cdn_trace = await asyncio.to_thread(_fetch_cdn_cgi_trace_sync, url)
    if cdn_trace["fields"]:
        f = cdn_trace["fields"]
        print(f"   ✅ ip={f.get('ip')} colo={f.get('colo')} tls={f.get('tls')} http={f.get('http')} loc={f.get('loc')}")
    else:
        print(f"   ⚠️ لا حقول (status={cdn_trace['status_code']}, error={cdn_trace['error']}) — قد يعني هذا المسار نفسه محجوبًا أيضًا، بيانات بحد ذاتها")

    print("⑧ فحص مسارات/نطاقات فرعية بديلة (wp-json/amp/feed + نطاقات شائعة)...")
    alt_paths = await asyncio.to_thread(_probe_alternate_paths_sync, url)
    promising = [k for k, v in alt_paths.items() if v.get("looks_promising")]
    if promising:
        print(f"   🎯 واعد فعليًا: {', '.join(promising)} — راجع التقرير الكامل للتفاصيل")
    else:
        print(f"   ⚠️ لا مسار بديل واعد من {len(alt_paths)} مُختبَر — راجع التقرير لتفاصيل كل محاولة")

    all_mitigations = [
        static_r.get("cf_mitigation"),
        *[p.get("cf_mitigation") for p in curl_cffi_r.get("probes", [])],
        _classify_cf_mitigation(
            browser_r.get("navigation_response_headers", {}).get("cf-mitigated"),
            browser_r.get("navigation_response_headers", {}).get("status"),
            "cloudflare" in str(browser_r.get("navigation_response_headers", {}).get("server", "")).lower(),
        ),
    ]
    categories = {m["mitigation_category"] for m in all_mitigations if m and m.get("mitigation_category")}
    if categories & {"recoverable_challenge"}:
        mitigation_layer_diagnosis = "recoverable_challenge — يستحق محاولة بصمات/أدوات أفضل (curl_cffi/patchright)"
    elif categories & {"hard_block_bot_management"}:
        mitigation_layer_diagnosis = "hard_block_bot_management — بوت-مانجمنت رفض حتى مع بصمة، تحسين البصمة غير مجدٍ على الأغلب"
    elif categories & {"waf_or_ip_rule_block_no_header"}:
        mitigation_layer_diagnosis = "waf_or_ip_rule_block_no_header — الأرجح قاعدة صريحة ضد نطاق IP، سابقة لأي فحص بصمة"
    else:
        mitigation_layer_diagnosis = "غير حاسم — راجع cf_mitigation بكل مسبار يدويًا"
    print(f"   🧭 التشخيص المُجمَّع: {mitigation_layer_diagnosis}")

    # [إضافة] لو نجح الاتصال المباشر بأي IP أصل مُرشَّح، نضيف ملاحظة صريحة
    # هنا (لا فقط بحقل origin_server_discovery الخام) — لأنها أهم نتيجة
    # عملية ممكنة بكل هذا القسم: تعني إمكانية تجاوز Cloudflare بالكامل
    # بالاتصال المباشر بـIP الأصل (fetch_mode جديد محتمل: "direct_origin")،
    # مع مراعاة أن التطابق التاريخي لا يضمن أن IP ما زال صحيحًا اليوم.
    _origin_reachable = [
        d for d in (origin_discovery.get("direct_connection_attempts") or [])
        if d.get("tls_handshake_ok") and d.get("cert_matches_target_domain")
    ]
    if _origin_reachable:
        print(f"   🎯 خادم أصل محتمل يستجيب مباشرة ويحمل شهادة مطابقة للنطاق: "
              f"{[d['target_ip'] for d in _origin_reachable]} — راجع origin_server_discovery بالتقرير "
              "(تحقق يدوي إضافي مطلوب قبل الاعتماد عليه بالإنتاج، فالمرشَّح تاريخي وقد لا يخدم الموقع اليوم)")

    report_relpath = f"diagnostics/{slug}-report.json"
    report = {
        "url": url, "tls_and_server_info": tls_info, "runner_network_info": runner_info,
        "origin_server_discovery": origin_discovery,
        "direct_origin_access": origin_access,
        "static_probe": static_r, "curl_cffi_probe": curl_cffi_r,
        "browser_probe": browser_r, "browser_probe_second_run": browser_r2,
        "consistency_diffs": consistency_diffs, "rate_limit_probe": rl,
        "history_diffs_since_last_run": history_diffs,
        "deep_diagnostic": deep_diag,
        "cdn_cgi_trace": cdn_trace,
        "alternate_paths_probe": alt_paths,
        "mitigation_layer_diagnosis": mitigation_layer_diagnosis,
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
    print(f"🧬 DEEP_DIAGNOSTIC: {'مفعّل — يضيف فحص توفر Wayback لكل رابط (أي تصنيف، طلب واحد خفيف) + مسبارَي Runtime.enable/sourceURL لكل رابط solvable_challenge تحديدًا (~90-180ث إضافية لكل رابط من هذين الأخيرين)' if DEEP_DIAGNOSTIC else 'غير مفعّل'}")
    if len(chapter_urls) > 3:
        print(f"⚠️ تم إدخال {len(chapter_urls)} رابط — يُفضَّل رابط أو رابطين فقط (كل رابط يفتح متصفحًا كاملًا ويشغّل فحصًا مزدوجًا لكل مرحلة). سيُتابَع بكل الروابط رغم ذلك")

    diag_dir = OUTPUT_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    print("🌐 جلب معلومات شبكة الـrunner الحالي (IP/ASN)...")
    runner_info = await asyncio.to_thread(_runner_network_info_sync)
    if runner_info.get("error"):
        print(f"   ⚠️ تعذّر جلب معلومات الشبكة: {runner_info['error']}")
    else:
        print(f"   IP: {runner_info.get('ip')} | ASN/مزوّد: {runner_info.get('org_asn')} | الموقع: {runner_info.get('city')}/{runner_info.get('country')}")

    print("🔏 قياس بصمة JA4/JA3/HTTP2 الفعلية لكل مسار جلب (عبر tls.peet.ws/api/all)...")
    tls_fp_static = await asyncio.to_thread(_tls_fingerprint_echo_static_sync)
    if tls_fp_static.get("error"):
        print(f"   ⚠️ Python requests/static: {tls_fp_static['error']}")
    else:
        print(f"   Python requests/static: ja3={tls_fp_static.get('ja3_hash')} ja4={tls_fp_static.get('ja4')}"
              + (f" ⚠️ {tls_fp_static.get('known_giveaway_signature')}" if tls_fp_static.get("known_giveaway_signature") else ""))
    tls_fp_curl_cffi = {}
    for _profile in CURL_CFFI_IMPERSONATE_PROFILES:
        _fp = await asyncio.to_thread(_tls_fingerprint_echo_curl_cffi_sync, _profile)
        tls_fp_curl_cffi[_profile] = _fp
        if _fp.get("error"):
            print(f"   ⚠️ curl_cffi[{_profile}]: {_fp['error']}")
        else:
            print(f"   curl_cffi[{_profile}]: ja3={_fp.get('ja3_hash')} ja4={_fp.get('ja4')}")

    reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])

        _tmp_ctx = await browser.new_context(user_agent=UA)
        tls_fp_browser = await _tls_fingerprint_echo_browser(_tmp_ctx)
        await _tmp_ctx.close()
        if tls_fp_browser.get("error"):
            print(f"   ⚠️ متصفح الإنتاج الفعلي: {tls_fp_browser['error']}")
        else:
            print(f"   متصفح الإنتاج الفعلي: ja3={tls_fp_browser.get('ja3_hash')} ja4={tls_fp_browser.get('ja4')}")

        tls_fingerprint_comparison = {
            "static_requests": tls_fp_static,
            "curl_cffi": tls_fp_curl_cffi,
            "production_browser": tls_fp_browser,
            "note": "يُقاس مرة واحدة فقط لكل التشغيلة (بصمة عميلنا نفسه لا تختلف باختلاف الرابط المُشخَّص) عبر خدمة عامة لطرف ثالث (tls.peet.ws) — فشل جزء منها لا يوقف بقية التشخيص.",
        }

        for url in chapter_urls:
            try:
                report = await diagnose_url(browser, url, diag_dir, runner_info)
                report["client_tls_fingerprint_comparison"] = tls_fingerprint_comparison
                reports.append(report)
            except Exception as e:
                print(f"❌ خطأ غير متوقع أثناء تشخيص {url}: {e}")
                reports.append({"url": url, "error": str(e)})
        await browser.close()

    (diag_dir / "summary.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

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
