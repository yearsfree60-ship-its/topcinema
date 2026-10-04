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

import json
import re

from compress_chapters import (WIDGET_CONTEXT_PATTERN, _classify_challenge_html,
                               _looks_like_challenge_html, extract_images_from_html)

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


def collect_dom_images_sb(sb, base_url: str, max_rounds: int = 60) -> tuple[list[str], list[dict]]:
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
        time.sleep(0.7)
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
                        dom_urls, infos = collect_dom_images_sb(sb, url)
                        res["images"] = dom_urls or extract_images_from_html(html, url)
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
