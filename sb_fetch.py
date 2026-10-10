#!/usr/bin/env python3
"""
جلب صفحات الفصول من المواقع المحمية بتحدٍّ Cloudflare عبر SeleniumBase UC+CDP
(متصفح Chrome حقيقي بواجهة تحت Xvfb) — الاستراتيجية الفائزة فعليًا بتشخيص
starzmanga.com (تشغيلة 37178175830: حُلَّ التحدي خلال ~17ث، 12 صورة، cf_clearance).
يُستخدَم من compress_chapters.py كمسار fetch_mode="seleniumbase".

الاستخدام:
    results = fetch_pages_via_seleniumbase(urls)           # متصفح واحد لكل الروابط
    results[url] -> {"ok","html","images","cookies","user_agent","error","waited_sec"}
    sess = build_requests_session(results[url])            # لتحميل الصور بنفس الكوكيز/UA
"""
import base64
import os
import time
from urllib.parse import urlparse, unquote

import requests

import json
import re

from compress_chapters import (WIDGET_CONTEXT_PATTERN, _classify_challenge_html,
                               _looks_like_challenge_html, extract_images_from_html)

DEFAULT_WAIT_SEC = 45.0
# [تسريع] عدد الفصول قبل إعادة تشغيل المتصفح الدائم (تفادي تسرّب الذاكرة)، وتوازي تنزيل صور الفصل داخل الصفحة.
SB_RECYCLE_EVERY = max(1, int(os.environ.get("SB_RECYCLE_EVERY", "20") or 20))
SB_IMG_CONCURRENCY = max(1, min(12, int(os.environ.get("SB_IMG_CONCURRENCY", "8") or 8)))


def _first_ok(sb, getters, default=None):
    for g in getters:
        try:
            obj = sb
            for part in g.split("."):
                obj = getattr(obj, part)
            v = obj()
            if v is not None:
                return v
        except Exception:
            continue
    return default



_DOM_IMAGES_JS = """(() => {
  const out = [];
  document.querySelectorAll('img').forEach(e => {
    const src = e.currentSrc || e.getAttribute('data-src') || e.getAttribute('data-lazy-src') ||
                e.getAttribute('data-original') || e.getAttribute('src') || '';
    let ctx = '', n = e, d = 0;
    while (n && d < 5) { ctx += ' ' + (n.className && n.className.toString ? n.className.toString() : '') + ' ' + (n.id || ''); n = n.parentElement; d++; }
    const r = e.getBoundingClientRect();
    out.push({src: src, w: e.naturalWidth || 0, h: e.naturalHeight || 0,
              aw: parseInt(e.getAttribute('width') || '0') || 0, ah: parseInt(e.getAttribute('height') || '0') || 0,
              rw: Math.round(r.width), rh: Math.round(r.height), ctx: ctx.trim().slice(0, 200)});
  });
  return JSON.stringify(out);
})()"""

_SCROLL_STEP_JS = "(() => { window.scrollBy(0, Math.round(window.innerHeight * 0.85)); return JSON.stringify([window.scrollY + window.innerHeight, document.documentElement.scrollHeight]); })()"


def _sb_eval(sb, js: str):
    for call in (lambda: sb.cdp.evaluate(js), lambda: sb.execute_script("return " + js)):
        try:
            v = call()
            if v is not None:
                return v
        except Exception:
            continue
    return None


_FAST_READING_JS = """(() => {
  const sel = '.reading-content img, .read-container img, #readerarea img, .chapter-content img';
  const out = [];
  document.querySelectorAll(sel).forEach(e => {
    const src = e.getAttribute('data-src') || e.getAttribute('data-lazy-src') ||
                e.getAttribute('data-original') || e.currentSrc || e.getAttribute('src') || '';
    let ctx = '', n = e, d = 0;
    while (n && d < 5) { ctx += ' ' + (n.className && n.className.toString ? n.className.toString() : '') + ' ' + (n.id || ''); n = n.parentElement; d++; }
    out.push({src: src.trim(), ctx: ctx.toLowerCase().slice(0, 200)});
  });
  return JSON.stringify(out);
})()"""


def _fast_reading_urls(sb, base_url: str) -> list[str] | None:
    """[تسريع] روابط صور القراءة مباشرة من سمات data-src/src بلا تمرير ولا انتظار تحميل الصور.
    None = غير جاهز/غير موثوق (عنصر بلا رابط حقيقي، أو روابط مكررة تدل على placeholder) ← المسار البطيء."""
    from urllib.parse import urljoin
    raw = _sb_eval(sb, _FAST_READING_JS)
    try:
        data = json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        return None
    urls, seen = [], set()
    for d in data:
        if WIDGET_CONTEXT_PATTERN.search(d.get("ctx") or ""):
            continue
        src = d.get("src") or ""
        if not src or src.startswith("data:"):
            return None
        u = urljoin(base_url, src)
        if _is_thumbnail_url(u) or u in seen:
            return None
        seen.add(u)
        urls.append(u)
    return urls or None


def collect_dom_images_sb(sb, base_url: str, max_rounds: int = 60) -> tuple[list[str], list[dict]]:
    # مسار سريع: كل وسوم الفصل موجودة بروابطها الحقيقية أصلًا (Madara/lazy-load) ← لا حاجة لتمرير بطيء.
    # يُتحقَّق بقفزة واحدة لآخر الصفحة: لو ثبتت القائمة نفسها نعتمدها، وإلا نرجع للتمرير التدريجي الكامل.
    fast1 = _fast_reading_urls(sb, base_url)
    if fast1:
        _sb_eval(sb, "(() => { window.scrollTo(0, document.documentElement.scrollHeight); return 1; })()")
        time.sleep(0.5)
        if _fast_reading_urls(sb, base_url) == fast1:
            print(f"  ⚡ [SB] مسار سريع: {len(fast1)} صورة بلا تمرير")
            return fast1, []

    """صور المحتوى الفعلية من DOM المُنفَّذ (بعد تمرير تدريجي لتحفيز lazy-load) بمعيار الحجم:
    صور الفصل كبيرة (>=300px عرضًا وطولًا)، بخلاف الشعارات والمصغّرات (75x106...) والودجات.
    يُعيد (روابط مرتّبة بترتيب DOM، كل معلومات <img> للتقرير)."""
    from urllib.parse import urljoin
    last_count, stable, last_bottom = -1, 0, -1
    for _ in range(max_rounds):
        raw = _sb_eval(sb, _SCROLL_STEP_JS)
        try:
            bottom, total = json.loads(raw) if isinstance(raw, str) else (0, 1)
        except Exception:
            bottom, total = 0, 1
        time.sleep(0.5)
        infos = _dom_infos(sb)
        loaded = sum(1 for i in infos if i["w"] >= 300 and i["h"] >= 300)
        at_end = bottom >= total - 5
        if loaded == last_count and at_end:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_count = loaded
        if at_end and bottom == last_bottom and stable == 0 and loaded == 0:
            break
        last_bottom = bottom
    infos = _dom_infos(sb)
    # قوالب Madara/WP-Manga (مثل starzmanga): صور الفصل داخل .reading-content حصرًا — تُفضَّل
    # بلا اعتماد على الحجم وحده (قد تكون الصورة شريطًا طويلًا جدًا أو كسولة التحميل).
    reading = [i for i in infos if "reading-content" in (i.get("ctx") or "")
               and i.get("src") and not i["src"].startswith("data:")]
    if reading:
        infos_for_pick = reading
    else:
        infos_for_pick = infos
    keep, seen = [], set()
    for tier in ((300, 300), (200, 200)):
        for i in infos_for_pick:
            u = urljoin(base_url, i["src"]) if i["src"] and not i["src"].startswith("data:") else None
            if not u or u in seen:
                continue
            w, h = i["w"] or i["rw"] or i["aw"], i["h"] or i["rh"] or i["ah"]
            if w < tier[0] or h < tier[1]:
                continue
            if WIDGET_CONTEXT_PATTERN.search(i["ctx"] or ""):
                continue
            seen.add(u)
            keep.append(u)
        if keep:
            break
    return keep, infos


def _dom_infos(sb) -> list[dict]:
    raw = _sb_eval(sb, _DOM_IMAGES_JS)
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        data = []
    return [d for d in data if isinstance(d, dict)]


def _cookies_dict(sb) -> list:
    raw = _first_ok(sb, ["cdp.get_all_cookies", "get_cookies"], None) or []
    out = []
    for c in raw:
        try:
            if isinstance(c, dict):
                out.append({"name": c.get("name"), "value": c.get("value"),
                            "domain": c.get("domain"), "path": c.get("path", "/")})
            else:
                out.append({"name": getattr(c, "name", None), "value": getattr(c, "value", None),
                            "domain": getattr(c, "domain", None), "path": getattr(c, "path", "/")})
        except Exception:
            continue
    return [c for c in out if c["name"]]


# ---------- تنزيل الصور من داخل جلسة المتصفح نفسها (إصلاح 403 لصور CDN الفرعي) ----------
# صور starzmanga تُخدَّم من نطاق فرعي (smanhwa.starzmanga.com) يرفض طلبات خارج المتصفح (403 HTML)
# حتى مع إعادة الكوكيز؛ التنزيل من داخل Chrome الذي اجتاز التحدّي يحمل بصمة TLS والكوكيز والـReferer كما هي.

_FETCH_IMG_JS = """(() => {
  window.__sbr = null;
  fetch(%s, {credentials: 'include', cache: 'no-store'})
    .then(r => { if (!r.ok) throw new Error('status=' + r.status);
                 const ct = r.headers.get('content-type') || '';
                 return r.blob().then(b => ({b: b, ct: ct})); })
    .then(x => new Promise((res, rej) => { const fr = new FileReader();
        fr.onload = () => res({ct: x.ct, d: String(fr.result).split(',')[1] || ''});
        fr.onerror = () => rej(new Error('filereader')); fr.readAsDataURL(x.b); }))
    .then(x => { window.__sbr = JSON.stringify({ok: 1, ct: x.ct, d: x.d}); })
    .catch(e => { window.__sbr = JSON.stringify({ok: 0, e: String(e)}); });
  return 'started';
})()"""

_POLL_IMG_JS = "(() => window.__sbr === null || window.__sbr === undefined ? '' : window.__sbr)()"


def _in_page_fetch(sb, url: str, timeout: float = 40.0) -> tuple[bytes | None, str]:
    """fetch() داخل الصفحة الحالية ثم استقصاء النتيجة (لا يعتمد على دعم await بواجهة التقييم)."""
    _sb_eval(sb, _FETCH_IMG_JS % json.dumps(url))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.25)
        raw = _sb_eval(sb, _POLL_IMG_JS)
        if not raw or not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except Exception:
            return None, "نتيجة fetch غير مقروءة"
        if not data.get("ok"):
            return None, str(data.get("e") or "فشل fetch")[:120]
        ct = (data.get("ct") or "").lower()
        if ct and not ct.startswith("image/"):
            return None, f"content-type غير صورة: {ct}"
        try:
            raw_bytes = base64.b64decode(data.get("d") or "")
        except Exception:
            return None, "base64 تالف"
        if len(raw_bytes) < 500:
            return None, f"جسم صغير جدًا ({len(raw_bytes)} بايت)"
        return raw_bytes, ""
    return None, "انتهت مهلة fetch"


_FETCH_MANY_JS = r"""((urls, conc) => {
  window.__sbm = {}; window.__sbn = 0; window.__sbtot = urls.length;
  let idx = 0;
  const one = async (u) => {
    try {
      const r = await fetch(u, {credentials: 'include', cache: 'no-store'});
      if (!r.ok) throw new Error('status=' + r.status);
      const ct = r.headers.get('content-type') || '';
      const b = await r.blob();
      const d = await new Promise((res, rej) => { const fr = new FileReader();
        fr.onload = () => res(String(fr.result).split(',')[1] || ''); fr.onerror = () => rej(new Error('filereader'));
        fr.readAsDataURL(b); });
      window.__sbm[u] = JSON.stringify({ok: 1, ct: ct, d: d});
    } catch (e) { window.__sbm[u] = JSON.stringify({ok: 0, e: String(e)}); }
    window.__sbn++;
  };
  const worker = async () => { while (idx < urls.length) { const u = urls[idx++]; await one(u); } };
  for (let i = 0; i < conc; i++) worker();
  return 'started';
})"""


def _in_page_fetch_many(sb, urls: list[str], conc: int = SB_IMG_CONCURRENCY,
                        timeout: float = 90.0) -> dict[str, bytes]:
    """تنزيل متوازٍ (conc صور معًا) من داخل صفحة الفصل. يُعيد ما نجح فقط — الباقي يُعاد بالمسار المتسلسل."""
    out: dict[str, bytes] = {}
    if not urls:
        return out
    _sb_eval(sb, _FETCH_MANY_JS + "(" + json.dumps(urls) + "," + str(conc) + ")")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.15)
        raw = _sb_eval(sb, "(() => JSON.stringify([window.__sbn || 0, window.__sbtot || 0]))()")
        try:
            n, tot = json.loads(raw) if isinstance(raw, str) else (0, 1)
        except Exception:
            continue
        if tot and n >= tot:
            break
    for u in urls:
        raw = _sb_eval(sb, "(() => (window.__sbm && window.__sbm[" + json.dumps(u) + "]) || '')()")
        if not raw or not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
            if not data.get("ok"):
                continue
            ct = (data.get("ct") or "").lower()
            if ct and not ct.startswith("image/"):
                continue
            b = base64.b64decode(data.get("d") or "")
        except Exception:
            continue
        if len(b) >= 500:
            out[u] = b
    return out


SB_HTTP_DOWNLOAD = os.environ.get("SB_HTTP_DOWNLOAD", "true").strip().lower() == "true"


def _probe_http_download(urls: list[str], cookies: list, ua: str | None, referer: str) -> bool:
    """[تسريع جذري] هل يمكن تنزيل الصور خارج المتصفح (curl_cffi بانتحال Chrome + كوكيز التحدّي)؟
    يُفحَص أول/وسط/آخر صورة؛ نجاحها كلها ← يتحرر المتصفح فورًا للفصل التالي وتُنزَّل الصور بالتوازي
    من بايثون. أي إخفاق ← الرجوع للتنزيل بالمتصفح (السلوك المضمون السابق)."""
    try:
        from curl_cffi import requests as cr
    except Exception:
        return False
    sample = list(dict.fromkeys([urls[0], urls[len(urls) // 2], urls[-1]]))
    for u in sample:
        try:
            host = (urlparse(u).hostname or "").lower()
            pairs = []
            for c in cookies or []:
                d = (c.get("domain") or "").lstrip(".").lower()
                if c.get("name") and (not d or host == d or host.endswith("." + d)):
                    pairs.append(f"{c['name']}={c['value']}")
            if not pairs:
                return False
            r = cr.get(u, headers={"User-Agent": ua or "", "Referer": referer, "Cookie": "; ".join(pairs),
                                   "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
                       timeout=20, impersonate="chrome")
            if not r.ok or not (r.headers.get("content-type", "").startswith("image/")) or len(r.content) < 500:
                return False
        except Exception:
            return False
    return True


def download_images_in_browser(sb, image_urls: list[str], page_url: str) -> tuple[dict, dict]:
    """يُنزِّل كل الصور من داخل المتصفح. الطبقة 1: fetch من صفحة الفصل (Referer صحيح تلقائيًا).
    الطبقة 2 (إن منع CORS): فتح رابط الصورة كصفحة أعلى مستوى ثم fetch بنفس الأصل.
    يُعيد (url -> bytes, url -> سبب الفشل)."""
    got: dict[str, bytes] = {}
    errs: dict[str, str] = {}
    page_host = urlparse(page_url).netloc
    cur_host = page_host            # الأصل الذي تقف عليه الصفحة الآن
    try:
        got.update(_in_page_fetch_many(sb, list(dict.fromkeys(image_urls))))
    except Exception:
        pass                        # أي خلل بالتوازي ← يكمل المسار المتسلسل أدناه كما كان
    for u in image_urls:
        if u in got:
            continue
        host = urlparse(u).netloc
        data, err = None, ""
        try:
            data, err = _in_page_fetch(sb, u)          # طبقة 1 (قد تُمنع بـCORS إن اختلف الأصل)
            if data is None and host != cur_host:
                # الطبقة 2: التنقل إلى نطاق الصورة نفسه ثم fetch بنفس الأصل
                try:
                    sb.cdp.get(u)
                except Exception:
                    try:
                        sb.activate_cdp_mode(u)
                    except Exception:
                        pass
                time.sleep(1.0)
                cur_host = host
                data, err2 = _in_page_fetch(sb, u)
                err = err2 or err
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:120]
        if data:
            got[u] = data
        else:
            errs[u] = err or "سبب غير معروف"
    return got, errs


def _norm_path(u: str) -> str:
    p = urlparse(u or "")
    return (p.netloc.lower().removeprefix("www.") + unquote(p.path).rstrip("/")).lower()


def _landed_on_requested(requested: str, current: str | None) -> bool:
    """هل المتصفح استقر فعلًا على صفحة الفصل المطلوبة (لا صفحة المانهوا/الرئيسية/404 بعد تحويل)؟
    نقارن host+path بعد إزالة الشرطة الأخيرة؛ ونسمح بامتداد المسار (مثل /ch-1/ ← /ch-1/page/2)."""
    if not current:
        return True   # تعذّر قراءة الرابط الحالي: لا نحكم بالفشل
    req, cur = _norm_path(requested), _norm_path(current)
    return (cur == req or cur.startswith(req + "/")
            or cur == req + "_1" or cur.startswith(req + "_1/"))


def _resolve_suffixed_chapter_url(sb, url: str, wait_sec: float) -> str | None:
    """بعض المواقع تنشر الفصل بلاحقة _1 (مثل /96/ ← /96_1/). نبني هذا الاحتمال الوحيد فقط
    (بدون أي زيارة إضافية)؛ والمستدعي يفتحه ويتحقق من وجود صور القراءة."""
    p = urlparse(url)
    path = p.path
    if not path.rstrip("/") or path.rstrip("/").endswith("_1"):
        return None
    new_path = path.rstrip("/") + "_1" + ("/" if path.endswith("/") else "")
    return p._replace(path=new_path).geturl()


def _is_thumbnail_url(u: str) -> bool:
    """مصغّرات ووردبريس (…-75x106.jpg) وشعارات الموقع: ليست صور فصل أبدًا."""
    return bool(re.search(r"-\d{2,4}x\d{2,4}\.(?:jpe?g|png|webp|gif)(?:\?|$)", u, re.I)) \
        or "/wp-content/uploads/starzmanga" in u.lower()


_READING_PROBE_JS = """(() => {
  const sel = '.reading-content img, .read-container img, #readerarea img, .chapter-content img';
  let n = 0;
  document.querySelectorAll(sel).forEach(e => {
    const src = e.currentSrc || e.getAttribute('data-src') || e.getAttribute('data-lazy-src') ||
                e.getAttribute('data-original') || e.getAttribute('src') || '';
    if (src && !src.startsWith('data:') && !/-\\d{2,4}x\\d{2,4}\\.(jpe?g|png|webp|gif)/i.test(src)) n++;
  });
  window.scrollBy(0, Math.round(window.innerHeight * 0.6));
  return JSON.stringify({n: n, imgs: document.images.length, title: document.title.slice(0, 80),
    url: location.href, rc: !!document.querySelector('.reading-content, .read-container, #readerarea, .chapter-content'),
    ready: document.readyState});
})()"""


def _wait_reading_images(sb, timeout: float = 25.0, absent_grace: float | None = None) -> tuple[int, dict]:
    """ينتظر ظهور صور حاوية القراءة الفعلية في DOM (قد تُحقَن بالجافاسكربت متأخرة بعد حل التحدي).
    absent_grace: لو اكتمل تحميل الصفحة ولا حاوية قراءة إطلاقًا طوال هذه المدة ← خروج مبكر (فشل سريع).
    يُعيد (العدد، آخر تشخيص)."""
    deadline = time.monotonic() + timeout
    diag: dict = {}
    absent_since = None
    while True:
        raw = _sb_eval(sb, _READING_PROBE_JS)
        try:
            diag = json.loads(raw) if isinstance(raw, str) else {}
        except Exception:
            diag = {}
        if diag.get("n", 0) > 0:
            return int(diag["n"]), diag
        now = time.monotonic()
        if absent_grace and diag.get("ready") == "complete" and not diag.get("rc"):
            absent_since = absent_since or now
            if now - absent_since >= absent_grace:
                return 0, diag
        else:
            absent_since = None
        if now >= deadline:
            return 0, diag
        time.sleep(0.3)


def _wait_resolved(sb, wait_sec: float) -> tuple[bool, str, float]:
    t0 = time.monotonic()
    deadline = t0 + wait_sec
    next_solve = t0 + 6.0
    solves = 0
    html = ""
    while True:
        title = _first_ok(sb, ["cdp.get_title", "get_title"], "") or ""
        html = _first_ok(sb, ["cdp.get_page_source", "get_page_source"], "") or ""
        if html and _classify_challenge_html(html) in (None, "none") \
                and "just a moment" not in title.lower() and not _looks_like_challenge_html(html):
            return True, html, round(time.monotonic() - t0, 2)
        now = time.monotonic()
        if now >= deadline:
            return False, html, round(now - t0, 2)
        if now >= next_solve and solves < 4:
            solves += 1
            try:
                sb.solve_captcha()
            except Exception:
                pass
            next_solve = now + 8.0
        try:
            sb.sleep(0.7)
        except Exception:
            time.sleep(0.7)


def _fetch_one(sb, url: str, *, activated: bool, wait_sec: float, retries: int,
               download_images: bool) -> tuple[dict, bool]:
    """يجلب فصلًا واحدًا عبر متصفح مفتوح أصلًا. يُعيد (النتيجة، هل فُعِّل وضع CDP).
    res["fatal"]: فشل حتمي (لا حاوية قراءة/تحويل لصفحة أخرى) ← لا فائدة من إعادة المحاولة.
    res["restart"]: المتصفح نفسه مشتبه به (تحدٍّ لم يُحَل/انهيار) ← يُعاد تشغيله."""
    res = {"ok": False, "html": "", "images": [], "cookies": [], "user_agent": None,
           "error": None, "waited_sec": None}
    page_url = url
    _t0 = time.monotonic()
    for attempt in range(1, retries + 2):
        try:
            if not activated:
                sb.activate_cdp_mode(url)
                activated = True
            else:
                try:
                    sb.cdp.get(url)
                except Exception:
                    sb.activate_cdp_mode(url)
            cur0 = _first_ok(sb, ["cdp.get_current_url", "get_current_url"], None)
            if cur0 and urlparse(cur0).netloc == urlparse(url).netloc \
                    and not _landed_on_requested(url, cur0) and "challenge" not in cur0:
                time.sleep(2)
                try:
                    sb.cdp.get(url)
                except Exception:
                    pass
            ok, html, waited = _wait_resolved(sb, wait_sec)
            res["waited_sec"] = waited
            if not ok:
                res["error"] = f"لم يُحَل التحدي خلال {wait_sec:.0f}ث"
                res["restart"] = True
                time.sleep(3)
                continue
            res["ok"], res["html"] = True, html
            cur_url = _first_ok(sb, ["cdp.get_current_url", "get_current_url"], None)
            res["final_url"] = cur_url
            if not _landed_on_requested(url, cur_url):
                res["ok"], res["fatal"] = False, True
                res["error"] = f"أُعيد التوجيه إلى صفحة أخرى: {cur_url}"
                break
            n_read, diag = _wait_reading_images(sb, 25.0, absent_grace=8.0)
            if n_read == 0 and not diag.get("rc"):
                # رابط الفصل الفعلي قد يحمل اللاحقة _1 (/96/ ← /96_1/) — نجربها مرة واحدة
                real = _resolve_suffixed_chapter_url(sb, url, wait_sec)
                if real:
                    print(f"  🔗 [SB] رابط الفصل الفعلي بلاحقة: {real}")
                    try:
                        sb.cdp.get(real)
                    except Exception:
                        sb.activate_cdp_mode(real)
                    ok3, html3, _w3 = _wait_resolved(sb, wait_sec)
                    if ok3:
                        html = html3
                    n_read, diag = _wait_reading_images(sb, 25.0, absent_grace=8.0)
                    if n_read > 0:
                        page_url = real
                        res["final_url"] = real
                    elif not diag.get("rc"):
                        res["ok"], res["fatal"] = False, True
                        res["error"] = "الرابط الأصلي ورابط _1 بلا حاوية قراءة — تخطّي الفصل"
                        print(f"  ⏭️ [SB] فشل {url} و{real} — الانتقال للفصل التالي")
                        break
            if n_read == 0:
                print(f"  ⚠️ [SB] حاوية القراءة فارغة — إعادة تحميل الصفحة. تشخيص: {diag}")
                try:
                    sb.cdp.get(page_url)
                except Exception:
                    sb.activate_cdp_mode(page_url)
                ok2, html2, _w = _wait_resolved(sb, wait_sec)
                if ok2:
                    html = html2
                n_read, diag = _wait_reading_images(sb, 25.0, absent_grace=8.0)
            if n_read == 0:
                res["ok"] = False
                res["error"] = f"لم تظهر صور الفصل في DOM (حاوية القراءة فارغة/غائبة) — تشخيص: {diag}"
                if not diag.get("rc"):
                    res["fatal"] = True
                    break
                time.sleep(3)
                continue
            _t1 = time.monotonic()
            dom_urls, infos = collect_dom_images_sb(sb, page_url)
            _t2 = time.monotonic()
            if dom_urls:
                res["images"] = dom_urls
            else:
                fb = [u for u in extract_images_from_html(html, page_url) if not _is_thumbnail_url(u)]
                res["images"] = fb
            res["dom_image_info"] = infos[:60]
            try:
                html = _first_ok(sb, ["cdp.get_page_source", "get_page_source"], html) or html
                res["html"] = html
            except Exception:
                pass
            res["cookies"] = _cookies_dict(sb)
            res["user_agent"] = _first_ok(sb, ["cdp.get_user_agent"], None)
            if not res["user_agent"]:
                try:
                    res["user_agent"] = sb.cdp.evaluate("navigator.userAgent")
                except Exception:
                    pass
            if res["images"] and download_images and SB_HTTP_DOWNLOAD \
                    and _probe_http_download(res["images"], res["cookies"], res["user_agent"], page_url):
                print(f"  🚀 [SB] التنزيل خارج المتصفح (curl_cffi) — المتصفح حرّ للفصل التالي ({len(res['images'])} صورة)")
                res["image_bytes"], res["image_errors"] = {}, {}
            elif res["images"] and download_images:
                try:
                    _t3 = time.monotonic()
                    got, errs = download_images_in_browser(sb, res["images"], page_url)
                    print(f"  ⏱️ [SB] فتح+حل+انتظار {_t1-_t0:.1f}ث | جمع الروابط {_t2-_t1:.1f}ث | تنزيل {time.monotonic()-_t3:.1f}ث")
                    res["image_bytes"], res["image_errors"] = got, errs
                    print(f"  🌐 [SB] تنزيل بالمتصفح: {len(got)}/{len(res['images'])} صورة"
                          + (f" — أول سبب فشل: {next(iter(errs.values()))}" if errs else ""))
                    more = _cookies_dict(sb)
                    seen = {(c["name"], c.get("domain")) for c in res["cookies"]}
                    res["cookies"] += [c for c in more if (c["name"], c.get("domain")) not in seen]
                except Exception as e:
                    res["image_errors"] = {"*": f"{type(e).__name__}: {e}"[:200]}
            if res["images"]:
                res.pop("error", None)
                res["error"] = None
                break
            res["ok"], res["error"] = False, "صفحة بلا صور بعد حل التحدي"
        except Exception as e:
            res["ok"] = False
            res["error"] = f"{type(e).__name__}: {e}"[:300]
            res["restart"] = True      # استثناء غير متوقع ← المتصفح مشتبه به
        time.sleep(3)
    if res.get("ok") and not res.get("images"):
        res["ok"] = False
    if res.get("ok"):
        res.pop("restart", None)
    return res, activated


def _sb_kwargs(proxy: str | None) -> dict:
    kw = {"uc": True, "test": True, "locale": "en", "xvfb": True}
    if proxy:
        kw["proxy"] = proxy
    return kw


def fetch_pages_via_seleniumbase(urls: list[str], *, wait_sec: float = DEFAULT_WAIT_SEC,
                                 proxy: str | None = None, retries: int = 2,
                                 download_images: bool = False) -> dict:
    """متصفح واحد لكل الروابط تسلسليًا (cf_clearance تبقى صالحة فيُحَل التحدي مرة واحدة غالبًا)."""
    from seleniumbase import SB
    results: dict = {}
    with SB(**_sb_kwargs(proxy)) as sb:
        activated = False
        for url in urls:
            res, activated = _fetch_one(sb, url, activated=activated, wait_sec=wait_sec,
                                        retries=retries, download_images=download_images)
            results[url] = res
    return results


class SBSession:
    """متصفح SeleniumBase دائم عبر فصول التشغيلة كلها (يُحَل التحدي مرة واحدة بدل كل فصل).
    كل العمليات تُنفَّذ على خيط واحد مخصَّص (واجهة CDP المتزامنة لا تُستعمل من خيوط متعددة).
    يُعاد تشغيل المتصفح تلقائيًا: كل SB_RECYCLE_EVERY فصل، أو بعد فشل يُشتبه فيه المتصفح نفسه."""

    def __init__(self, proxy: str | None = None, recycle_every: int = SB_RECYCLE_EVERY):
        self._proxy, self._recycle = proxy, recycle_every
        self._ex = None
        self._cm = self._sb = None
        self._activated, self._count = False, 0

    def _run(self, fn, *a, **k):
        if self._ex is None:
            from concurrent.futures import ThreadPoolExecutor
            self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sb-session")
        return self._ex.submit(fn, *a, **k).result()

    def _start(self):
        from seleniumbase import SB
        self._cm = SB(**_sb_kwargs(self._proxy))
        self._sb = self._cm.__enter__()
        self._activated, self._count = False, 0

    def _stop(self):
        cm, self._cm, self._sb = self._cm, None, None
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass

    def _job(self, url, wait_sec, retries, download_images):
        if self._sb is not None and self._count >= self._recycle:
            self._stop()
        if self._sb is None:
            self._start()
        res, self._activated = _fetch_one(self._sb, url, activated=self._activated, wait_sec=wait_sec,
                                          retries=retries, download_images=download_images)
        self._count += 1
        if res.get("restart") and not res.get("ok"):
            self._stop()
        return res

    def fetch(self, url: str, *, wait_sec: float = DEFAULT_WAIT_SEC, retries: int = 2,
              download_images: bool = False) -> dict:
        return self._run(self._job, url, wait_sec, retries, download_images)

    def fetch_bytes(self, urls: list[str]) -> dict:
        """احتياطي: تنزيل صور بعينها من داخل المتصفح الحالي (لما فشل تنزيلها خارجه)."""
        if self._sb is None:
            return {}
        return self._run(lambda: _in_page_fetch_many(self._sb, list(urls), conc=4, timeout=60.0))

    def close(self):
        if self._ex is None:
            return
        try:
            self._run(self._stop)
        except RuntimeError:
            self._stop()      # عند إغلاق المفسّر (atexit/sys.exit) لا يقبل المجمّع مهامًا — إغلاق مباشر
        finally:
            self._ex.shutdown(wait=False)
            self._ex = None


def build_requests_session(page_result: dict) -> requests.Session:
    """جلسة requests بنفس كوكيز/UA المتصفح (لتحميل الصور لو CDN الصور خلف التحدي أيضًا)."""
    s = requests.Session()
    if page_result.get("user_agent"):
        s.headers["User-Agent"] = page_result["user_agent"]
    for c in page_result.get("cookies") or []:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/")
    return s
