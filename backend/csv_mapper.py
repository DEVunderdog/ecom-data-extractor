"""Maps a scraped product dict onto the Swagify CSV schema."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data" / "swagify_headers.json"
SWAGIFY_HEADERS: list[str] = json.loads(DATA.read_text(encoding="utf-8"))
SWAGIFY_HEADERS_SET = set(SWAGIFY_HEADERS)


_IN_STOCK_HINTS = ("in stock", "instock", "available", "in_stock")
_OUT_STOCK_HINTS = ("out of stock", "outofstock", "unavailable", "sold out")


def _availability_qty(av: str) -> str:
    if not av:
        return ""
    s = str(av).lower()
    if any(h in s for h in _IN_STOCK_HINTS):
        return "1"
    if any(h in s for h in _OUT_STOCK_HINTS):
        return "0"
    return ""


def _split_category(cat: str) -> list[str]:
    if not cat:
        return []
    return [p.strip() for p in str(cat).split(" > ") if p and p.strip()]


_COVERED_LEFTOVER_KEYS = {
    "name", "description", "brand", "category", "material", "size",
    "country_of_origin", "sku", "product_id", "price", "image_url",
    "availability", "_source",
}


def to_swagify_row(p: dict[str, Any]) -> dict[str, str]:
    """Translate a scraped product dict to a subset of Swagify columns.

    Any Swagify header not returned here is emitted as "" by the writer.
    """
    name = (p.get("name") or "").strip()
    sku = (p.get("sku") or p.get("product_id") or "").strip()
    cats = _split_category(p.get("category") or "")
    price = p.get("price")
    price_str = "" if price in (None, "") else f"{price}"
    image = (p.get("image_url") or "").strip()

    # anything not mapped goes into Additional Infos JSON (lossless-ish)
    leftover = {k: v for k, v in (p or {}).items() if k not in _COVERED_LEFTOVER_KEYS and v not in (None, "", [])}
    additional = json.dumps(leftover, ensure_ascii=False) if leftover else ""

    row: dict[str, str] = {
        "Product Name": name,
        "Long Description": (p.get("description") or "").strip(),
        "Brand": (p.get("brand") or "").strip(),
        "Primary Supplier": (p.get("brand") or "").strip(),
        "Category-1": cats[0] if len(cats) >= 1 else "",
        "Sub-Category-1-1": cats[1] if len(cats) >= 2 else "",
        "Sub-Category-1-1-1": cats[2] if len(cats) >= 3 else "",
        "Material": (p.get("material") or "").strip(),
        "Size": (p.get("size") or "").strip(),
        "Country of Origin": (p.get("country_of_origin") or "").strip(),
        "Product Type": "Product" if name else "",
        "Active": "1" if name else "",
        "Variant Type": "Product",
        "Swagify SKU": sku,
        "Supplier SKU": sku,
        "Variant SKU": sku,
        "Parent SKU": sku,
        "Minimum Order Qty": "1",
        "QtyBreak1": "1",
        "Price1": price_str,
        "Main Image": image,
        "Gallery Images": image,
        "Lifestyle Image": image,
        "Inventory Quantity": _availability_qty(p.get("availability") or ""),
        "Additional Infos": additional,
    }
    # Drop keys the schema doesn't know about (defensive).
    return {k: v for k, v in row.items() if k in SWAGIFY_HEADERS_SET}
