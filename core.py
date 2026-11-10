#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 核心引擎

检索（OpenAlex 开放学术索引，CC0）→ 五维打分 → 智能挑选 → 调研报告 → 引用导出。

本模块与本地执行端（or-paper-radar / radar_deliver.py）口径一致：
    综合分 = 相关 0.40 + 新颖 0.20 + 质量 0.15 + 方法 0.15 + 启发 0.10，推荐阈值 70。
只使用 Python 标准库，便于在任意沙箱托管。
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------
# 顶刊池（22 刊 · ISSN，与本地端 radar_profile.json 同源，经 OpenAlex issn_l 校验）
# --------------------------------------------------------------------------
TOP_JOURNALS = [
    ("EJOR", "0377-2217"),
    ("COR", "0305-0548"),
    ("Transportation Science", "0041-1655"),
    ("OMEGA", "0305-0483"),
    ("TR Part A", "0965-8564"),
    ("TR Part B", "0191-2615"),
    ("TR Part C", "0968-090X"),
    ("TR Part D", "1361-9209"),
    ("TR Part E", "1366-5545"),
    ("Networks", "0028-3045"),
    ("Mathematics of OR", "0364-765X"),
    ("Operations Research", "0030-364X"),
    ("Management Science", "0025-1909"),
    ("M&SOM", "1523-4614"),
    ("POM", "1059-1478"),
    ("IJOC", "0899-1499"),
    ("IEEE TITS", "1524-9050"),
    ("IEEE TEVC", "1089-778X"),
    ("IEEE TASE", "1545-5955"),
    ("IEEE TCYB", "2168-2267"),
    ("IEEE IoT-J", "2327-4662"),
    ("IEEE TII", "1551-3203"),
]
TOP_ISSN = [issn for _, issn in TOP_JOURNALS]
TOP_NAME = {issn: name for name, issn in TOP_JOURNALS}
TOP_NAME_BY_SET = {name.lower(): issn for name, issn in TOP_JOURNALS}

# 四层加权（排序参考，用于报告中的期刊层级说明）
TIERS = [
    ("UTD / 旗舰", ["Management Science", "Operations Research", "M&SOM", "POM", "IJOC",
                    "Mathematics of OR", "Transportation Science"], 45),
    ("TR 系列", ["TR Part A", "TR Part B", "TR Part C", "TR Part D", "TR Part E"], 25),
    ("IEEE 系列", ["IEEE TITS", "IEEE TEVC", "IEEE TASE", "IEEE TCYB", "IEEE IoT-J",
                   "IEEE TII"], 20),
    ("OR 核心", ["EJOR", "COR", "OMEGA", "Networks"], 15),
]

WEIGHTS = {"rel": 0.40, "nov": 0.20, "qual": 0.15, "method": 0.15, "insp": 0.10}
DIM_LABEL = {"rel": "相关", "nov": "新颖", "qual": "质量", "method": "方法", "insp": "启发"}
RECOMMEND_THRESHOLD = 70

EXAMPLES = [
    "城市物流无人机调度",
    "drone delivery urban logistics",
    "应急救援物资调度",
    "电动车路径规划",
    "供应链韧性",
    "港航泊位调度",
    "强化学习 组合优化",
    "digital twin manufacturing",
]

METHOD_KEYS = [
    # 英文方法词
    "optimization", "heuristic", "metaheuristic", "matheuristic", "genetic algorithm", "memetic",
    "machine learning", "deep learning", "reinforcement learning", "neural network", "transformer",
    "large language model", "graph neural network", "simulation", "agent-based", "digital twin",
    "stochastic", "robust optimization", "integer programming", "mixed-integer", "linear programming",
    "dynamic programming", "decomposition", "benders", "column generation", "branch and",
    "tabu search", "simulated annealing", "markov", "queueing", "queuing", "game theory",
    "multi-objective", "fuzzy", "network flow", "network design", "scheduling", "routing",
    "location", "inventory", "discrete choice", "causal", "econometric", "empirical",
    "case study", "survey", "literature review", "benchmark", "data-driven", "bayesian",
    "regression", "forecast", "clustering", "resilience", "uncertainty", "risk", "evacuation",
    "humanitarian", "relief",
    # 中文方法词
    "优化", "调度", "路径规划", "车辆路径", "仿真", "模拟", "强化学习", "机器学习", "深度学习",
    "神经网络", "遗传算法", "启发式", "元启发", "鲁棒", "随机", "整数规划", "动态规划", "博弈",
    "多目标", "模糊", "排队", "库存", "选址", "韧性", "不确定性", "风险", "疏散", "应急",
    "资源配置", "列生成", "分解", "分支定界", "数字孪生", "智能体", "预测", "聚类", "回归",
    "因果", "实证", "案例", "综述", "基准", "数据驱动", "贝叶斯", "图神经网络", "大模型",
]

STOP = set(
    ("the and for with from that this using based study research analysis of in on a an to by via "
     "their its our we is are be as at or not can may how what why when which into out more most than then there "
     "these those it will would could should have has had do does did but if else also such both each other some "
     "any all per non pre post new novel approach model system paper works results method methods problem problems "
     "基于 研究 分析 优化 的 与 和 在 中 下 一种 及其").split()
)

ALEX_BASE = "https://api.openalex.org/works"
ALEX_SELECT = ("id,doi,title,publication_year,cited_by_count,primary_location,"
               "authorships,open_access,abstract_inverted_index")


# --------------------------------------------------------------------------
# 文本工具
# --------------------------------------------------------------------------
def has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fa5]", s or ""))


def tokenize(text: str) -> list[str]:
    t = (text or "").lower()
    out: list[str] = []
    for m in re.findall(r"[a-z][a-z-]{2,}", t):
        if m not in STOP and len(m) >= 3:
            out.append(m)
    for run in re.findall(r"[\u4e00-\u9fa5]{2,}", t):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in STOP:
                out.append(g)
    return out


def abstract_from_inverted(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for idx in idxs or []:
            pos.append((idx, word))
    pos.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pos)


# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------
def build_filter(window_days: int, min_cite: int, top_only: bool, oa_only: bool) -> str:
    filters = ["type:article"]
    if window_days:
        from_date = (date.today() - timedelta(days=int(window_days))).isoformat()
        filters.append(f"from_publication_date:{from_date}")
    if min_cite:
        filters.append(f"cited_by_count:>{int(min_cite)}")
    if top_only:
        filters.append("primary_location.source.issn:" + "|".join(TOP_ISSN))
    if oa_only:
        filters.append("is_oa:true")
    return ",".join(filters)


def _http_json(url: str, timeout: int = 30, retries: int = 3) -> tuple[dict, int]:
    """带重试的 JSON 请求，返回 (payload, 耗时毫秒)。

    响应体较大时远端可能提前断流（IncompleteRead），故分块读取并重试。
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        started = datetime.now()
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "PaperPilot-Radar/1.0 (workbuddy campus ai agent competition)",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                buf = bytearray()
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    buf.extend(chunk)
            elapsed_ms = round((datetime.now() - started).total_seconds() * 1000)
            return json.loads(bytes(buf).decode("utf-8")), elapsed_ms
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def openalex_search(query: str, window_days: int = 1095, min_cite: int = 0,
                    size: int = 50, top_only: bool = False, oa_only: bool = False,
                    api_key: str = "", timeout: int = 30) -> dict:
    """调用 OpenAlex 检索。返回 {count, results, request_url, elapsed_ms}。"""
    params = {
        "search": query,
        "filter": build_filter(window_days, min_cite, top_only, oa_only),
        "per-page": str(int(size)),
        "select": ALEX_SELECT,
    }
    if api_key:
        params["api_key"] = api_key
    url = ALEX_BASE + "?" + urllib.parse.urlencode(params, safe=":|(),>")

    payload, elapsed_ms = _http_json(url, timeout=timeout)

    works = [w for w in (payload.get("results") or []) if w.get("title")]
    return {
        "count": (payload.get("meta") or {}).get("count", len(works)),
        "results": works,
        "request_url": url,
        "elapsed_ms": elapsed_ms,
    }


# --------------------------------------------------------------------------
# 五维打分
# --------------------------------------------------------------------------
def score_all(works: list[dict], query: str) -> list[dict]:
    n = len(works)
    cur = date.today().year
    q_tok = list(dict.fromkeys(tokenize(query)))

    items: list[dict] = []
    for i, w in enumerate(works):
        title = w.get("title") or ""
        abs_txt = abstract_from_inverted(w.get("abstract_inverted_index"))
        doc = title + " " + abs_txt
        doc_tok = set(tokenize(doc))

        cover = 0.0
        if q_tok:
            cover = sum(1 for t in q_tok if t in doc_tok) / len(q_tok)
        rank_score = max(45.0, 95.0 - (i / (n - 1)) * 50.0) if n > 1 else 90.0
        lex_score = min(100.0, 55.0 + cover * 90.0) if cover > 0 else None
        rel = round(rank_score if lex_score is None else 0.6 * rank_score + 0.4 * lex_score)

        year = w.get("publication_year") or (cur - 10)
        age = max(0, cur - year)
        nov = max(8, min(100, 100 - age * 12))

        src = ((w.get("primary_location") or {}).get("source") or {})
        issn = src.get("issn_l") or ""
        issn_list = src.get("issn") or []
        is_top = issn in TOP_NAME or any(x in TOP_NAME for x in issn_list)
        if not issn and issn_list:
            issn = issn_list[0]
        venue = src.get("display_name") or ""

        cited = w.get("cited_by_count") or 0
        base = 90 if is_top else (66 if (issn or venue) else 48)
        qual = min(100, round(base + min(15, math.log10(cited + 1) * 8)))

        low = doc.lower()
        mh = [k for k in METHOD_KEYS if k in low]
        method = 30 if not mh else min(100, 45 + len(mh) * 13)

        vel = cited / (age + 1)
        has_abs = len(abs_txt) > 60
        oa = bool((w.get("open_access") or {}).get("is_oa"))
        insp = min(100, round(
            26 + min(38, math.log10(vel * 10 + 1) * 20)
            + (12 if oa else 0)
            + (10 if is_top else 0)
            + (6 if has_abs else 0)
        ))

        dims = {"rel": rel, "nov": nov, "qual": qual, "method": method, "insp": insp}
        total = round(sum(dims[k] * WEIGHTS[k] for k in WEIGHTS))

        items.append({
            "i": i,
            "title": title,
            "abstract": abs_txt,
            "venue": venue,
            "issn": issn,
            "top_name": TOP_NAME.get(issn) or ("" if not is_top else venue),
            "is_top": is_top,
            "year": year,
            "cited": cited,
            "is_oa": oa,
            "authors": [((a.get("author") or {}).get("display_name") or "")
                        for a in (w.get("authorships") or [])][:12],
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "url": ((w.get("primary_location") or {}).get("landing_page_url")
                    or w.get("doi") or ""),
            "dims": dims,
            "total": total,
            "rec": total >= RECOMMEND_THRESHOLD,
            "src": "heuristic",
            "why": "",
            "sel": False,
        })
    return items


def reason(item: dict) -> str:
    d = item["dims"]
    p: list[str] = []
    if d["rel"] >= 80:
        p.append("与检索意图高度契合")
    elif d["rel"] >= 60:
        p.append("主题相关性较好")
    if item["is_top"]:
        p.append(f"发表于顶刊 {item['top_name'] or item['venue']}")
    if d["nov"] >= 85:
        p.append("发表时间新，处于前沿")
    if item["cited"] >= 100:
        p.append(f"被引 {item['cited']} 次，影响力高")
    if d["qual"] >= 85:
        p.append("载体质量与引用表现俱佳")
    if d["method"] >= 70:
        p.append("方法链条清晰、可复用")
    if not p:
        p.append("综合表现均衡，可作为背景阅读")
    return "；".join(p[:3]) + "。"


def summarize(items: list[dict], total_count: int) -> dict:
    if not items:
        return {"hit": total_count, "page": 0, "top": 0, "oa": 0, "avg_cited": 0,
                "years": "", "rec": 0}
    years = [x["year"] for x in items if x["year"]]
    return {
        "hit": total_count,
        "page": len(items),
        "top": sum(1 for x in items if x["is_top"]),
        "oa": sum(1 for x in items if x["is_oa"]),
        "avg_cited": round(sum(x["cited"] for x in items) / len(items)),
        "years": f"{min(years)}–{max(years)}" if years else "—",
        "rec": sum(1 for x in items if x["rec"]),
    }


def pick(items: list[dict]) -> list[dict]:
    """智能挑选：优先推荐精读（综合分 ≥ 70）；不足则退回首序前 5 篇。"""
    rec = [x for x in items if x["rec"]]
    target = rec if rec else sorted(items, key=lambda x: -x["total"])[:5]
    for x in items:
        x["sel"] = False
    for x in target:
        x["sel"] = True
    return target


# --------------------------------------------------------------------------
# 报告与导出
# --------------------------------------------------------------------------
def build_report(items: list[dict], query: str, stats: dict) -> str:
    sel = [x for x in items if x.get("sel")]
    ranked = sorted(items, key=lambda x: -x["total"])
    rec = [x for x in ranked if x["total"] >= RECOMMEND_THRESHOLD][:5]

    venue: dict[str, int] = {}
    term: dict[str, int] = {}
    year: dict[int, int] = {}
    meth: dict[str, int] = {}
    for x in items:
        if x["venue"]:
            venue[x["venue"]] = venue.get(x["venue"], 0) + 1
        year[x["year"]] = year.get(x["year"], 0) + 1
        for t in set(tokenize(x["title"])):
            term[t] = term.get(t, 0) + 1
        low = (x["title"] + " " + x["abstract"]).lower()
        for k in METHOD_KEYS:
            if k in low:
                meth[k] = meth.get(k, 0) + 1

    def top_of(d: dict, k: int) -> list[tuple]:
        return sorted(d.items(), key=lambda kv: -kv[1])[:k]

    L: list[str] = []
    L.append("# PaperPilot 调研报告")
    L.append("")
    L.append(f"- 检索意图：**{query}**")
    L.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- 数据来源：OpenAlex 开放学术索引（CC0）· 打分权重 相关 0.40 / 新颖 0.20 / "
             f"质量 0.15 / 方法 0.15 / 启发 0.10 · 推荐阈值 {RECOMMEND_THRESHOLD}")
    L.append("")
    L.append("## 一、概览")
    L.append("")
    L.append(f"| 指标 | 数值 |")
    L.append("| --- | --- |")
    L.append(f"| 检索命中 | {stats.get('hit', 0)} |")
    L.append(f"| 本页文献 | {stats.get('page', 0)} |")
    L.append(f"| 顶刊篇数 | {stats.get('top', 0)} |")
    L.append(f"| 开放获取 | {stats.get('oa', 0)} |")
    L.append(f"| 平均被引 | {stats.get('avg_cited', 0)} |")
    L.append(f"| 年份区间 | {stats.get('years', '—')} |")
    L.append(f"| 达到推荐阈值 | {stats.get('rec', 0)} |")
    L.append(f"| 已选入本报告 | {len(sel) if sel else min(len(ranked), 10)} |")
    L.append("")

    L.append("## 二、研究方向画像")
    L.append("")
    L.append("**高频载体**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(venue, 6)) or "—"))
    L.append("")
    L.append("**高频术语**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(term, 12)) or "—"))
    L.append("")
    L.append("**方法取向**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(meth, 8)) or "—"))
    L.append("")

    L.append("## 三、推荐精读")
    L.append("")
    if rec:
        L.append("| # | 标题 | 载体 | 年份 | 综合分 | 推荐理由 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for i, x in enumerate(rec, 1):
            title = x["title"].replace("|", "/")
            L.append(f"| {i} | {title} | {x['venue'] or '—'} | {x['year']} | **{x['total']}** | "
                     f"{reason(x)} |")
    else:
        L.append(f"本轮没有达到推荐阈值（综合分 ≥ {RECOMMEND_THRESHOLD}）的文献，"
                 "建议放宽时间窗或换更具体的关键词重试。")
    L.append("")

    L.append("## 四、年份分布")
    L.append("")
    L.append("| 年份 | 篇数 |")
    L.append("| --- | --- |")
    for y, c in sorted(year.items(), key=lambda kv: -kv[0])[:8]:
        L.append(f"| {y} | {c} |")
    L.append("")

    L.append("## 五、逐篇评分明细")
    L.append("")
    for x in ranked[:10]:
        d = x["dims"]
        L.append(f"### {x['title']}")
        L.append("")
        L.append(f"- **载体**：{x['venue'] or '未标注'} · {x['year']} · "
                 f"被引 {x['cited']}" + ("　· 开放获取" if x["is_oa"] else ""))
        if x["doi"]:
            L.append(f"- **DOI**：https://doi.org/{x['doi']}")
        L.append(f"- **综合分**：{x['total']} = 相关 {d['rel']}×0.40 + 新颖 {d['nov']}×0.20 + "
                 f"质量 {d['qual']}×0.15 + 方法 {d['method']}×0.15 + 启发 {d['insp']}×0.10")
        L.append(f"- **推荐理由**：{reason(x)}")
        if x["abstract"]:
            L.append(f"- **摘要要点**：{x['abstract'][:220]}…")
        L.append("")

    L.append("## 六、结论与建议")
    L.append("")
    if rec:
        L.append(f"本轮最值得优先精读的是《{rec[0]['title'][:60]}》（综合分 {rec[0]['total']}），"
                 f"{reason(rec[0])}建议按上表顺序推进精读，并优先获取开放获取版本。")
    else:
        L.append("本轮无达标文献，建议调整检索式（补充同义词 / 放宽时间窗 / 去掉限定条件）后重试。")
    L.append("")
    L.append("> 说明：本报告由 PaperPilot 文献雷达在线工作台生成，全部指标来自 OpenAlex 公开元数据，"
             "可现场复现。文献全文请通过所在机构的合法订阅或出版商开放获取渠道获取，"
             "本工具不做任何绕过付费墙的下载。")
    L.append("")
    return "\n".join(L)


def _bib_key(item: dict, i: int) -> str:
    last = (item["authors"][0] if item["authors"] else "anon").split()[-1].lower()
    last = re.sub(r"[^a-z0-9]", "", last) or "anon"
    m = re.search(r"[A-Za-z]{3,}", item["title"])
    word = m.group(0).lower() if m else "paper"
    return f"{last}{item['year']}{word}{i}"


def to_bibtex(items: list[dict]) -> str:
    out: list[str] = []
    for i, it in enumerate(items, 1):
        L = [f"@article{{{_bib_key(it, i)},",
             f"  title   = {{{it['title']}}},"]
        if it["authors"]:
            L.append(f"  author  = {{{' and '.join(it['authors'])}}},")
        if it["venue"]:
            L.append(f"  journal = {{{it['venue']}}},")
        L.append(f"  year    = {{{it['year']}}},")
        if it["doi"]:
            L.append(f"  doi     = {{{it['doi']}}},")
        if it["url"]:
            L.append(f"  url     = {{{it['url']}}},")
        L.append("}")
        out.append("\n".join(L))
    return "\n\n".join(out) + "\n"


def to_ris(items: list[dict]) -> str:
    chunks: list[str] = []
    for it in items:
        L = ["TY  - JOUR"]
        L += [f"AU  - {a}" for a in it["authors"]]
        L.append(f"TI  - {it['title']}")
        if it["venue"]:
            L.append(f"JO  - {it['venue']}")
        L.append(f"PY  - {it['year']}")
        if it["doi"]:
            L.append(f"DO  - {it['doi']}")
        if it["url"]:
            L.append(f"UR  - {it['url']}")
        L.append("ER  - ")
        chunks.append("\n".join(L))
    return "\n\n".join(chunks) + "\n"


def to_markdown_table(items: list[dict]) -> str:
    L = ["| # | 标题 | 载体 | 年份 | 被引 | 综合分 | 相关 | 新颖 | 质量 | 方法 | 启发 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, x in enumerate(items, 1):
        d = x["dims"]
        L.append(f"| {i} | {x['title'].replace('|', '/')} | {x['venue'] or '—'} | {x['year']} | "
                 f"{x['cited']} | **{x['total']}** | {d['rel']} | {d['nov']} | {d['qual']} | "
                 f"{d['method']} | {d['insp']} |")
    return "\n".join(L)


def top_journal_table() -> list[dict]:
    order: dict[str, tuple[str, int]] = {}
    for tier, names, weight in TIERS:
        for nm in names:
            order[nm] = (tier, weight)
    rows = []
    for name, issn in TOP_JOURNALS:
        tier, weight = order.get(name, ("其他", 0))
        rows.append({"name": name, "issn": issn, "tier": tier, "weight": weight})
    rows.sort(key=lambda r: (-r["weight"], r["name"]))
    return rows
