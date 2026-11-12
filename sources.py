#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 多源检索

OpenAlex（开放学术索引，CC0）+ Crossref（出版商元数据）并行检索，
统一归一化后按 DOI / 标题去重，保留「双源命中」这一证据。

合规边界：只读取公开元数据并标注开放获取状态，不下载全文、不绕过付费墙。
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import core

CROSSREF_BASE = "https://api.crossref.org/works"
CROSSREF_UA = "PaperPilot-Radar/2.0 (literature radar; public metadata only)"
CROSSREF_SELECT = ("DOI,title,container-title,issued,is-referenced-by-count,author,"
                   "abstract,URL,ISSN,license,type")

SOURCE_LABEL = {"openalex": "OpenAlex", "crossref": "Crossref"}


# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------
def _clean_jats(text: str) -> str:
    """去掉 Crossref 摘要里的 JATS/HTML 标签。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _crossref_year(it: dict) -> int:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (it.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return 0


def normalize_crossref(it: dict) -> dict:
    titles = [t for t in (it.get("title") or []) if t]
    title = html.unescape(titles[0]).strip() if titles else ""
    venues = [v for v in (it.get("container-title") or []) if v]
    venue = html.unescape(venues[0]).strip() if venues else ""
    issn_list = [str(x).upper() for x in (it.get("ISSN") or []) if x]
    issn = issn_list[0] if issn_list else ""
    is_top = any(x in core.TOP_NAME for x in issn_list) or issn in core.TOP_NAME

    authors: list[str] = []
    for a in it.get("author") or []:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        name = (given + " " + family).strip() or (a.get("name") or "").strip()
        if name:
            authors.append(html.unescape(name))

    doi = (it.get("DOI") or "").strip().lower()
    url = (it.get("URL") or "").strip() or (f"https://doi.org/{doi}" if doi else "")
    licenses = [str((lic or {}).get("URL") or "") for lic in (it.get("license") or [])]
    is_oa = any("creativecommons.org" in u.lower() for u in licenses)

    return {
        "title": title,
        "abstract": _clean_jats(it.get("abstract") or ""),
        "year": _crossref_year(it),
        "cited": int(it.get("is-referenced-by-count") or 0),
        "venue": venue,
        "issn": issn,
        "is_top": bool(is_top),
        "is_oa": is_oa,
        "authors": authors[:12],
        "doi": doi,
        "url": url,
        "source_tags": ["crossref"],
    }


# --------------------------------------------------------------------------
# 单源检索
# --------------------------------------------------------------------------
def search_openalex(query: str, window_days: int = 1095, min_cite: int = 0,
                    size: int = 50, top_only: bool = False, oa_only: bool = False,
                    api_key: str = "", timeout: int = 30) -> dict:
    started = time.time()
    res = core.openalex_search(
        query, window_days=window_days, min_cite=min_cite, size=size,
        top_only=top_only, oa_only=oa_only, api_key=api_key, timeout=timeout,
    )
    items = [core.normalize_openalex_work(w) for w in res["results"]]
    return {
        "items": items,
        "total": int(res.get("count") or len(items)),
        "raw_total": int(res.get("count") or len(items)),
        "elapsed_ms": res.get("elapsed_ms") or round((time.time() - started) * 1000),
        "url": res.get("request_url") or "",
        "error": "",
    }


def search_crossref(query: str, window_days: int = 1095, min_cite: int = 0,
                    size: int = 50, top_only: bool = False, oa_only: bool = False,
                    timeout: int = 30) -> dict:
    started = time.time()
    params = {
        "query": query,
        "rows": str(max(1, min(200, int(size)))),
        "select": CROSSREF_SELECT,
        "filter": "type:journal-article",
    }
    if window_days:
        from_date = date.today() - timedelta(days=int(window_days))
        params["filter"] += f",from-pub-date:{from_date.isoformat()}"
    url = CROSSREF_BASE + "?" + urllib.parse.urlencode(params)

    payload, elapsed_ms = core._http_json(url, timeout=timeout, headers={"User-Agent": CROSSREF_UA})
    msg = payload.get("message") or {}
    raw_items = msg.get("items") or []
    raw_total = int(msg.get("total-results") or len(raw_items))

    items: list[dict] = []
    for it in raw_items:
        row = normalize_crossref(it)
        if not row["title"]:
            continue
        if top_only and not row["is_top"]:
            continue
        if oa_only and not row["is_oa"]:
            continue
        if min_cite and row["cited"] <= int(min_cite):
            continue
        items.append(row)

    filtered = bool(top_only or oa_only or min_cite)
    return {
        "items": items,
        "total": len(items) if filtered else raw_total,
        "raw_total": raw_total,
        "elapsed_ms": elapsed_ms or round((time.time() - started) * 1000),
        "url": url,
        "error": "",
    }


# --------------------------------------------------------------------------
# 合并与去重
# --------------------------------------------------------------------------
def _key(item: dict) -> str:
    doi = (item.get("doi") or "").strip().lower()
    if doi:
        return "doi:" + doi
    norm = re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", "", (item.get("title") or "").lower())
    return "title:" + norm[:90]


def merge_items(groups: list[list[dict]], size: int = 50) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []

    for items in groups:
        for it in items:
            k = _key(it)
            if k in merged:
                base = merged[k]
                tags = set(base.get("source_tags") or []) | set(it.get("source_tags") or [])
                base["source_tags"] = sorted(tags)
                base["cited"] = max(int(base.get("cited") or 0), int(it.get("cited") or 0))
                base["is_oa"] = bool(base.get("is_oa")) or bool(it.get("is_oa"))
                base["is_top"] = bool(base.get("is_top")) or bool(it.get("is_top"))
                if len(it.get("abstract") or "") > len(base.get("abstract") or ""):
                    base["abstract"] = it["abstract"]
                for f in ("doi", "url", "year", "venue", "issn"):
                    if not base.get(f) and it.get(f):
                        base[f] = it[f]
            else:
                row = dict(it)
                row["source_tags"] = list(it.get("source_tags") or [])
                merged[k] = row
                order.append(k)

    # 双源命中的条目优先，其余保持原有召回顺序
    order.sort(key=lambda k: -len(merged[k].get("source_tags") or []))
    return [merged[k] for k in order[:max(1, int(size))]]


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
def search_all(query: str, window_days: int = 1095, min_cite: int = 0, size: int = 50,
               top_only: bool = False, oa_only: bool = False,
               sources: tuple[str, ...] = ("openalex", "crossref"),
               openalex_key: str = "", timeout: int = 30) -> dict:
    """并行检索多个来源，返回合并去重后的结果与每个来源的状态。"""
    picked = tuple(s for s in sources if s in SOURCE_LABEL) or ("openalex",)
    started = time.time()
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=len(picked)) as pool:
        futures: dict[str, object] = {}
        if "openalex" in picked:
            futures["openalex"] = pool.submit(
                search_openalex, query, window_days, min_cite, size,
                top_only, oa_only, openalex_key, timeout,
            )
        if "crossref" in picked:
            futures["crossref"] = pool.submit(
                search_crossref, query, window_days, min_cite, size,
                top_only, oa_only, timeout,
            )
        for name, fut in futures.items():
            try:
                results[name] = fut.result()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                results[name] = {
                    "items": [], "total": 0, "raw_total": 0, "elapsed_ms": 0,
                    "url": "", "error": f"{type(exc).__name__}: {exc}",
                }

    items = merge_items([results[s]["items"] for s in picked if s in results], size=size)
    counts = {s: int(results[s].get("total") or 0) for s in picked if s in results}
    raw_counts = {s: int(results[s].get("raw_total") or 0) for s in picked if s in results}
    errors = {s: results[s]["error"] for s in picked if results.get(s, {}).get("error")}
    urls = {s: results[s].get("url") or "" for s in picked if s in results}

    return {
        "items": items,
        "counts": counts,
        "raw_counts": raw_counts,
        "hit": counts.get("openalex") or counts.get("crossref") or len(items),
        "errors": errors,
        "request_urls": urls,
        "sources_used": [s for s in picked if s in results],
        "elapsed_ms": round((time.time() - started) * 1000),
    }
