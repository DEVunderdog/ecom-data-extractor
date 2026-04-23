"""Async Playwright-based generic ecommerce scraper.

Pipeline:
  1. Intelligence probe (framework detect + XHR JSON sniff).
  2. Per-page extraction (JSON-LD → microdata → OG → heuristic DOM).
  3. Autonomous pagination (rel=next → aria-label → .next → load-more → infinite scroll).
  4. Rate limiting + retries with UA rotation.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PWError,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MAX_PAGES = int(os.environ.get("MAX_PAGES", "500"))
MAX_PRODUCTS = int(os.environ.get("MAX_PRODUCTS", "10000"))
MIN_DELAY_SEC = float(os.environ.get("MIN_DELAY_SEC", "0.5"))
MAX_DELAY_SEC = float(os.environ.get("MAX_DELAY_SEC", "2.0"))
NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

CURRENCY_MAP = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}
PRICE_RE = re.compile(r"([\$£€¥₹])\s?(\d[\d,]*(?:\.\d+)?)")
REVIEW_RE = re.compile(r"(\d[\d,]*)\s*(?:reviews?|ratings?)", re.IGNORECASE)

LogFn = Callable[[str, str, Optional[dict]], Awaitable[None]]
CancelFn = Callable[[], Awaitable[bool]]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ua() -> str:
    return random.choice(USER_AGENTS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_price(text: str) -> tuple[Optional[float], Optional[str]]:
    if not text:
        return None, None
    m = PRICE_RE.search(text)
    if not m:
        return None, None
    sym, num = m.group(1), m.group(2).replace(",", "")
    try:
        return float(num), CURRENCY_MAP.get(sym)
    except ValueError:
        return None, CURRENCY_MAP.get(sym)


def _first_truthy(*vals: Optional[str]) -> str:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _absolutize(base: str, maybe_rel: Optional[str]) -> str:
    if not maybe_rel:
        return ""
    try:
        return urljoin(base, maybe_rel)
    except Exception:
        return maybe_rel or ""


# ---------------------------------------------------------------------------
# Extraction strategies (executed inside the browser via page.evaluate)
# ---------------------------------------------------------------------------
_EXTRACT_JS = r"""
() => {
  const pick = (el, sels) => {
    for (const s of sels) {
      const f = el.querySelector(s);
      if (f && (f.textContent || f.getAttribute('content'))) {
        return (f.getAttribute('content') || f.textContent || '').trim();
      }
    }
    return '';
  };

  // --- 1. JSON-LD
  const jsonld = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try {
      const parsed = JSON.parse(s.textContent);
      const list = Array.isArray(parsed) ? parsed : [parsed];
      list.forEach(obj => {
        if (!obj) return;
        const graph = obj['@graph'] ? obj['@graph'] : [obj];
        graph.forEach(g => {
          const t = g && (g['@type'] || '');
          if (t === 'Product' || (Array.isArray(t) && t.includes('Product'))) jsonld.push(g);
        });
      });
    } catch (e) {}
  });

  // --- 2. Microdata
  const micro = [];
  document.querySelectorAll('[itemtype*="schema.org/Product"]').forEach(el => {
    const m = {};
    el.querySelectorAll('[itemprop]').forEach(p => {
      const k = p.getAttribute('itemprop');
      const v = p.getAttribute('content') || p.getAttribute('src') || p.getAttribute('href') || p.textContent;
      if (k && v) m[k] = (v || '').trim();
    });
    if (Object.keys(m).length) micro.push(m);
  });

  // --- 3. Open Graph (single product page)
  const og = {};
  document.querySelectorAll('meta[property^="og:"], meta[property^="product:"], meta[name^="twitter:"]').forEach(m => {
    const k = m.getAttribute('property') || m.getAttribute('name');
    const v = m.getAttribute('content');
    if (k && v) og[k] = v;
  });

  // --- 4. Heuristic DOM scan: find most-repeated container with price+heading
  const priceRe = /[\$£€¥₹]\s?\d+[\d.,]*/;
  const containers = new Map(); // sig -> {nodes:[...]}
  const all = document.querySelectorAll('*');
  for (const el of all) {
    if (!el.children || el.children.length < 3) continue;
    const kids = Array.from(el.children);
    let hits = 0;
    for (const k of kids) {
      const txt = (k.textContent || '').slice(0, 800);
      const hasPrice = priceRe.test(txt);
      const hasHead = !!k.querySelector('h1,h2,h3,h4,strong,.title,.product-title,[itemprop="name"]');
      if (hasPrice && hasHead) hits++;
    }
    if (hits >= 3) {
      // signature = first kid tag+class
      const s = (kids[0].tagName + '.' + (kids[0].className || '')).slice(0, 120);
      const existing = containers.get(s);
      if (!existing || hits > existing.hits) {
        containers.set(s, { hits, kids });
      }
    }
  }
  let heuristic = [];
  if (containers.size) {
    const best = [...containers.values()].sort((a, b) => b.hits - a.hits)[0];
    heuristic = best.kids.filter(k => priceRe.test((k.textContent || '').slice(0, 800))).map(k => {
      const h = k.querySelector('h1,h2,h3,h4,[itemprop="name"],.product-title,.title,strong');
      const a = k.querySelector('a[href]');
      const img = k.querySelector('img');
      const imgSrc = img ? (img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('src') || '') : '';
      return {
        name: (h ? h.textContent : '').trim(),
        price_text: (k.textContent.match(priceRe) || [''])[0],
        link: a ? a.getAttribute('href') : '',
        image: imgSrc,
        sku: k.getAttribute('data-product-id') || k.getAttribute('data-sku') || '',
        rating_text: pick(k, ['[itemprop=ratingValue]', '[aria-label*="star" i]', '.rating', '.stars']),
        review_text: (k.textContent.match(/\d[\d,]*\s*(?:reviews?|ratings?)/i) || [''])[0],
        brand: pick(k, ['[itemprop=brand]', '[data-brand]', '.brand']),
        availability: pick(k, ['[itemprop=availability]', '.availability', '.stock']),
        description: pick(k, ['[itemprop=description]', '.description', '.desc']),
        material: pick(k, ['[itemprop=material]', '[data-material]']),
        size: pick(k, ['[itemprop=size]', '[data-size]']),
        color: pick(k, ['[itemprop=color]', '[data-color]']),
      };
    });
  }

  // Breadcrumbs
  const crumbs = [];
  document.querySelectorAll('nav[aria-label*="breadcrumb" i] a, .breadcrumb a, .breadcrumbs a').forEach(a => {
    const t = (a.textContent || '').trim();
    if (t) crumbs.push(t);
  });

  // Framework detection
  const fw = {
    next: !!window.__NEXT_DATA__,
    nuxt: !!window.__NUXT__,
    react: !!window.__REACT_DEVTOOLS_GLOBAL_HOOK__,
    angular: !!document.querySelector('[ng-version]'),
    vue: !!document.querySelector('[data-v-app], #__vue_app__'),
  };

  return { jsonld, micro, og, heuristic, breadcrumbs: crumbs, framework: fw, title: document.title };
}
"""


def _normalize_from_jsonld(obj: dict, base_url: str, crumbs: list[str]) -> dict:
    offers = obj.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price") or offers.get("lowPrice")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    currency = offers.get("priceCurrency") or ""
    brand = obj.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name") or ""
    rating = (obj.get("aggregateRating") or {}).get("ratingValue")
    try:
        rating_f = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating_f = None
    review_count = (obj.get("aggregateRating") or {}).get("reviewCount")
    try:
        review_i = int(review_count) if review_count is not None else None
    except (TypeError, ValueError):
        review_i = None
    image = obj.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    return {
        "name": _first_truthy(obj.get("name")),
        "price": price_f,
        "currency": currency or "",
        "rating": rating_f,
        "review_count": review_i,
        "sku": _first_truthy(obj.get("sku"), obj.get("mpn"), obj.get("productID")),
        "product_id": _first_truthy(obj.get("productID"), obj.get("sku")),
        "brand": _first_truthy(brand),
        "availability": _first_truthy(offers.get("availability")),
        "image_url": _absolutize(base_url, image if isinstance(image, str) else ""),
        "product_url": _absolutize(base_url, obj.get("url") or base_url),
        "category": " > ".join(crumbs) if crumbs else _first_truthy(obj.get("category")),
        "description": _first_truthy(obj.get("description")),
        "material": _first_truthy(obj.get("material")),
        "size": _first_truthy(obj.get("size")),
        "color": _first_truthy(obj.get("color")),
        "scraped_at": _now(),
        "_source": "jsonld",
    }


def _normalize_from_microdata(m: dict, base_url: str, crumbs: list[str]) -> dict:
    price_f, curr = _parse_price(m.get("price", ""))
    if price_f is None:
        try:
            price_f = float(m.get("price")) if m.get("price") else None
        except (TypeError, ValueError):
            price_f = None
    return {
        "name": _first_truthy(m.get("name")),
        "price": price_f,
        "currency": _first_truthy(m.get("priceCurrency"), curr),
        "rating": float(m["ratingValue"]) if m.get("ratingValue", "").replace(".", "").isdigit() else None,
        "review_count": int(m["reviewCount"]) if m.get("reviewCount", "").isdigit() else None,
        "sku": _first_truthy(m.get("sku"), m.get("productID")),
        "product_id": _first_truthy(m.get("productID"), m.get("sku")),
        "brand": _first_truthy(m.get("brand")),
        "availability": _first_truthy(m.get("availability")),
        "image_url": _absolutize(base_url, m.get("image", "")),
        "product_url": _absolutize(base_url, m.get("url", base_url)),
        "category": " > ".join(crumbs) if crumbs else _first_truthy(m.get("category")),
        "description": _first_truthy(m.get("description")),
        "material": _first_truthy(m.get("material")),
        "size": _first_truthy(m.get("size")),
        "color": _first_truthy(m.get("color")),
        "scraped_at": _now(),
        "_source": "microdata",
    }


def _normalize_from_heuristic(h: dict, base_url: str, crumbs: list[str]) -> dict:
    price_f, curr = _parse_price(h.get("price_text", ""))
    rating_f, _ = _parse_price(h.get("rating_text", ""))  # rarely helpful, try later
    if rating_f is None:
        rm = re.search(r"(\d(?:\.\d+)?)", h.get("rating_text", "") or "")
        if rm:
            try:
                rating_f = float(rm.group(1))
            except ValueError:
                rating_f = None
    review_i = None
    rv = REVIEW_RE.search(h.get("review_text", "") or "")
    if rv:
        try:
            review_i = int(rv.group(1).replace(",", ""))
        except ValueError:
            review_i = None
    link = h.get("link") or ""
    absolute = _absolutize(base_url, link) if link else base_url
    sku_from_url = ""
    try:
        sku_from_url = urlparse(absolute).path.rstrip("/").split("/")[-1] or ""
    except Exception:
        pass
    return {
        "name": _first_truthy(h.get("name")),
        "price": price_f,
        "currency": curr or "",
        "rating": rating_f,
        "review_count": review_i,
        "sku": _first_truthy(h.get("sku"), sku_from_url),
        "product_id": _first_truthy(h.get("sku"), sku_from_url),
        "brand": _first_truthy(h.get("brand")),
        "availability": _first_truthy(h.get("availability")),
        "image_url": _absolutize(base_url, h.get("image", "")),
        "product_url": absolute,
        "category": " > ".join(crumbs) if crumbs else "",
        "description": _first_truthy(h.get("description")),
        "material": _first_truthy(h.get("material")),
        "size": _first_truthy(h.get("size")),
        "color": _first_truthy(h.get("color")),
        "scraped_at": _now(),
        "_source": "heuristic",
    }


def _normalize_from_og(og: dict, base_url: str, crumbs: list[str]) -> Optional[dict]:
    name = og.get("og:title") or og.get("twitter:title")
    price = og.get("product:price:amount") or og.get("og:price:amount")
    if not name and not price:
        return None
    try:
        price_f = float(price) if price else None
    except (TypeError, ValueError):
        price_f = None
    return {
        "name": _first_truthy(name),
        "price": price_f,
        "currency": _first_truthy(og.get("product:price:currency"), og.get("og:price:currency")),
        "rating": None,
        "review_count": None,
        "sku": "",
        "product_id": "",
        "brand": _first_truthy(og.get("product:brand")),
        "availability": _first_truthy(og.get("product:availability")),
        "image_url": _absolutize(base_url, og.get("og:image", "")),
        "product_url": _absolutize(base_url, og.get("og:url", base_url)),
        "category": " > ".join(crumbs) if crumbs else _first_truthy(og.get("product:category")),
        "description": _first_truthy(og.get("og:description"), og.get("twitter:description")),
        "material": "",
        "size": "",
        "color": "",
        "scraped_at": _now(),
        "_source": "og",
    }


async def _extract_on_page(page: Page, base_url: str) -> list[dict]:
    """Run the JS extractor and normalize into a flat list of product dicts."""
    try:
        raw = await page.evaluate(_EXTRACT_JS)
    except PWError:
        return []
    crumbs = raw.get("breadcrumbs") or []
    out: list[dict] = []

    # JSON-LD wins
    for obj in raw.get("jsonld", []) or []:
        n = _normalize_from_jsonld(obj, base_url, crumbs)
        if n["name"]:
            out.append(n)

    # Microdata
    if not out:
        for m in raw.get("micro", []) or []:
            n = _normalize_from_microdata(m, base_url, crumbs)
            if n["name"]:
                out.append(n)

    # Heuristic listing
    if not out:
        for h in raw.get("heuristic", []) or []:
            n = _normalize_from_heuristic(h, base_url, crumbs)
            if n["name"]:
                out.append(n)

    # OG fallback (single product)
    if not out:
        og_one = _normalize_from_og(raw.get("og", {}) or {}, base_url, crumbs)
        if og_one and og_one["name"]:
            out.append(og_one)

    return out


# ---------------------------------------------------------------------------
# Pagination detection
# ---------------------------------------------------------------------------
_NEXT_JS = r"""
() => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    return el ? (el.getAttribute('href') || '') : '';
  };
  let href = pick('a[rel="next"]');
  if (href) return { kind: 'href', href };
  href = pick('[aria-label*="Next" i]');
  if (href) return { kind: 'href', href };
  href = pick('.pagination .next a, .pager .next a, li.next a, a.next');
  if (href) return { kind: 'href', href };
  // text-based
  const anchors = Array.from(document.querySelectorAll('a, button'));
  const match = anchors.find(a => {
    const t = (a.textContent || '').trim().toLowerCase();
    return /^(next|load more|show more|view more|see more)\b/.test(t) && !a.disabled;
  });
  if (match) {
    const h = match.getAttribute('href');
    if (h) return { kind: 'href', href: h };
    return { kind: 'click', selector: null, text: (match.textContent || '').trim() };
  }
  return { kind: 'none' };
}
"""


async def _find_next(page: Page, base_url: str) -> Optional[dict]:
    try:
        r = await page.evaluate(_NEXT_JS)
    except PWError:
        return None
    if not r or r.get("kind") == "none":
        return None
    if r["kind"] == "href":
        h = r.get("href") or ""
        if not h:
            return None
        return {"kind": "href", "url": _absolutize(base_url, h)}
    return r


# ---------------------------------------------------------------------------
# Intelligence probe — collect XHR responses for 3s, inspect JSON
# ---------------------------------------------------------------------------
async def _intelligence_probe(context: BrowserContext, url: str, log: LogFn) -> dict:
    page = await context.new_page()
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    candidates: list[dict] = []

    async def _on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct.lower():
                return
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            body = await resp.json()
            items = None
            if isinstance(body, list):
                items = body
            elif isinstance(body, dict):
                for k in ("data", "results", "products", "items", "hits", "edges"):
                    v = body.get(k)
                    if isinstance(v, list) and v:
                        items = v
                        break
            if not items or not isinstance(items[0], dict):
                return
            sample = items[0]
            keys = {str(k).lower() for k in sample.keys()}
            if any(k in keys for k in ("price", "name", "title", "product_id", "sku")):
                candidates.append({"url": resp.url, "count": len(items)})
        except Exception:  # noqa: BLE001
            pass

    page.on("response", lambda r: asyncio.create_task(_on_response(r)))

    try:
        await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    except (PWTimeout, PWError) as e:
        await log("WARN", f"Probe navigation issue: {type(e).__name__}", {"url": url})

    await asyncio.sleep(3)

    fw = {}
    title = ""
    try:
        fw = await page.evaluate(
            "() => ({ next: !!window.__NEXT_DATA__, nuxt: !!window.__NUXT__, react: !!window.__REACT_DEVTOOLS_GLOBAL_HOOK__, angular: !!document.querySelector('[ng-version]') })"
        )
        title = await page.title()
    except PWError:
        pass

    await page.close()
    best = max(candidates, key=lambda x: x["count"]) if candidates else None
    return {"framework": fw, "title": title, "api_candidate": best["url"] if best else None}


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
async def run_scrape(
    job_id: str,
    url: str,
    log: LogFn,
    save_products: Callable[[list[dict]], Awaitable[int]],
    is_cancelled: CancelFn,
    on_page: Optional[Callable[[], Awaitable[None]]] = None,
) -> dict:
    """
    Run the full scrape. Calls:
      - log(level, message, meta) for each step
      - save_products([dicts]) to persist (returns count saved)
      - is_cancelled() -> bool, checked between pages
    Returns {"pages_scraped": int, "products_count": int}
    """
    await log("INFO", "Scrape starting", {"url": url})
    pages_scraped = 0
    products_count = 0

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(
                user_agent=_ua(),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            await context.set_extra_http_headers({"accept-language": "en-US,en;q=0.9"})

            # Step 1: intelligence probe
            try:
                probe = await _intelligence_probe(context, url, log)
                await log(
                    "INFO",
                    f"Probe: framework={probe['framework']} api_candidate={probe['api_candidate']}",
                    {"title": probe["title"], **probe},
                )
            except Exception as e:  # noqa: BLE001
                await log("WARN", f"Probe failed (non-fatal): {e}", None)

            # Step 2 + 3: navigate pages
            visited: set[str] = set()
            current_url = url
            fail_streak = 0

            while True:
                if await is_cancelled():
                    await log("WARN", "Cancellation detected — stopping", {"pages_scraped": pages_scraped})
                    break
                if pages_scraped >= MAX_PAGES:
                    await log("INFO", f"Page cap reached ({MAX_PAGES})", None)
                    break
                if products_count >= MAX_PRODUCTS:
                    await log("INFO", f"Product cap reached ({MAX_PRODUCTS})", None)
                    break
                if current_url in visited:
                    await log("DEBUG", "Already visited, stopping", {"url": current_url})
                    break
                visited.add(current_url)

                # navigate with retries
                page = await context.new_page()
                page.set_default_navigation_timeout(NAV_TIMEOUT_MS)

                ok = False
                last_err: Optional[str] = None
                for attempt in range(3):
                    try:
                        if attempt > 0:
                            # rotate UA + backoff
                            await context.set_extra_http_headers({"user-agent": _ua()})
                            delay = 2 ** attempt  # 2, 4 (attempt=1→2s, 2→4s)
                            await log(
                                "WARN",
                                f"Retry {attempt} in {delay}s: {last_err}",
                                {"url": current_url, "attempt": attempt},
                            )
                            await asyncio.sleep(delay)
                        resp = await page.goto(current_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                        if resp and resp.status == 429:
                            last_err = "HTTP 429"
                            continue
                        await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
                        ok = True
                        break
                    except (PWTimeout, PWError) as e:
                        last_err = f"{type(e).__name__}: {e}"
                        continue

                if not ok:
                    await log("ERROR", f"Navigation failed after 3 retries: {last_err}", {"url": current_url})
                    await page.close()
                    # If we've never loaded a single page, this is a hard failure.
                    if pages_scraped == 0:
                        raise RuntimeError(f"Unable to load initial page: {last_err}")
                    fail_streak += 1
                    if fail_streak >= 3:
                        raise RuntimeError(f"Aborting after 3 consecutive page failures: {last_err}")
                    continue

                fail_streak = 0
                pages_scraped += 1
                if on_page:
                    await on_page()
                await log("INFO", f"Page {pages_scraped} loaded", {"url": current_url})

                # Extract products
                products = await _extract_on_page(page, current_url)
                # Infinite-scroll fallback if the page looks scrollable and no "next" button found
                # Try infinite scroll if initial extraction is small and no static next
                next_info = await _find_next(page, current_url)
                if not products or (not next_info and len(products) < 5):
                    scrolled_new = await _try_infinite_scroll(page, current_url, log)
                    if scrolled_new:
                        products = await _extract_on_page(page, current_url)

                if products:
                    saved = await save_products(products)
                    products_count += saved
                    await log(
                        "INFO",
                        f"Saved {saved} products on page {pages_scraped} (total {products_count})",
                        {"url": current_url, "saved": saved, "source": products[0].get("_source")},
                    )
                else:
                    await log("DEBUG", "No products found on this page", {"url": current_url})

                # Find pagination
                next_info = await _find_next(page, current_url)
                await page.close()

                if not next_info:
                    await log("INFO", "No next page detected — finishing", None)
                    break

                # Jitter
                await asyncio.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))

                if next_info.get("kind") == "href":
                    current_url = next_info["url"]
                    await log("DEBUG", "Paginating via href", {"next_url": current_url})
                else:
                    # click-based load-more — reopen same URL is wrong; we'd need persistent page.
                    await log("WARN", "Click-based pagination not supported across pages; stopping", None)
                    break

        finally:
            await browser.close()

    await log("INFO", f"Scrape complete: {pages_scraped} pages, {products_count} products", None)
    return {"pages_scraped": pages_scraped, "products_count": products_count}


async def _try_infinite_scroll(page: Page, url: str, log: LogFn) -> bool:
    """Scroll until 2 consecutive scrolls yield no new product-like elements. Returns True if anything new loaded."""
    zero_streak = 0
    last_height = 0
    grew = False
    for _ in range(30):
        try:
            height = await page.evaluate("document.body.scrollHeight")
        except PWError:
            return grew
        if height == last_height:
            zero_streak += 1
        else:
            zero_streak = 0
            grew = True
        last_height = height
        if zero_streak >= 2:
            break
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except PWError:
            break
        await asyncio.sleep(1.5)
    if grew:
        await log("DEBUG", "Infinite scroll grew the page", {"url": url})
    return grew
