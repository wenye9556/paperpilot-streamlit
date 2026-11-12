#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 意图解析

把用户输入的一句中文/英文研究意图，转成可用于 OpenAlex / Crossref 的英文检索式，
并抽取出可读的主题标签。全部基于本地学术术语词典（最长匹配），不依赖网络与模型。

设计口径：
- 我只做「术语翻译 + 检索式拼装」，不编造用户没说的概念；
- 未识别的中文词会原样列在 unknown 里，由界面提示用户改写或启用 LLM 增强；
- 英文输入原样保留，只补充常见缩写（VRP / DRL / MIP 等）。
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# 中英学术术语词典
# key 为中文，value 为英文检索词（多个候选用 " / " 分隔，取第一个进检索式）
# --------------------------------------------------------------------------
GLOSSARY: dict[str, str] = {
    # 物流与供应链
    "城市物流": "urban logistics",
    "最后一公里": "last-mile delivery",
    "协同配送": "collaborative delivery",
    "车辆路径问题": "vehicle routing problem",
    "车辆路径": "vehicle routing",
    "路径规划": "routing",
    "配送": "delivery",
    "物流": "logistics",
    "供应链韧性": "supply chain resilience",
    "供应链": "supply chain",
    "库存管理": "inventory management",
    "库存": "inventory",
    "仓储": "warehousing",
    "设施选址": "facility location",
    "选址": "location",
    "冷链": "cold chain",
    "生鲜": "fresh produce",
    "电商": "e-commerce",
    "零售": "retail",
    "采购": "procurement",
    "供应商": "supplier",
    "需求预测": "demand forecasting",
    "订单": "order",
    "定价": "pricing",
    "收益管理": "revenue management",
    "契约": "contract",
    "平台": "platform",
    "共享经济": "sharing economy",
    # 交通与运输
    "无人机": "drone / UAV",
    "卡车": "truck",
    "货车": "truck",
    "车队": "fleet",
    "电动车辆": "electric vehicle",
    "电动车": "electric vehicle",
    "电动汽车": "electric vehicle",
    "充电": "charging",
    "换电": "battery swapping",
    "交通流": "traffic flow",
    "交通": "traffic",
    "公交": "transit",
    "地铁": "metro",
    "铁路": "railway",
    "航运": "shipping",
    "港口": "port",
    "港航": "port shipping",
    "泊位调度": "berth scheduling",
    "泊位": "berth",
    "船舶": "vessel",
    "航空": "aviation",
    "机场": "airport",
    "航班": "flight",
    "延误": "delay",
    "多式联运": "intermodal transport",
    "危险品": "hazardous materials",
    "应急": "emergency",
    "应急救援": "emergency rescue",
    "救援": "rescue",
    "物资": "supplies",
    "灾害": "disaster",
    "疏散": "evacuation",
    "人道主义": "humanitarian",
    # 制造与能源
    "制造": "manufacturing",
    "生产计划": "production planning",
    "车间调度": "job shop scheduling",
    "柔性制造": "flexible manufacturing",
    "数字孪生": "digital twin",
    "工业互联网": "industrial internet",
    "预测性维护": "predictive maintenance",
    "质量控制": "quality control",
    "能源": "energy",
    "新能源": "renewable energy",
    "可再生能源": "renewable energy",
    "电力系统": "power system",
    "微电网": "microgrid",
    "储能": "energy storage",
    "碳排放": "carbon emission",
    "低碳": "low carbon",
    "可持续": "sustainable",
    "循环经济": "circular economy",
    "农业": "agriculture",
    "食品": "food",
    "医疗": "healthcare",
    "医院": "hospital",
    "医疗健康": "healthcare",
    "养老服务": "elderly care",
    "预约": "appointment scheduling",
    "排队": "queueing",
    # 方法与算法
    "组合优化": "combinatorial optimization",
    "整数规划": "integer programming",
    "混合整数": "mixed-integer",
    "线性规划": "linear programming",
    "动态规划": "dynamic programming",
    "鲁棒优化": "robust optimization",
    "随机规划": "stochastic programming",
    "分布鲁棒": "distributionally robust",
    "列生成": "column generation",
    "分支定界": "branch and bound",
    "分支定价": "branch and price",
    "拉格朗日": "Lagrangian",
    "分解": "decomposition",
    "启发式": "heuristic",
    "元启发式": "metaheuristic",
    "遗传算法": "genetic algorithm",
    "禁忌搜索": "tabu search",
    "模拟退火": "simulated annealing",
    "粒子群": "particle swarm",
    "蚁群": "ant colony",
    "大邻域搜索": "large neighborhood search",
    "自适应大邻域搜索": "adaptive large neighborhood search",
    "局部搜索": "local search",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "强化学习": "reinforcement learning",
    "深度强化学习": "deep reinforcement learning",
    "神经网络": "neural network",
    "图神经网络": "graph neural network",
    "大语言模型": "large language model",
    "大模型": "large language model",
    "注意力机制": "attention mechanism",
    "时间序列": "time series",
    "回归": "regression",
    "分类": "classification",
    "聚类": "clustering",
    "预测": "prediction",
    "仿真": "simulation",
    "模拟": "simulation",
    "离散事件仿真": "discrete event simulation",
    "系统动力学": "system dynamics",
    "蒙特卡洛": "Monte Carlo",
    "多目标优化": "multi-objective optimization",
    "多目标": "multi-objective",
    "帕累托": "Pareto",
    "鲁棒性": "robustness",
    "不确定性": "uncertainty",
    "风险评估": "risk assessment",
    "韧性": "resilience",
    "博弈": "game theory",
    "机制设计": "mechanism design",
    "拍卖": "auction",
    "马尔可夫决策": "Markov decision process",
    "因果推断": "causal inference",
    "双重差分": "difference-in-differences",
    "工具变量": "instrumental variable",
    "面板数据": "panel data",
    "实证": "empirical",
    "计量": "econometric",
    "案例研究": "case study",
    "案例": "case study",
    "问卷": "survey",
    "实验": "experiment",
    "综述": "literature review",
    "元分析": "meta-analysis",
    "系统综述": "systematic review",
    "数据驱动": "data-driven",
    "优化": "optimization",
    "调度": "scheduling",
    "决策": "decision-making",
    "资源配置": "resource allocation",
    "风险管理": "risk management",
    "可视化": "visualization",
    "知识库": "knowledge base",
}

# 常见英文缩写 → 补全（只在英文输入中出现时追加，不改写原词）
EN_EXPANSIONS: dict[str, str] = {
    "uav": "drone",
    "vrp": "vehicle routing problem",
    "tsp": "traveling salesman problem",
    "drl": "deep reinforcement learning",
    "rl": "reinforcement learning",
    "mip": "mixed integer programming",
    "milp": "mixed integer linear programming",
    "alns": "adaptive large neighborhood search",
    "lns": "large neighborhood search",
    "gnn": "graph neural network",
    "llm": "large language model",
    "mcdm": "multi-criteria decision making",
    "agv": "automated guided vehicle",
    "iot": "internet of things",
    "abm": "agent-based model",
}

# 中文停用词：不参与「未识别词」提示
CJK_STOP = set(
    ("的 了 与 和 及 在 中 下 上 对 为 是 有 无 一种 一个 如何 什么 哪些 研究 分析 方法 "
     "问题 应用 基于 面向 关于 及其 以及 一种 这类 相关").split()
)

MAX_QUERY_TERMS = 14
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _sorted_glossary() -> list[tuple[str, str]]:
    return sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0]))


_GLOSSARY_SORTED = _sorted_glossary()
_EN_TO_ZH: dict[str, str] = {}
for _zh, _en in GLOSSARY.items():
    for _alt in _en.split(" / "):
        _EN_TO_ZH.setdefault(_alt.strip().lower(), _zh)


def _match_zh(text: str) -> tuple[list[tuple[int, int, str, str]], list[str]]:
    """最长匹配中文术语，返回 (命中列表, 未识别中文片段)。"""
    consumed = [False] * len(text)
    hits: list[tuple[int, int, str, str]] = []
    i = 0
    while i < len(text):
        matched = False
        for zh, en in _GLOSSARY_SORTED:
            if text.startswith(zh, i):
                hits.append((i, i + len(zh), zh, en.split(" / ")[0].strip()))
                for k in range(i, i + len(zh)):
                    consumed[k] = True
                i += len(zh)
                matched = True
                break
        if not matched:
            i += 1

    unknown: list[str] = []
    i = 0
    while i < len(text):
        if _CJK_RE.match(text[i]) and not consumed[i]:
            j = i
            while j < len(text) and _CJK_RE.match(text[j]) and not consumed[j]:
                j += 1
            frag = text[i:j]
            if frag not in CJK_STOP and len(frag) >= 2:
                unknown.append(frag)
            i = j
        else:
            i += 1
    return hits, unknown


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        k = s.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(s.strip())
    return out


def _english_terms(text: str) -> list[str]:
    """从输入中抽取英文词，补充缩写全称（保留用户原始措辞）。"""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9&/+-]{1,}", text or "")
    out: list[str] = []
    for w in raw:
        out.append(w)
        if w.lower() in EN_EXPANSIONS:
            out.append(EN_EXPANSIONS[w.lower()])
    return _dedupe(out)


def parse(text: str) -> dict:
    """解析研究意图。

    返回：
        raw      原始输入
        query    用于检索的英文检索式
        tags     中文主题标签（来自词典命中）
        unknown  未识别的中文片段
        source   glossary（中文词典命中）/ english（英文输入）/ fallback（无法翻译）
        note     给界面显示的一句话说明
    """
    raw = (text or "").strip()
    if not raw:
        return {"raw": "", "query": "", "tags": [], "unknown": [],
                "source": "empty", "note": "请输入研究方向。"}

    if not has_cjk(raw):
        terms = _english_terms(raw)
        query = " ".join(terms)[:400] if terms else raw
        tags = [zh for alt, zh in _EN_TO_ZH.items() if alt in raw.lower()]
        tags = _dedupe(tags)[:6]
        return {
            "raw": raw,
            "query": query,
            "tags": tags,
            "unknown": [],
            "source": "english",
            "note": "英文意图直接检索" + ("，已补全常见缩写" if any(w.lower() in EN_EXPANSIONS for w in re.findall(r"[A-Za-z]+", raw)) else ""),
        }

    hits, unknown = _match_zh(raw)
    en_terms = [en for _, _, _, en in hits]
    # 中英混写：把用户自己写的英文词也带上
    en_terms += [w for w in _english_terms(raw) if w.lower() not in {t.lower() for t in en_terms}]

    if not en_terms:
        return {
            "raw": raw,
            "query": raw,
            "tags": [],
            "unknown": unknown,
            "source": "fallback",
            "note": "未能把中文术语翻译成英文检索式，已按原样检索；建议改用英文关键词，或启用 LLM 增强。",
        }

    query = " ".join(_dedupe(en_terms)[:MAX_QUERY_TERMS])
    tags = _dedupe([zh for _, _, zh, _ in hits])[:8]
    note = f"已识别 {len(hits)} 个术语并转成英文检索式"
    if unknown:
        note += f"；未识别：{'、'.join(unknown[:4])}"
    return {
        "raw": raw,
        "query": query,
        "tags": tags,
        "unknown": unknown,
        "source": "glossary",
        "note": note,
    }


def explain(intent: dict) -> str:
    """给界面用的一行解析说明。"""
    if not intent:
        return ""
    src = intent.get("source")
    if src == "glossary":
        parts = [f"{intent['raw']} → **{intent['query']}**"]
        if intent.get("tags"):
            parts.append("标签：" + "、".join(intent["tags"]))
        return "　|　".join(parts)
    if src == "english":
        return f"英文意图 → **{intent['query']}**"
    if src == "fallback":
        return "未识别中文术语，已按原样检索"
    return ""
