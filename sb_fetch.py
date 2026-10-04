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
import time
from urllib.parse import urlparse

import requests

from compress_chapters import _classify_challenge_html, _looks_like_challenge_html, extract_images_from_html

DEFAULT_WAIT_SEC = 45.0


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
            sb.sleep(2)
        except Exception:
            time.sleep(2)


def fetch_pages_via_seleniumbase(urls: list[str], *, wait_sec: float = DEFAULT_WAIT_SEC,
                                 proxy: str | None = None, retries: int = 2) -> dict:
    """يفتح متصفحًا واحدًا (Xvfb مدمج) ويجلب كل الروابط تسلسليًا — كوكيز cf_clearance
    تبقى صالحة لباقي الفصول بنفس النطاق فيُحَل التحدي مرة واحدة غالبًا."""
    from seleniumbase import SB
    results: dict = {}
    kw = {"uc": True, "test": True, "locale": "en", "xvfb": True}
    if proxy:
        kw["proxy"] = proxy
    with SB(**kw) as sb:
        for url in urls:
            res = {"ok": False, "html": "", "images": [], "cookies": [], "user_agent": None,
                   "error": None, "waited_sec": None}
            for attempt in range(1, retries + 2):
                try:
                    if attempt == 1 and not results:
                        sb.activate_cdp_mode(url)
                    else:
                        try:
                            sb.cdp.get(url)
                        except Exception:
                            sb.activate_cdp_mode(url)
                    ok, html, waited = _wait_resolved(sb, wait_sec)
                    res["waited_sec"] = waited
                    if ok:
                        res["ok"], res["html"] = True, html
                        res["images"] = extract_images_from_html(html, url)
                        res["cookies"] = _cookies_dict(sb)
                        res["user_agent"] = _first_ok(sb, ["cdp.get_user_agent"], None)
                        if not res["user_agent"]:
                            try:
                                res["user_agent"] = sb.cdp.evaluate("navigator.userAgent")
                            except Exception:
                                pass
                        if res["images"]:
                            break
                        res["error"] = "صفحة بلا صور بعد حل التحدي"
                    else:
                        res["error"] = f"لم يُحَل التحدي خلال {wait_sec:.0f}ث"
                except Exception as e:
                    res["error"] = f"{type(e).__name__}: {e}"[:300]
                time.sleep(3)
            results[url] = res
    return results


def build_requests_session(page_result: dict) -> requests.Session:
    """جلسة requests بنفس كوكيز/UA المتصفح (لتحميل الصور لو CDN الصور خلف التحدي أيضًا)."""
    s = requests.Session()
    if page_result.get("user_agent"):
        s.headers["User-Agent"] = page_result["user_agent"]
    for c in page_result.get("cookies") or []:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/")
    return s
