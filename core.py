#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 核心引擎

多源文献（OpenAlex / Crossref）→ 可解释五维评分 → 选题洞察 → 调研简报 → 引用导出。

评分口径（v2）：
    综合分 = 相关 0.40 + 新颖 0.20 + 质量 0.15 + 方法 0.15 + 启发 0.10，推荐阈值 70。
    - 相关性：TF-IDF 余弦相似度 + 检索词覆盖率 + 召回位次
    - 新颖性：发表年份
    - 质量：期刊层级 + 本批被引分位
    - 方法：方法关键词分组覆盖 + 摘要完整度
    - 启发：引用速度分位 + 开放获取 + 双源命中 + 摘要可得性
    另有「证据完整性校验」：标题、年份、载体/DOI、摘要四项，缺关键项不进入推荐。

只使用 Python 标准库，便于在任意沙箱托管。
"""

from __future__ import annotations

import bisect
import hashlib
import html
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
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

TIERS = [
    ("UTD / 旗舰", ["Management Science", "Operations Research", "M&SOM", "POM", "IJOC",
                    "Mathematics of OR", "Transportation Science"], 45),
    ("TR 系列", ["TR Part A", "TR Part B", "TR Part C", "TR Part D", "TR Part E"], 25),
    ("IEEE 系列", ["IEEE TITS", "IEEE TEVC", "IEEE TASE", "IEEE TCYB", "IEEE IoT-J",
                   "IEEE TII"], 20),
    ("OR 核心", ["EJOR", "COR", "OMEGA", "Networks"], 15),
]

TOP_TIER: dict[str, tuple[str, int]] = {}
for _tier, _names, _weight in TIERS:
    for _nm in _names:
        _issn = TOP_NAME_BY_SET.get(_nm.lower())
        if _issn:
            TOP_TIER[_issn] = (_tier, _weight)
TIER_BASE = {"UTD / 旗舰": 96, "TR 系列": 93, "IEEE 系列": 91, "OR 核心": 89}

WEIGHTS = {"rel": 0.40, "nov": 0.20, "qual": 0.15, "method": 0.15, "insp": 0.10}
DIM_LABEL = {"rel": "相关", "nov": "新颖", "qual": "质量", "method": "方法", "insp": "启发"}
RECOMMEND_THRESHOLD = 70

EXAMPLES = [
    "城市物流无人机调度",
    "卡车无人机协同配送路径规划",
    "供应链韧性",
    "应急救援物资调度",
    "强化学习 组合优化",
    "港航泊位调度",
    "电动车路径规划",
    "digital twin manufacturing",
]

# 方法关键词分组：同一组只计一次，避免堆词刷分
METHOD_GROUPS: dict[str, list[str]] = {
    "优化建模": [
        "optimization", "integer programming", "mixed-integer", "linear programming",
        "dynamic programming", "robust optimization", "stochastic programming",
        "multi-objective", "benders", "column generation", "decomposition",
        "mathematical model", "formulation", "优化", "整数规划", "混合整数", "动态规划",
        "鲁棒优化", "随机规划", "多目标", "列生成", "分解", "建模",
    ],
    "启发式算法": [
        "heuristic", "metaheuristic", "genetic algorithm", "tabu search",
        "simulated annealing", "particle swarm", "ant colony",
        "large neighborhood search", "local search", "memetic",
        "启发式", "元启发", "遗传算法", "禁忌搜索", "模拟退火", "粒子群", "蚁群",
        "大邻域搜索", "局部搜索",
    ],
    "机器学习": [
        "machine learning", "deep learning", "reinforcement learning",
        "neural network", "transformer", "graph neural network",
        "large language model", "xgboost", "random forest", "clustering",
        "classification", "prediction", "机器学习", "深度学习", "强化学习",
        "神经网络", "图神经网络", "大语言模型", "大模型", "预测", "分类", "聚类",
    ],
    "仿真与系统": [
        "simulation", "agent-based", "digital twin", "discrete event",
        "system dynamics", "monte carlo", "仿真", "模拟", "数字孪生",
        "离散事件", "系统动力学", "蒙特卡洛",
    ],
    "实证与统计": [
        "empirical", "econometric", "regression", "causal", "difference-in-differences",
        "instrumental variable", "panel data", "experiment", "econometric model",
        "实证", "计量", "回归", "因果", "双重差分", "工具变量", "面板数据",
        "问卷", "实验",
    ],
    "案例与综述": [
        "case study", "literature review", "meta-analysis", "systematic review",
        "survey paper", "案例", "综述", "元分析", "系统综述",
    ],
    "博弈与决策": [
        "game theory", "mechanism design", "auction", "pricing",
        "markov decision process", "decision-making", "博弈", "机制设计",
        "拍卖", "定价", "马尔可夫决策", "决策",
    ],
}
METHOD_KEYS = [k for keys in METHOD_GROUPS.values() for k in keys]

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
UA = "PaperPilot-Radar/2.0 (public metadata only)"


# --------------------------------------------------------------------------
# 文本工具
# --------------------------------------------------------------------------
def has_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fa5]", s or ""))


def tokenize(text: str) -> list[str]:
    t = (text or "").lower()
    out: list[str] = []
    for m in re.findall(r"[a-z][a-z-]{2,}", t):
        # 连字符词拆开，保证 truck-drone 能同时命中 truck / drone
        for part in m.split("-"):
            if len(part) >= 3 and part not in STOP:
                out.append(part)
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
# 归一化
# --------------------------------------------------------------------------
def normalize_openalex_work(w: dict) -> dict:
    src = ((w.get("primary_location") or {}).get("source") or {})
    issn = (src.get("issn_l") or "").upper()
    issn_list = [str(x).upper() for x in (src.get("issn") or [])]
    is_top = issn in TOP_NAME or any(x in TOP_NAME for x in issn_list)
    if not issn and issn_list:
        issn = issn_list[0]
    venue = src.get("display_name") or ""
    authors = [((a.get("author") or {}).get("display_name") or "")
               for a in (w.get("authorships") or [])][:12]
    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
    url = ((w.get("primary_location") or {}).get("landing_page_url") or w.get("doi") or "")
    return {
        "title": html.unescape(w.get("title") or "").strip(),
        "abstract": abstract_from_inverted(w.get("abstract_inverted_index")),
        "year": int(w.get("publication_year") or 0),
        "cited": int(w.get("cited_by_count") or 0),
        "venue": html.unescape(venue).strip(),
        "issn": issn,
        "is_top": bool(is_top),
        "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
        "authors": [html.unescape(a) for a in authors if a],
        "doi": doi,
        "url": url,
        "source_tags": ["openalex"],
    }


def normalize_work(w: dict) -> dict:
    if "source_tags" in w and "abstract" in w:
        row = dict(w)
        row.setdefault("year", 0)
        row.setdefault("cited", 0)
        row.setdefault("venue", "")
        row.setdefault("issn", "")
        row.setdefault("is_top", False)
        row.setdefault("is_oa", False)
        row.setdefault("authors", [])
        row.setdefault("doi", "")
        row.setdefault("url", "")
        return row
    return normalize_openalex_work(w)


# --------------------------------------------------------------------------
# 检索（OpenAlex 单源，保留供旧入口调用）
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


def _http_json(url: str, timeout: int = 30, retries: int = 3,
               headers: dict | None = None) -> tuple[dict, int]:
    """带重试的 JSON 请求，返回 (payload, 耗时毫秒)。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        started = datetime.now()
        try:
            hdrs = {"Accept": "application/json", "User-Agent": UA}
            if headers:
                hdrs.update(headers)
            req = urllib.request.Request(url, headers=hdrs)
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
# 五维评分 v2
# --------------------------------------------------------------------------
def _pct(sorted_vals: list[float], v: float) -> float:
    if not sorted_vals:
        return 0.5
    return bisect.bisect_right(sorted_vals, v) / len(sorted_vals)


def _venue_base(item: dict) -> int:
    issn = item.get("issn") or ""
    if issn in TOP_TIER:
        return TIER_BASE.get(TOP_TIER[issn][0], 89)
    venue = (item.get("venue") or "").lower()
    for name, issn2 in TOP_NAME_BY_SET.items():
        if name == venue and issn2 in TOP_TIER:
            return TIER_BASE.get(TOP_TIER[issn2][0], 89)
    if issn or item.get("venue"):
        return 68
    return 48


def _method_groups(text: str) -> list[str]:
    low = (text or "").lower()
    return [g for g, keys in METHOD_GROUPS.items() if any(k in low for k in keys)]


def _item_key(item: dict) -> str:
    doi = (item.get("doi") or "").lower().strip()
    if doi:
        return "doi:" + re.sub(r"[^a-z0-9./_-]", "", doi)[:80]
    title = (item.get("title") or "").lower()
    return "t:" + hashlib.md5(title.encode("utf-8")).hexdigest()[:10]


def score_all(works: list[dict], query: str, extra_terms: list[str] | None = None,
              threshold: int = RECOMMEND_THRESHOLD) -> list[dict]:
    """对归一化或 OpenAlex 原始记录打分，返回带五维明细的条目。"""
    items = [normalize_work(w) for w in (works or [])]
    n = len(items)
    if n == 0:
        return []

    cur = date.today().year
    q_text = " ".join([query or ""] + list(extra_terms or []))
    q_tokens = list(dict.fromkeys(tokenize(q_text)))
    if not q_tokens:
        q_tokens = list(dict.fromkeys(tokenize(query or "")))
    q_set = set(q_tokens)

    doc_tokens: list[list[str]] = []
    for x in items:
        text = ((x.get("title") or "") + " ") * 2 + (x.get("abstract") or "")
        doc_tokens.append(tokenize(text))

    df = Counter()
    for toks in doc_tokens:
        df.update(set(toks))
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    default_idf = math.log(n + 1) + 1.0
    q_tf = Counter(q_tokens)
    q_vec = {t: (1 + math.log(c)) * idf.get(t, default_idf) for t, c in q_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0

    cited_sorted = sorted(int(x.get("cited") or 0) for x in items)

    def _age(x: dict) -> int:
        y = int(x.get("year") or 0) or (cur - 10)
        return max(0, cur - y)

    vel_sorted = sorted((int(x.get("cited") or 0) / (_age(x) + 1)) for x in items)

    rows: list[dict] = []
    for i, x in enumerate(items):
        title = (x.get("title") or "").strip()
        abstract = x.get("abstract") or ""
        year = int(x.get("year") or 0) or (cur - 10)
        cited = int(x.get("cited") or 0)
        tags = list(x.get("source_tags") or [])
        is_top = bool(x.get("is_top"))
        issn = x.get("issn") or ""
        venue = x.get("venue") or ""
        age = _age(x)

        toks = doc_tokens[i]
        d_tf = Counter(toks)
        d_vec = {t: (1 + math.log(c)) * idf.get(t, default_idf) for t, c in d_tf.items()}
        d_norm = math.sqrt(sum(v * v for v in d_vec.values())) or 1.0
        cos = sum(q_vec.get(t, 0.0) * v for t, v in d_vec.items()) / (q_norm * d_norm)
        coverage = (len(q_set & set(toks)) / len(q_set)) if q_set else 0.0
        rank_prior = 1.0 if n == 1 else 1.0 - i / (n - 1)
        if "openalex" not in tags:
            rank_prior = 0.55
        if q_set:
            rel_raw = 0.50 * min(1.0, cos / 0.35) + 0.30 * coverage + 0.20 * rank_prior
            rel = max(5, min(100, round(100 * rel_raw)))
        else:
            rel = 50

        nov = max(25, min(100, 100 - age * 12))
        qual = min(100, round(_venue_base(x) + 12 * _pct(cited_sorted, cited)))

        text = title + " " + abstract
        groups = _method_groups(text)
        method = 32 + 9 * len(groups)
        if len(abstract) > 300:
            method += 6
        if re.search(r"\bwe (propose|develop|formulate|design|present|introduce)\b|"
                     r"this (paper|study) (proposes|develops|formulates)", text.lower()):
            method += 6
        method = max(25, min(100, method))

        vel = cited / (age + 1)
        insp = 15 + 40 * _pct(vel_sorted, vel)
        if x.get("is_oa"):
            insp += 10
        if len(tags) > 1:
            insp += 8
        if len(abstract) >= 120:
            insp += 5
        if is_top:
            insp += 10
        if age <= 1:
            insp += 5
        insp = max(10, min(100, round(insp)))

        dims = {"rel": rel, "nov": nov, "qual": qual, "method": method, "insp": insp}
        total = round(sum(dims[k] * WEIGHTS[k] for k in WEIGHTS))

        missing: list[str] = []
        if not title:
            missing.append("标题")
        if not (1900 <= year <= cur + 1):
            missing.append("年份异常")
        if not (venue or issn):
            missing.append("缺少期刊/会议")
        if not (x.get("doi") or x.get("url")):
            missing.append("缺少 DOI/链接")
        if len(abstract) < 120:
            missing.append("摘要缺失")
        evid_ok = bool(title) and (1900 <= year <= cur + 1) and bool(venue or issn or x.get("doi") or x.get("url"))

        rows.append({
            "i": i,
            "key": _item_key(x),
            "title": title,
            "abstract": abstract,
            "venue": venue,
            "issn": issn,
            "top_name": TOP_NAME.get(issn) or ("" if not is_top else venue),
            "is_top": is_top,
            "year": year,
            "cited": cited,
            "is_oa": bool(x.get("is_oa")),
            "authors": list(x.get("authors") or [])[:12],
            "doi": x.get("doi") or "",
            "url": x.get("url") or "",
            "dims": dims,
            "total": total,
            "rec": total >= int(threshold) and evid_ok,
            "evid_ok": evid_ok,
            "evid_missing": missing,
            "method_groups": groups,
            "source_tags": tags,
            "src": "tfidf+meta",
            "why": "",
            "sel": False,
            "star": False,
        })

    # 为叙述补上「本批分位」信息
    rel_sorted = sorted(r["dims"]["rel"] for r in rows)
    for r in rows:
        r["rel_pct"] = round(100 * _pct(rel_sorted, r["dims"]["rel"]))
        r["cited_pct"] = round(100 * _pct(cited_sorted, r["cited"]))
        r["why"] = reason(r)
    return rows


def reason(item: dict) -> str:
    d = item["dims"]
    p: list[str] = []
    if d["rel"] >= 80:
        p.append(f"与检索式匹配度高（本批相关度前 {max(1, 100 - int(item.get('rel_pct', 100)))}%）")
    elif d["rel"] >= 60:
        p.append("主题相关性较好")
    if item.get("is_top"):
        p.append(f"发表于顶刊 {item.get('top_name') or item.get('venue')}")
    if d["nov"] >= 88:
        p.append("近两年发表，时效性强")
    if item.get("cited", 0) >= 50:
        p.append(f"被引 {item['cited']} 次，影响力较高")
    elif d["qual"] >= 85:
        p.append("载体层级高")
    if d["method"] >= 70 and item.get("method_groups"):
        p.append("方法覆盖 " + "、".join(item["method_groups"][:2]))
    if len(item.get("source_tags") or []) > 1:
        p.append("OpenAlex 与 Crossref 双源命中")
    if item.get("is_oa"):
        p.append("开放获取可直接阅读")
    if not p:
        p.append("综合表现均衡，可作为背景阅读")
    return "；".join(p[:3]) + "。"


def summarize(items: list[dict], total_count: int) -> dict:
    if not items:
        return {"hit": total_count, "page": 0, "top": 0, "oa": 0, "avg_cited": 0,
                "median_cited": 0, "years": "", "rec": 0, "doi": 0, "abstract": 0}
    years = [x["year"] for x in items if x.get("year")]
    cited = sorted(x["cited"] for x in items)
    mid = cited[len(cited) // 2]
    return {
        "hit": total_count,
        "page": len(items),
        "top": sum(1 for x in items if x["is_top"]),
        "oa": sum(1 for x in items if x["is_oa"]),
        "avg_cited": round(sum(cited) / len(cited)),
        "median_cited": mid,
        "years": f"{min(years)}–{max(years)}" if years else "—",
        "rec": sum(1 for x in items if x["rec"]),
        "doi": sum(1 for x in items if x.get("doi")),
        "abstract": sum(1 for x in items if len(x.get("abstract") or "") >= 120),
    }


def pick(items: list[dict]) -> list[dict]:
    """智能挑选：优先推荐精读（综合分 ≥ 阈值且证据完整）；不足则退回首序前 5 篇。"""
    rec = [x for x in items if x["rec"]]
    target = rec if rec else sorted(items, key=lambda x: -x["total"])[:5]
    for x in items:
        x["sel"] = False
    for x in target:
        x["sel"] = True
    return target


# --------------------------------------------------------------------------
# 选题洞察（只基于公开元数据与词频，不冒充论文结论）
# --------------------------------------------------------------------------
def build_insights(items: list[dict], query: str = "", stats: dict | None = None) -> list[dict]:
    stats = stats or {}
    out: list[dict] = []
    if not items:
        return out

    yc = Counter(int(x["year"]) for x in items if x.get("year"))
    if yc:
        ys = sorted(yc)
        latest = ys[-1]
        latest_n = yc[latest]
        prev = [yc[y] for y in ys if y < latest]
        avg_prev = (sum(prev) / len(prev)) if prev else 0.0
        if avg_prev and latest_n >= avg_prev * 1.4:
            trend = "升温"
        elif avg_prev and latest_n <= avg_prev * 0.6:
            trend = "降温"
        else:
            trend = "平稳"
        out.append({
            "tag": "趋势",
            "title": f"{latest} 年产出{trend}",
            "text": f"本批样本中 {latest} 年 {latest_n} 篇，此前年份平均 {avg_prev:.1f} 篇/年。",
            "evidence": "按出版年份统计，仅代表本批召回结果",
        })

    vc = Counter(x["venue"] for x in items if x.get("venue"))
    if vc:
        top = vc.most_common(3)
        share = sum(c for _, c in top) / len(items)
        out.append({
            "tag": "载体",
            "title": "载体集中" if share >= 0.5 else "载体较分散",
            "text": "前三个载体共 {:.0%}：{}。".format(
                share, "、".join(f"{v}（{c}）" for v, c in top)),
            "evidence": "按期刊/会议名称统计",
        })

    gc = Counter()
    for x in items:
        for g in x.get("method_groups") or []:
            gc[g] += 1
    if gc:
        top = gc.most_common(3)
        out.append({
            "tag": "方法",
            "title": "方法主线：" + "、".join(g for g, _ in top),
            "text": "本批标题/摘要中，{} 出现最多（{} 篇）；其次为 {}。".format(
                top[0][0], top[0][1],
                "、".join(f"{g}（{c}）" for g, c in top[1:]) or "—"),
            "evidence": "按方法关键词命中篇数统计，单篇可命中多类",
        })

        if len(gc) >= 2:
            groups = [g for g, _ in gc.most_common(5)]
            cands = []
            for a_i, g1 in enumerate(groups):
                for g2 in groups[a_i + 1:]:
                    c = sum(1 for x in items
                            if g1 in (x.get("method_groups") or [])
                            and g2 in (x.get("method_groups") or []))
                    if min(gc[g1], gc[g2]) >= 3 and c <= max(1, int(0.2 * min(gc[g1], gc[g2]))):
                        cands.append((c, g1, g2))
            if cands:
                c, g1, g2 = sorted(cands)[0]
                out.append({
                    "tag": "缺口",
                    "title": f"{g1} × {g2} 交叉较少",
                    "text": f"{g1} {gc[g1]} 篇、{g2} {gc[g2]} 篇，同时出现仅 {c} 篇，"
                            f"可作为方法交叉的选题线索。",
                    "evidence": "按方法关键词共现统计，仅代表本批样本",
                })

    oa = sum(1 for x in items if x.get("is_oa"))
    out.append({
        "tag": "获取",
        "title": f"开放获取 {oa}/{len(items)}",
        "text": f"本批 {oa} 篇可直接获取全文（{oa / len(items):.0%}），"
                f"其余需通过机构订阅或出版商页面获取。",
        "evidence": "OpenAlex open_access / Crossref CC 许可字段",
    })

    miss_abs = sum(1 for x in items if len(x.get("abstract") or "") < 120)
    miss_doi = sum(1 for x in items if not x.get("doi"))
    if miss_abs or miss_doi:
        out.append({
            "tag": "证据",
            "title": "元数据完整度提示",
            "text": f"{miss_abs} 篇缺少可用摘要，{miss_doi} 篇缺少 DOI；"
                    f"摘要缺失会在详情中标注，缺少标题/年份/载体与链接的条目不进入自动推荐。",
            "evidence": "按标题/摘要/DOI/载体四项校验",
        })
    return out


def executive_summary(items: list[dict], query: str, stats: dict | None = None,
                      insights: list[dict] | None = None) -> str:
    if not items:
        return "本轮没有召回文献，建议放宽时间窗或改用更具体的英文关键词。"
    th = int((stats or {}).get("threshold") or RECOMMEND_THRESHOLD)
    rec = [x for x in items if x["rec"]]
    top3 = sorted(items, key=lambda x: -x["total"])[:3]
    parts = [f"围绕「{query}」，本批检索到 {len(items)} 篇文献，"
             f"其中 {len(rec)} 篇达到推荐阈值（综合分 ≥ {th}）。"]
    if top3:
        parts.append("优先建议阅读：" + "；".join(
            f"《{x['title'][:44]}》（{x['total']} 分，{x['year']}）" for x in top3) + "。")
    for ins in (insights or [])[:2]:
        parts.append(ins["text"])
    parts.append("以上判断只基于公开元数据与标题/摘要词频，不等同于对论文结论的评价，请结合原文核对。")
    return "".join(parts)


# --------------------------------------------------------------------------
# 引用与导出
# --------------------------------------------------------------------------
def citation_text(item: dict) -> str:
    authors = item.get("authors") or []
    if len(authors) > 3:
        au = authors[0] + " et al."
    elif authors:
        au = ", ".join(authors)
    else:
        au = "Unknown"
    year = item.get("year") or "n.d."
    title = (item.get("title") or "").rstrip(".")
    venue = item.get("venue") or ""
    s = f"{au} ({year}). {title}."
    if venue:
        s += f" {venue}."
    if item.get("doi"):
        s += f" https://doi.org/{item['doi']}"
    return s


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


def to_csv(items: list[dict]) -> str:
    def q(v) -> str:
        return '"' + str(v if v is not None else "").replace('"', '""') + '"'

    rows = ["rank,title,venue,year,cited,total,rel,nov,qual,method,insp,doi"]
    for i, x in enumerate(items, 1):
        d = x["dims"]
        rows.append(",".join([
            str(i), q(x["title"]), q(x["venue"]), str(x["year"]), str(x["cited"]),
            str(x["total"]), str(d["rel"]), str(d["nov"]), str(d["qual"]),
            str(d["method"]), str(d["insp"]), q(x["doi"]),
        ]))
    return "\n".join(rows) + "\n"


def to_json(items: list[dict]) -> str:
    payload = [{
        "title": x["title"], "venue": x["venue"], "year": x["year"], "cited": x["cited"],
        "doi": x["doi"], "url": x["url"], "is_oa": x["is_oa"], "is_top": x["is_top"],
        "authors": x["authors"], "dims": x["dims"], "total": x["total"],
        "rec": x["rec"], "why": x["why"], "method_groups": x["method_groups"],
        "source_tags": x["source_tags"],
    } for x in items]
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# 调研简报
# --------------------------------------------------------------------------
def build_report(items: list[dict], query: str, stats: dict,
                 meta: dict | None = None) -> str:
    meta = meta or {}
    stats = stats or {}
    th = int(stats.get("threshold") or RECOMMEND_THRESHOLD)
    sel = [x for x in items if x.get("sel")]
    ranked = sorted(items, key=lambda x: -x["total"])
    rec = [x for x in ranked if x["total"] >= th][:5]
    insights = meta.get("insights") or build_insights(items, query, stats)

    L: list[str] = []
    L.append("# PaperPilot 文献调研简报")
    L.append("")
    L.append(f"- 研究意图：**{query}**")
    if meta.get("query_en") and meta.get("query_en") != query:
        L.append(f"- 检索式：`{meta['query_en']}`")
    if meta.get("tags"):
        L.append(f"- 主题标签：{'、'.join(meta['tags'])}")
    L.append(f"- 数据源：{' / '.join(meta.get('sources') or ['OpenAlex'])}")
    L.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- 评分口径：相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10，"
             f"推荐阈值 {th}，另做证据完整性校验")
    L.append("")

    L.append("## 一、概览")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("| --- | --- |")
    L.append(f"| 检索命中 | {stats.get('hit', 0)} |")
    L.append(f"| 本页文献 | {stats.get('page', 0)} |")
    L.append(f"| 顶刊篇数 | {stats.get('top', 0)} |")
    L.append(f"| 开放获取 | {stats.get('oa', 0)} |")
    L.append(f"| 平均被引 | {stats.get('avg_cited', 0)} |")
    L.append(f"| 年份区间 | {stats.get('years', '—')} |")
    L.append(f"| 达到推荐阈值 | {stats.get('rec', 0)} |")
    L.append(f"| 已选入本简报 | {len(sel) if sel else min(len(ranked), 10)} |")
    L.append("")
    if stats.get("counts"):
        L.append("**分来源命中**：" + "　".join(
            f"{k} {v}" for k, v in stats["counts"].items()))
        L.append("")

    L.append("## 二、本期判断")
    L.append("")
    L.append(meta.get("summary") or executive_summary(items, query, stats, insights))
    L.append("")

    L.append("## 三、研究方向画像")
    L.append("")
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
        for g in x.get("method_groups") or []:
            meth[g] = meth.get(g, 0) + 1

    def top_of(d: dict, k: int) -> list[tuple]:
        return sorted(d.items(), key=lambda kv: -kv[1])[:k]

    L.append("**高频载体**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(venue, 6)) or "—"))
    L.append("")
    L.append("**高频术语**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(term, 12)) or "—"))
    L.append("")
    L.append("**方法取向**：" + ("、".join(f"{k}（{v}）" for k, v in top_of(meth, 8)) or "—"))
    L.append("")

    L.append("## 四、推荐精读")
    L.append("")
    if rec:
        L.append("| # | 标题 | 载体 | 年份 | 综合分 | 推荐理由 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for i, x in enumerate(rec, 1):
            title = x["title"].replace("|", "/")
            L.append(f"| {i} | {title} | {x['venue'] or '—'} | {x['year']} | **{x['total']}** | "
                     f"{x['why']} |")
    else:
        L.append(f"本轮没有达到推荐阈值（综合分 ≥ {th}）的文献，"
                 "建议放宽时间窗或换更具体的关键词重试。")
    L.append("")

    L.append("## 五、选题线索（基于元数据）")
    L.append("")
    if insights:
        for ins in insights:
            L.append(f"- **[{ins['tag']}] {ins['title']}**：{ins['text']}"
                     f"（依据：{ins['evidence']}）")
    else:
        L.append("- 暂无足够样本形成线索。")
    L.append("")
    L.append("> 这些线索只描述本批召回文献的元数据分布，不是对研究空白的最终判断；"
             "请结合全文阅读与领域知识核对。")
    L.append("")

    L.append("## 六、年份分布")
    L.append("")
    L.append("| 年份 | 篇数 |")
    L.append("| --- | --- |")
    for y, c in sorted(year.items(), key=lambda kv: -kv[0])[:8]:
        L.append(f"| {y} | {c} |")
    L.append("")

    L.append("## 七、逐篇评分明细")
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
        if x.get("method_groups"):
            L.append(f"- **方法分组**：{'、'.join(x['method_groups'])}")
        if x.get("evid_missing"):
            L.append(f"- **证据缺口**：{'、'.join(x['evid_missing'])}")
        L.append(f"- **推荐理由**：{x['why']}")
        if x["abstract"]:
            L.append(f"- **摘要要点**：{x['abstract'][:220]}…")
        L.append("")

    L.append("## 八、结论与建议")
    L.append("")
    if rec:
        L.append(f"本轮最值得优先精读的是《{rec[0]['title'][:60]}》（综合分 {rec[0]['total']}），"
                 f"{rec[0]['why']}建议按上表顺序推进精读，并优先获取开放获取版本。")
    else:
        L.append("本轮无达标文献，建议调整检索式（补充同义词 / 放宽时间窗 / 去掉限定条件）后重试。")
    L.append("")

    L.append("## 九、方法与局限")
    L.append("")
    L.append("- 相关性为 TF-IDF 余弦相似度、检索词覆盖率与召回位次的加权结果，"
             "不做语义理解；同义词、缩写与跨语言表达可能造成漏召回。")
    L.append("- 质量为期刊层级与本批被引分位的组合，不代表单篇论文的真实学术水平。")
    L.append("- 方法分组基于标题/摘要关键词，存在误判与漏判；结论必须回到原文核对。")
    L.append("- 数据来自 OpenAlex 与 Crossref 的公开元数据，可能存在字段缺失或延迟。")
    L.append("")
    L.append("> 本简报由 PaperPilot 文献雷达生成，全部指标可现场复现；"
             "文献全文请通过所在机构的合法订阅或出版商开放获取渠道获取，"
             "本工具不做任何绕过付费墙的下载。")
    L.append("")
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
