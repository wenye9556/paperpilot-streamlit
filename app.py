#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 在线工作台（Streamlit 版 v2）

一句话研究意图 → 意图解析 → OpenAlex + Crossref 双源检索 → 可解释五维评分
→ 选题洞察 → 调研简报 → 引用导出。

零 Key 可用；填入任意 OpenAI 兼容接口可启用 AI 意图解析、推荐理由与摘要润色。
数据来源为公开学术元数据（OpenAlex CC0 / Crossref），不做任何绕过付费墙的下载。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from html import escape as h
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import core
import intent as intent_mod
import llm
import sources

st.set_page_config(
    page_title="PaperPilot 文献雷达",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------
# 样式
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
      :root { --ink:#0F172A; --muted:#64748B; --line:#E2E8F0; --blue:#1D4ED8; }
      .stApp { background: linear-gradient(180deg,#F8FAFC 0%,#FFFFFF 300px); }
      .block-container { padding-top: 2.8rem; padding-bottom: 3rem; max-width: 1180px; }
      section[data-testid="stSidebar"] { background:#F8FAFC; border-right:1px solid var(--line); }
      .pp-hero { padding: 6px 0 18px; }
      .pp-kicker { font-size:12.5px; letter-spacing:.12em; color:var(--blue); font-weight:700; text-transform:uppercase; }
      .pp-hero h1 { font-size:34px; line-height:1.25; margin:8px 0 10px; color:var(--ink); font-weight:750; }
      .pp-hero p { color:#475569; font-size:15.5px; margin:0; }
      .pp-statrow { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:6px 0 12px; }
      .pp-stat { background:#fff; border:1px solid var(--line); border-radius:12px; padding:11px 14px; }
      .pp-stat b { display:block; font-size:21px; color:var(--ink); line-height:1.25; }
      .pp-stat span { font-size:11.5px; color:var(--muted); }
      .pp-intent { background:#EFF6FF; border:1px solid #BFDBFE; border-radius:12px;
                   padding:11px 14px; font-size:13px; color:#1E3A8A; margin:4px 0 12px; }
      .pp-intent b { color:#1D4ED8; }
      .pp-chip { display:inline-block; background:#DBEAFE; color:#1E3A8A; border-radius:999px;
                 padding:1px 9px; font-size:11.5px; margin-left:6px; }
      .pp-chip-ai { background:#EDE9FE; color:#5B21B6; }
      .pp-title { font-size:15.5px; font-weight:650; line-height:1.5; color:var(--ink); }
      .pp-badges { display:flex; flex-wrap:wrap; gap:6px; margin:7px 0 8px; }
      .b { font-size:11.5px; padding:2px 8px; border-radius:999px; line-height:1.6; }
      .b-top { background:#DBEAFE; color:#1E3A8A; }
      .b-rec { background:#FEF3C7; color:#92400E; }
      .b-oa { background:#DCFCE7; color:#166534; }
      .b-src { background:#EDE9FE; color:#5B21B6; }
      .b-warn { background:#FEE2E2; color:#991B1B; }
      .b-plain { background:#F1F5F9; color:#475569; }
      .pp-dims { display:flex; gap:14px; flex-wrap:wrap; margin:2px 0 7px; }
      .pp-dim { display:flex; align-items:center; gap:5px; font-size:11.5px; color:var(--muted); }
      .pp-bar { width:52px; height:5px; background:#E2E8F0; border-radius:3px; overflow:hidden; }
      .pp-bar i { display:block; height:100%; background:linear-gradient(90deg,#93C5FD,#1D4ED8); }
      .pp-dim b { font-size:11.5px; color:#334155; }
      .pp-why { font-size:12.5px; color:#475569; line-height:1.6; }
      .pp-ring { text-align:center; padding-top:3px; }
      .pp-ring span { display:block; font-size:10.5px; color:var(--muted); margin-top:-3px; }
      .pp-insight { background:#fff; border:1px solid var(--line); border-left:4px solid #1D4ED8;
                    border-radius:10px; padding:13px 15px; margin-bottom:10px; }
      .pp-insight b { font-size:13.5px; color:var(--ink); }
      .pp-insight p { margin:4px 0 3px; font-size:13px; color:#475569; line-height:1.6; }
      .pp-insight small { color:#94A3B8; font-size:11px; }
      .pp-step { background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px; }
      .pp-step b { color:#1D4ED8; font-size:12px; letter-spacing:.1em; }
      .pp-step h3 { margin:6px 0 6px; font-size:16px; color:var(--ink); }
      .pp-step p { margin:0; font-size:13px; color:#64748B; line-height:1.65; }
      .pp-note { background:#FFF7ED; border:1px solid #FCD34D; border-radius:10px;
                 padding:13px 15px; font-size:13px; color:#92400E; line-height:1.65; }
      .pp-foot { color:#94A3B8; font-size:12px; line-height:1.8; border-top:1px solid var(--line);
                 padding-top:14px; margin-top:24px; }
      div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line);
                                    border-radius:12px; padding:10px 14px; }
      div[data-testid="stMetricLabel"] p { font-size:12px; color:#64748B; }
      div[data-testid="stMetricValue"] { font-size:22px; }
      div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
      div[data-testid="stExpander"] details { border-radius:10px; }
      button[data-baseweb="tab"] { font-size:14.5px; }
      @media (max-width: 900px) { .pp-statrow { grid-template-columns:repeat(3,1fr); } }
      @media (max-width: 640px) {
        .block-container { padding-left:.8rem; padding-right:.8rem; padding-top:2.2rem; }
        .pp-hero h1 { font-size:24px; }
        .pp-statrow { grid-template-columns:repeat(2,1fr); }
        .pp-dims { gap:8px; }
        .pp-title { font-size:14px; }
        .pp-intent { font-size:12px; }
        div[data-testid="stMetric"] { padding:8px 10px; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

SS = st.session_state
SS.setdefault("items", [])
SS.setdefault("stats", {})
SS.setdefault("query", "")
SS.setdefault("intent", {})
SS.setdefault("insights", [])
SS.setdefault("summary", "")
SS.setdefault("ai_summary", "")
SS.setdefault("searched_at", "")
SS.setdefault("history", [])
SS.setdefault("sel_keys", set())
SS.setdefault("stars", set())
SS.setdefault("llm_reasons", {})
SS.setdefault("llm_error", "")
SS.setdefault("llm_used", False)
SS.setdefault("pick_note", "")
SS.setdefault("auto_search", False)
SS.setdefault("demo_mode", False)
SS.setdefault("url_loaded", False)

# --------------------------------------------------------------------------
# URL 参数：支持分享「带检索条件的可复现链接」
# --------------------------------------------------------------------------
QP = st.query_params
if not SS["url_loaded"]:
    SS["url_loaded"] = True
    if QP.get("q"):
        SS["q"] = QP.get("q")
        window_map_qp = {"0": "不限", "365": "近 1 年", "1095": "近 3 年", "1825": "近 5 年"}
        if QP.get("window") in window_map_qp:
            SS["f_window"] = window_map_qp[QP["window"]]
        if QP.get("cite") in {"0", "5", "20", "100"}:
            SS["f_cite"] = int(QP["cite"])
        if QP.get("size") in {"25", "50", "100"}:
            SS["f_size"] = int(QP["size"])
        if QP.get("top") in {"0", "1"}:
            SS["f_top"] = QP["top"] == "1"
        if QP.get("oa") in {"0", "1"}:
            SS["f_oa"] = QP["oa"] == "1"
        if QP.get("th"):
            try:
                SS["f_thresh"] = max(55, min(90, int(QP["th"])))
            except ValueError:
                pass
        if QP.get("src"):
            picked_qp = set(QP["src"].split(","))
            SS["src_openalex"] = "openalex" in picked_qp
            SS["src_crossref"] = "crossref" in picked_qp
        SS["auto_search"] = True


SNAPSHOT_PATH = Path(__file__).with_name("demo_snapshot.json")


@st.cache_data(show_spinner=False)
def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _use_query(q: str) -> None:
    SS["q"] = q
    SS["auto_search"] = True


def _pill_change() -> None:
    v = SS.get("example_pill")
    if v:
        _use_query(v)
        SS["example_pill"] = None


def _load_demo() -> None:
    """载入随包示例快照：网络/配额异常时也能完整演示。"""
    try:
        data = load_snapshot()
    except Exception as exc:  # noqa: BLE001
        st.error(f"示例快照加载失败：{exc}")
        return
    SS["items"] = data.get("items") or []
    SS["stats"] = data.get("stats") or {}
    SS["query"] = data.get("query") or ""
    SS["intent"] = data.get("intent") or {}
    SS["insights"] = data.get("insights") or []
    SS["summary"] = data.get("summary") or ""
    SS["searched_at"] = (data.get("generated_at") or "") + "（示例快照）"
    SS["demo_mode"] = True
    SS["sel_keys"] = set()
    SS["llm_reasons"] = {}
    SS["pick_note"] = ""
    SS["ai_summary"] = ""
    SS["history"] = [SS["query"]] if SS["query"] else []
    st.query_params["q"] = SS["query"]


def ring_html(score: int) -> str:
    r = 27
    circ = 2 * math.pi * r
    frac = max(0.0, min(1.0, score / 100))
    color = "#16A34A" if score >= 80 else ("#1D4ED8" if score >= 70 else "#64748B")
    return (
        f'<div class="pp-ring"><svg viewBox="0 0 64 64" width="64" height="64">'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="#E2E8F0" stroke-width="6"/>'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{color}" stroke-width="6" '
        f'stroke-linecap="round" stroke-dasharray="{circ * frac:.1f} {circ:.1f}" '
        f'transform="rotate(-90 32 32)"/>'
        f'<text x="32" y="37" text-anchor="middle" font-size="17" font-weight="700" '
        f'fill="#0F172A">{score}</text></svg><span>综合分</span></div>'
    )


def badges_html(it: dict) -> str:
    b = []
    if it["is_top"]:
        b.append(f'<span class="b b-top">★ {h(it["top_name"] or it["venue"])}</span>')
    if it["rec"]:
        b.append('<span class="b b-rec">推荐精读</span>')
    if it["is_oa"]:
        b.append('<span class="b b-oa">开放获取</span>')
    if len(it.get("source_tags") or []) > 1:
        b.append('<span class="b b-src">双源命中</span>')
    if not it.get("evid_ok"):
        b.append('<span class="b b-warn">证据不完整</span>')
    b.append(f'<span class="b b-plain">{h(it["venue"] or "未标注载体")}</span>')
    b.append(f'<span class="b b-plain">{it["year"]}</span>')
    b.append(f'<span class="b b-plain">被引 {it["cited"]}</span>')
    return '<div class="pp-badges">' + "".join(b) + "</div>"


def dims_html(it: dict) -> str:
    parts = []
    for k, label in (("rel", "相关"), ("nov", "新颖"), ("qual", "质量"),
                     ("method", "方法"), ("insp", "启发")):
        v = it["dims"][k]
        parts.append(
            f'<div class="pp-dim"><span>{label}</span>'
            f'<div class="pp-bar"><i style="width:{v}%"></i></div><b>{v}</b></div>'
        )
    return '<div class="pp-dims">' + "".join(parts) + "</div>"


def safe_url(u: str) -> str:
    u = (u or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def safe_request_url(u: str) -> str:
    return re.sub(r"([?&])api_key=[^&]*", r"\1api_key=***", u or "")


@st.cache_data(ttl=900, show_spinner=False)
def cached_search(query: str, window_days: int, min_cite: int, size: int,
                  top_only: bool, oa_only: bool, picked: tuple, openalex_key: str) -> dict:
    return sources.search_all(
        query, window_days=window_days, min_cite=min_cite, size=size,
        top_only=top_only, oa_only=oa_only, sources=picked, openalex_key=openalex_key,
    )


def run_search(q: str, window_days: int, min_cite: int, size: int, top_only: bool,
               oa_only: bool, threshold: int, picked: tuple, openalex_key: str,
               llm_cfg: llm.LLMConfig, llm_enabled: bool) -> None:
    q = (q or "").strip()
    if not q:
        st.warning("请先输入研究方向，或点一个示例主题。")
        return

    parsed = intent_mod.parse(q)
    SS["llm_used"] = False
    SS["llm_error"] = ""

    if llm_enabled and llm_cfg.ready:
        try:
            with st.spinner("AI 正在解析研究意图…"):
                ai = llm.parse_intent(llm_cfg, q)
            parsed = dict(parsed)
            parsed["query"] = ai["query"]
            parsed["tags"] = ai.get("tags") or parsed.get("tags") or []
            parsed["source"] = "llm"
            parsed["note"] = ai.get("note") or "LLM 已改写检索式"
            SS["llm_used"] = True
        except llm.LLMError as exc:
            SS["llm_error"] = str(exc)

    SS["intent"] = parsed

    with st.spinner("正在并行检索 OpenAlex 与 Crossref…"):
        try:
            res = cached_search(
                parsed["query"], int(window_days), int(min_cite), int(size),
                bool(top_only), bool(oa_only), tuple(picked), openalex_key,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"检索失败：{type(exc).__name__}: {exc}")
            return

    items = core.score_all(res["items"], parsed["query"], threshold=int(threshold))
    if not items:
        SS["items"], SS["stats"], SS["insights"] = [], {}, []
        SS["query"], SS["summary"] = q, ""
        err = "；".join(f"{colors(s)}: {e}" for s, e in (res.get("errors") or {}).items())
        st.error("没有召回文献。" + (f"（{err}）" if err else "试试换个说法或放宽筛选条件。"))
        return

    stats = core.summarize(items, res.get("hit") or len(items))
    stats.update({
        "counts": res.get("counts") or {},
        "errors": res.get("errors") or {},
        "request_urls": res.get("request_urls") or {},
        "elapsed_ms": res.get("elapsed_ms") or 0,
        "sources": res.get("sources_used") or [],
        "threshold": int(threshold),
    })
    insights = core.build_insights(items, q, stats)
    summary = core.executive_summary(items, q, stats, insights)

    SS["items"] = items
    SS["stats"] = stats
    SS["query"] = q
    SS["insights"] = insights
    SS["summary"] = summary
    SS["ai_summary"] = ""
    SS["demo_mode"] = False
    SS["searched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SS["sel_keys"] = set()
    SS["llm_reasons"] = {}
    SS["pick_note"] = ""
    SS["history"] = ([q] + [x for x in SS["history"] if x != q])[:6]

    # 把检索条件写进 URL，便于分享与复现
    st.query_params["q"] = q
    st.query_params["window"] = str(int(window_days))
    st.query_params["cite"] = str(int(min_cite))
    st.query_params["size"] = str(int(size))
    st.query_params["top"] = "1" if top_only else "0"
    st.query_params["oa"] = "1" if oa_only else "0"
    st.query_params["th"] = str(int(threshold))
    st.query_params["src"] = ",".join(picked)


def colors(src: str) -> str:
    return sources.SOURCE_LABEL.get(src, src)


# --------------------------------------------------------------------------
# 侧边栏
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📡 PaperPilot 文献雷达")
    st.caption("v3.0 · 一句话意图 → 可读的文献调研简报")

    st.markdown("#### ① 说方向")
    st.text_input(
        "研究方向",
        key="q",
        placeholder="例：城市物流无人机调度 / truck drone routing",
        label_visibility="collapsed",
    )
    st.pills(
        "示例主题", core.EXAMPLES, key="example_pill",
        label_visibility="collapsed", on_change=_pill_change,
    )
    do_search = st.button("🔍 开始检索", type="primary", width="stretch", key="btn_search")

    st.markdown("#### ② 关键筛选")
    top_only = st.checkbox("仅顶刊池（22 刊）", value=False, key="f_top")
    threshold = st.slider("推荐阈值", 55, 90, 70, 1, key="f_thresh",
                          help="综合分达到该值且证据完整，才标记为「推荐精读」。")

    with st.expander("③ 高级筛选与数据源", expanded=False):
        window_label = st.selectbox("时间窗", ["近 3 年", "近 1 年", "近 5 年", "不限"],
                                    index=0, key="f_window")
        min_cite = st.selectbox("最少引用", [0, 5, 20, 100], index=0, key="f_cite",
                                format_func=lambda v: "不限" if v == 0 else f"≥ {v}")
        size = st.selectbox("召回条数", [25, 50, 100], index=1, key="f_size")
        oa_only = st.checkbox("仅开放获取", value=False, key="f_oa")

        st.markdown("**数据源**")
        use_openalex = st.checkbox("OpenAlex（开放学术索引）", value=True, key="src_openalex")
        use_crossref = st.checkbox("Crossref（出版商元数据）", value=True, key="src_crossref")
        st.text_input("OpenAlex API Key（可选，提高配额）", key="oa_key", type="password")

    picked_sources = tuple(
        s for s, on in (("openalex", use_openalex), ("crossref", use_crossref)) if on
    ) or ("openalex",)
    window_map = {"近 1 年": 365, "近 3 年": 1095, "近 5 年": 1825, "不限": 0}
    window_days = window_map[window_label]

    st.button("⚡ 载入示例结果", key="btn_demo", width="stretch", on_click=_load_demo)
    st.caption("默认近 3 年 · 双源 · 50 篇；示例结果为 2026-11-12 快照，不依赖网络。")

    st.divider()
    with st.expander("✨ AI 增强（自带 Key，可选）", expanded=False):
        st.caption("不填也能用；填入任意 OpenAI 兼容接口即可启用 AI 意图解析与摘要。")
        st.text_input("Base URL", key="llm_base",
                      placeholder="https://api.deepseek.com/v1")
        st.text_input("API Key", key="llm_key", type="password")
        st.text_input("模型名", key="llm_model", placeholder="deepseek-chat")
        llm_enabled = st.checkbox("启用 AI 增强", value=True, key="llm_enable")
        llm_cfg = llm.LLMConfig(
            base_url=SS.get("llm_base", ""),
            api_key=SS.get("llm_key", ""),
            model=SS.get("llm_model", ""),
        )
        if st.button("测试连接", key="llm_test", width="stretch"):
            try:
                msg = llm.test_connection(llm_cfg)
                st.success(f"连接成功：{msg[:30]}")
            except llm.LLMError as exc:
                st.error(str(exc))
        if llm_cfg.ready:
            st.caption("Key 仅保存在当前会话内存，不写入磁盘。")
        else:
            st.caption("当前为本地可解释模式（零 Key 可用）。")

    st.divider()
    if SS["history"]:
        st.markdown("**最近检索**")
        for i, item in enumerate(SS["history"]):
            label = item if len(item) <= 18 else item[:18] + "…"
            st.button(label, key=f"his{i}", on_click=_use_query, args=(item,), width="stretch")

    st.caption("数据来源：OpenAlex（CC0）与 Crossref 公开元数据。"
               "不下载全文、不绕过付费墙。")

# --------------------------------------------------------------------------
# 检索触发
# --------------------------------------------------------------------------
auto_search = SS.pop("auto_search", False)
if do_search or auto_search:
    run_search(
        SS.get("q", ""), window_days, min_cite, size, top_only, oa_only, threshold,
        picked_sources, SS.get("oa_key", "").strip(), llm_cfg, llm_enabled,
    )

items: list[dict] = SS["items"]
stats: dict = SS["stats"]
parsed: dict = SS["intent"]

# --------------------------------------------------------------------------
# 顶部
# --------------------------------------------------------------------------
st.markdown(
    """
    <div class="pp-hero">
      <div class="pp-kicker">PaperPilot · Literature Radar</div>
      <h1>一句话研究意图，变成一份可读的文献调研简报</h1>
      <p>OpenAlex + Crossref 双源检索 · 可解释五维评分 · 选题线索 · 引用一键导出</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# 空状态
# --------------------------------------------------------------------------
if not items:
    st.markdown(
        """
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:8px 0 18px;">
          <div class="pp-step"><b>STEP 01</b><h3>说一句研究方向</h3>
            <p>中文或英文都行。系统会把「城市物流无人机调度」这类意图翻译成英文学术检索式。</p></div>
          <div class="pp-step"><b>STEP 02</b><h3>看雷达排序</h3>
            <p>双源召回后，按相关、新颖、质量、方法、启发五维打分，并做证据完整性校验。</p></div>
          <div class="pp-step"><b>STEP 03</b><h3>拿走调研简报</h3>
            <p>勾选想读的文献，一键生成选题线索、推荐清单与 BibTeX / RIS / CSV。</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1.15, 1], gap="large")
    with c1:
        st.markdown("#### 这个工具解决什么")
        st.markdown(
            "科研入门者从「有个方向」到「知道该读什么」，中间隔着检索、筛选、判断、整理四道手工活。"
            "PaperPilot 把这段流程压缩成一次检索：**先把意图翻译成检索式，再用可解释的评分给出阅读顺序，"
            "最后把结果整理成能直接带走的简报与引用文件**。"
        )
        st.markdown(
            "- **零 Key 可用**：不配置任何模型也能完成检索、打分、洞察与导出\n"
            "- **可解释**：每一分都能看到来源，不是黑箱推荐\n"
            "- **可复现**：检索式、筛选条件、来源与耗时全部展示\n"
            "- **合规**：只读公开元数据，不下载全文、不绕过付费墙"
        )
        st.markdown(
            '<div class="pp-note">评委可直接输入任意主题体验；若网络或 OpenAlex 配额不稳定，'
            '点下方「载入示例结果」即可看到完整流程（2026-11-12 快照）。</div>',
            unsafe_allow_html=True,
        )
        if st.button("⚡ 载入示例结果", key="btn_demo_empty", width="stretch"):
            _load_demo()
            st.rerun()
    with c2:
        st.markdown("#### 22 刊顶刊池（按 ISSN 源头过滤）")
        st.dataframe(
            [{"期刊": r["name"], "ISSN": r["issn"], "层级": r["tier"]}
             for r in core.top_journal_table()],
            width="stretch", hide_index=True, height=392,
        )

    st.markdown(
        '<div class="pp-foot">PaperPilot 文献雷达 · 数据来源 OpenAlex（CC0）与 Crossref · '
        '评分口径 相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10，默认推荐阈值 70 · '
        '不做任何绕过付费墙的下载</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# --------------------------------------------------------------------------
# 结果概览
# --------------------------------------------------------------------------
st.markdown(f"#### 检索意图：{h(SS['query'])}")
intent_bits = [f'<b>检索式</b> {h(parsed.get("query") or SS["query"])}']
if parsed.get("tags"):
    intent_bits.append("".join(f'<span class="pp-chip">{h(t)}</span>' for t in parsed["tags"][:8]))
if SS["llm_used"]:
    intent_bits.append('<span class="pp-chip pp-chip-ai">LLM 改写</span>')
st.markdown('<div class="pp-intent">' + "　".join(intent_bits) + "</div>", unsafe_allow_html=True)

if parsed.get("unknown"):
    st.caption("未识别的中文片段：" + "、".join(parsed["unknown"][:6])
               + "。可改用更常见的学术术语，或在侧边栏配置 LLM 增强。")
if SS.get("llm_error"):
    st.caption(f"LLM 调用失败，已自动回退到本地解析：{SS['llm_error']}")

s = stats
cards = [
    ("检索命中", f"{s.get('hit', 0):,}"),
    ("本页文献", f"{s.get('page', 0)}"),
    ("顶刊篇数", f"{s.get('top', 0)}"),
    ("开放获取", f"{s.get('oa', 0)}"),
    ("平均被引", f"{s.get('avg_cited', 0)}"),
    ("达标推荐", f"{s.get('rec', 0)}"),
]
st.markdown(
    '<div class="pp-statrow">' + "".join(
        f'<div class="pp-stat"><b>{v}</b><span>{k}</span></div>' for k, v in cards
    ) + "</div>",
    unsafe_allow_html=True,
)

src_bits = " · ".join(f"{colors(k)} {v:,}" for k, v in (s.get("counts") or {}).items())
st.caption(
    f"检索于 {SS['searched_at']} · 双源并行耗时 {s.get('elapsed_ms', 0)} ms · "
    f"{src_bits} · 年份 {s.get('years', '—')} · 达标线 综合分 ≥ {s.get('threshold', core.RECOMMEND_THRESHOLD)}"
)
if s.get("errors"):
    st.info("部分来源本次未返回结果，已自动使用其余来源，不影响本次检索："
            + "；".join(f"{colors(k)} {v}" for k, v in s["errors"].items())
            + "。若 OpenAlex 提示配额，可在「③ 高级筛选与数据源」填入自己的免费 API Key。")
if SS.get("demo_mode"):
    st.info("当前展示的是示例快照（2026-11-12），不是实时检索；"
            "点「🔍 开始检索」可拉取最新数据，点「⚡ 载入示例结果」可随时回到这份快照。")

# --------------------------------------------------------------------------
# 四个标签页
# --------------------------------------------------------------------------
tab_list, tab_insight, tab_report, tab_export = st.tabs(
    ["📚 文献", "🔭 洞察", "📝 简报", "📤 导出"]
)

with tab_list:
    st.markdown("##### 阅读顺序")
    t1, t2, t3, t4, t5 = st.columns([2.1, 1.35, 1.35, 1.2, 1.2], gap="small")
    with t1:
        sort_by = st.radio("排序", ["综合分", "引用量", "年份"], horizontal=True,
                           label_visibility="collapsed", key="sort")
    with t2:
        if st.button("🤖 智能挑选", key="btn_pick", width="stretch"):
            picked = core.pick(items)
            SS["sel_keys"] = {x["key"] for x in picked}
            SS["pick_note"] = f"已挑选 {len(picked)} 篇（综合分 ≥ {s.get('threshold', core.RECOMMEND_THRESHOLD)}，证据完整）"
            st.rerun()
    with t3:
        if st.button("✅ 全选 / 清空", key="btn_all", width="stretch"):
            if len(SS["sel_keys"]) >= len(items):
                SS["sel_keys"] = set()
            else:
                SS["sel_keys"] = {x["key"] for x in items}
            st.rerun()
    with t4:
        only_rec = st.checkbox("只看达标", key="only_rec")
    with t5:
        only_star = st.checkbox("只看收藏", key="only_star")

    view = list(items)
    if only_rec:
        view = [x for x in view if x["rec"]]
    if only_star:
        view = [x for x in view if x["key"] in SS["stars"]]
    kw = st.text_input(
        "结果内过滤", key="kw",
        placeholder="在标题、摘要、期刊中过滤，例如：reinforcement / 港口 / berth",
        label_visibility="collapsed",
    ).strip().lower()
    if kw:
        view = [x for x in view
                if kw in (x["title"] + " " + x["abstract"] + " " + x["venue"]).lower()]
    if sort_by == "引用量":
        view.sort(key=lambda x: -x["cited"])
    elif sort_by == "年份":
        view.sort(key=lambda x: -x["year"])
    else:
        view.sort(key=lambda x: -x["total"])

    bar_a, bar_b, bar_c = st.columns([4.2, 1.3, 1.5])
    with bar_a:
        st.caption(f"已选 {len(SS['sel_keys'])} / {len(items)} 篇"
                   + (f"　·　{SS['pick_note']}" if SS["pick_note"] else "")
                   + f"　·　收藏 {len(SS['stars'])} 篇"
                   + (f"　·　过滤后 {len(view)} 篇" if kw else ""))
    with bar_b:
        show_n = st.selectbox("显示", [10, 25, 50, 100], index=1,
                              label_visibility="collapsed", key="show_n")
    with bar_c:
        if llm_cfg.ready:
            if st.button("✨ AI 推荐理由", key="btn_ai_why", width="stretch"):
                try:
                    with st.spinner("AI 正在读标题与摘要…"):
                        SS["llm_reasons"] = llm.explain_items(llm_cfg, SS["query"], view[:20])
                    st.rerun()
                except llm.LLMError as exc:
                    st.error(str(exc))

    if not view:
        st.info("当前筛选下没有文献，试试取消「只看达标 / 只看收藏」或清空结果内过滤。")

    for rank, it in enumerate(view[:int(show_n)], 1):
        with st.container(border=True):
            c_ring, c_body, c_act = st.columns([0.9, 8.1, 1.7], gap="medium")
            with c_ring:
                st.markdown(ring_html(it["total"]), unsafe_allow_html=True)
            with c_body:
                st.markdown(
                    f'<div class="pp-title">{rank}. {h(it["title"])}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(badges_html(it), unsafe_allow_html=True)
                st.markdown(dims_html(it), unsafe_allow_html=True)
                why = SS["llm_reasons"].get(it["key"]) or it["why"]
                prefix = "AI 理由：" if it["key"] in SS["llm_reasons"] else "推荐理由："
                st.markdown(f'<div class="pp-why">{prefix}{h(why)}</div>',
                            unsafe_allow_html=True)
            with c_act:
                selected = it["key"] in SS["sel_keys"]
                if st.button("✓ 已选" if selected else "＋ 选入", key=f"sel_{it['key']}",
                             width="stretch"):
                    if selected:
                        SS["sel_keys"].discard(it["key"])
                    else:
                        SS["sel_keys"].add(it["key"])
                    st.rerun()
                starred = it["key"] in SS["stars"]
                if st.button("★ 已收藏" if starred else "☆ 收藏", key=f"star_{it['key']}",
                             width="stretch"):
                    if starred:
                        SS["stars"].discard(it["key"])
                    else:
                        SS["stars"].add(it["key"])
                    st.rerun()

            with st.expander("摘要 · 评分依据 · 引用"):
                au = "、".join(it["authors"][:8]) + (" 等" if len(it["authors"]) > 8 else "")
                st.markdown(f"**作者**：{h(au) if au else '—'}")
                d = it["dims"]
                st.markdown(
                    f"**评分拆解**：相关 {d['rel']} ×0.40　新颖 {d['nov']} ×0.20　"
                    f"质量 {d['qual']} ×0.15　方法 {d['method']} ×0.15　启发 {d['insp']} ×0.10"
                    f"　→　综合 **{it['total']}**"
                )
                if it.get("method_groups"):
                    st.markdown("**方法分组**：" + "、".join(it["method_groups"]))
                if it.get("domains"):
                    st.markdown("**应用领域**：" + "、".join(it["domains"]))
                if it.get("evid_missing"):
                    st.caption("证据缺口：" + "、".join(it["evid_missing"]))
                st.markdown("**摘要**：" + (h(it["abstract"]) if it["abstract"]
                                           else "OpenAlex / Crossref 未提供摘要，建议直接看原文。"),
                            unsafe_allow_html=True)
                st.markdown("**引用**（点代码块右上角复制）：")
                st.code(core.citation_text(it), language=None, wrap_lines=True)
                links = []
                oa_pdf = safe_url(it.get("oa_url"))
                if oa_pdf and it.get("is_oa"):
                    links.append(f"[直达 PDF（OA）]({oa_pdf})")
                u = safe_url(it.get("url"))
                if u:
                    links.append(f"[出版商页面]({u})")
                if it.get("doi"):
                    links.append(f"[DOI](https://doi.org/{it['doi']})")
                if links:
                    st.markdown(" · ".join(links))

with tab_insight:
    st.markdown("##### 这批文献在说什么")
    year_counts: dict[int, int] = {}
    venue_counts: dict[str, int] = {}
    method_counts: dict[str, int] = {}
    for x in items:
        year_counts[x["year"]] = year_counts.get(x["year"], 0) + 1
        if x["venue"]:
            venue_counts[x["venue"]] = venue_counts.get(x["venue"], 0) + 1
        for g in x.get("method_groups") or []:
            method_counts[g] = method_counts.get(g, 0) + 1

    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        st.markdown("**年份分布**")
        ydf = pd.DataFrame(sorted(year_counts.items()), columns=["年份", "篇数"])
        chart = (
            alt.Chart(ydf)
            .mark_bar(color="#1D4ED8", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("年份:O", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("篇数:Q"),
                tooltip=["年份", "篇数"],
            )
            .properties(height=250)
        )
        st.altair_chart(chart, use_container_width=True)
    with col2:
        st.markdown("**方法取向**")
        mdf = pd.DataFrame(
            sorted(method_counts.items(), key=lambda kv: -kv[1])[:8],
            columns=["方法", "篇数"],
        )
        if mdf.empty:
            st.caption("本批文献的标题/摘要中没有识别到方法关键词。")
        else:
            chart = (
                alt.Chart(mdf)
                .mark_bar(color="#0EA5E9", cornerRadiusEnd=4)
                .encode(
                    x=alt.X("篇数:Q"),
                    y=alt.Y("方法:N", sort="-x", axis=alt.Axis(labelLimit=160)),
                    tooltip=["方法", "篇数"],
                )
                .properties(height=250)
            )
            st.altair_chart(chart, use_container_width=True)

    st.markdown("**高频载体**")
    vdf = pd.DataFrame(
        sorted(venue_counts.items(), key=lambda kv: -kv[1])[:8],
        columns=["载体", "篇数"],
    )
    if vdf.empty:
        st.caption("Crossref / OpenAlex 未返回载体名称。")
    else:
        chart = (
            alt.Chart(vdf)
            .mark_bar(color="#7C3AED", cornerRadiusEnd=4)
            .encode(
                x=alt.X("篇数:Q"),
                y=alt.Y("载体:N", sort="-x", axis=alt.Axis(labelLimit=260)),
                tooltip=["载体", "篇数"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)

    st.divider()
    st.markdown("##### 方法 × 年份")
    method_order = [g for g, _ in sorted(method_counts.items(), key=lambda kv: -kv[1])]
    my_rows = core.method_year_matrix(items)
    if my_rows and method_order:
        mydf = pd.DataFrame(my_rows)
        base = alt.Chart(mydf).mark_rect().encode(
            x=alt.X("year:O", title="年份", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("method:N", title="", sort=method_order),
            color=alt.Color("count:Q", scale=alt.Scale(scheme="blues"), title="篇数"),
            tooltip=[alt.Tooltip("year:O", title="年份"),
                     alt.Tooltip("method:N", title="方法"),
                     alt.Tooltip("count:Q", title="篇数")],
        )
        text = alt.Chart(mydf[mydf["count"] > 0]).mark_text(
            size=10, color="#0F172A").encode(
            x=alt.X("year:O", sort=None),
            y=alt.Y("method:N", sort=method_order),
            text=alt.Text("count:Q", format="d"),
        )
        st.altair_chart((base + text).properties(height=max(240, 30 * len(method_order))),
                        use_container_width=True)
    else:
        st.caption("本批文献没有识别到方法关键词，无法生成方法趋势图。")

    st.markdown("##### 领域 × 方法")
    md_rows = core.method_domain_matrix(items)
    if md_rows:
        mddf = pd.DataFrame(md_rows)
        domains = sorted(mddf["domain"].unique())
        if len(domains) <= 1:
            st.caption(f"本批文献集中在「{domains[0]}」一个应用领域，领域×方法矩阵暂不展开。")
        else:
            base = alt.Chart(mddf).mark_rect().encode(
                x=alt.X("method:N", title="", sort=method_order,
                        axis=alt.Axis(labelAngle=-20)),
                y=alt.Y("domain:N", title="", sort=domains),
                color=alt.Color("count:Q", scale=alt.Scale(scheme="teals"), title="篇数"),
                tooltip=[alt.Tooltip("domain:N", title="领域"),
                         alt.Tooltip("method:N", title="方法"),
                         alt.Tooltip("count:Q", title="篇数")],
            )
            text = alt.Chart(mddf[mddf["count"] > 0]).mark_text(
                size=10, color="#0F172A").encode(
                x=alt.X("method:N", sort=method_order),
                y=alt.Y("domain:N", sort=domains),
                text=alt.Text("count:Q", format="d"),
            )
            st.altair_chart((base + text).properties(height=max(220, 42 * len(domains))),
                            use_container_width=True)

    st.divider()
    st.markdown("##### 选题线索")
    for ins in SS["insights"]:
        st.markdown(
            f'<div class="pp-insight"><b>[{h(ins["tag"])}] {h(ins["title"])}</b>'
            f'<p>{h(ins["text"])}</p><small>依据：{h(ins["evidence"])}</small></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="pp-note">这些线索只描述本批召回文献的元数据分布，'
        '不是对研究空白的最终判断；请结合全文阅读与领域知识核对。</div>',
        unsafe_allow_html=True,
    )

with tab_report:
    st.markdown("##### 本期判断")
    summary_text = SS.get("ai_summary") or SS.get("summary")
    st.markdown(
        f'<div class="pp-intent" style="background:#F8FAFC;border-color:#E2E8F0;color:#0F172A;">'
        f'{h(summary_text)}</div>',
        unsafe_allow_html=True,
    )
    r1, r2, r3 = st.columns([1.5, 1.5, 3])
    with r1:
        if llm_cfg.ready:
            if st.button("✨ 用 AI 润色", key="btn_ai_sum", width="stretch"):
                try:
                    with st.spinner("AI 正在写调研摘要…"):
                        SS["ai_summary"] = llm.summarize(
                            llm_cfg, SS["query"], SS["stats"], SS["insights"])
                    st.rerun()
                except llm.LLMError as exc:
                    st.error(str(exc))
        else:
            st.caption("配置 LLM Key 后可 AI 润色")
    with r2:
        if st.button("🤖 重新智能挑选", key="btn_pick2", width="stretch"):
            picked = core.pick(items)
            SS["sel_keys"] = {x["key"] for x in picked}
            SS["pick_note"] = f"已挑选 {len(picked)} 篇"
            st.rerun()

    for x in items:
        x["sel"] = x["key"] in SS["sel_keys"]
    report_md = core.build_report(items, SS["query"], stats, meta={
        "query_en": parsed.get("query") or "",
        "tags": parsed.get("tags") or [],
        "sources": [colors(s) for s in (stats.get("sources") or [])],
        "insights": SS["insights"],
        "summary": summary_text,
        "demo": SS.get("demo_mode", False),
    })
    st.divider()
    st.markdown(report_md.replace("# PaperPilot 文献调研简报", "", 1).lstrip())
    st.download_button(
        "⬇ 下载 Markdown 简报", report_md,
        file_name="paperpilot-report.md", mime="text/markdown",
        width="stretch", key="dl_report",
    )

with tab_export:
    st.markdown("##### 导出与复现")
    sel_items = [x for x in items if x["key"] in SS["sel_keys"]]
    export_items = sel_items or items
    scope = f"已选 {len(sel_items)} 篇" if sel_items else f"全部 {len(items)} 篇"
    st.caption(f"当前导出范围：{scope}。未选择时默认导出全部。")

    e1, e2, e3, e4, e5 = st.columns(5)
    with e1:
        st.download_button("⬇ BibTeX", core.to_bibtex(export_items),
                           file_name="paperpilot.bib", mime="text/plain",
                           width="stretch", key="dl_bib")
    with e2:
        st.download_button("⬇ RIS", core.to_ris(export_items),
                           file_name="paperpilot.ris", mime="text/plain",
                           width="stretch", key="dl_ris")
    with e3:
        st.download_button("⬇ CSV", "\ufeff" + core.to_csv(export_items),
                           file_name="paperpilot.csv", mime="text/csv",
                           width="stretch", key="dl_csv")
    with e4:
        st.download_button("⬇ JSON", core.to_json(export_items),
                           file_name="paperpilot.json", mime="application/json",
                           width="stretch", key="dl_json")
    with e5:
        st.download_button("⬇ 评分表 MD", core.to_markdown_table(export_items),
                           file_name="paperpilot-scores.md", mime="text/markdown",
                           width="stretch", key="dl_md")

    st.divider()
    st.markdown("##### 复现信息")
    st.markdown("**检索式**（可复制到 OpenAlex / Crossref 手动复现）：")
    st.code(parsed.get("query") or SS["query"], language=None, wrap_lines=True)

    params = {
        "原始意图": SS["query"],
        "检索式": parsed.get("query") or SS["query"],
        "时间窗": window_label,
        "最少引用": min_cite,
        "召回条数": size,
        "仅顶刊池": top_only,
        "仅开放获取": oa_only,
        "数据源": [colors(s) for s in (stats.get("sources") or [])],
        "检索时间": SS["searched_at"],
    }
    st.json(params, expanded=False)

    with st.expander("各来源请求地址（已隐藏 API Key）"):
        for k, u in (stats.get("request_urls") or {}).items():
            st.markdown(f"**{colors(k)}**")
            st.code(safe_request_url(u), language=None, wrap_lines=True)

st.markdown(
    '<div class="pp-foot">PaperPilot 文献雷达 · 数据来源 OpenAlex（CC0）与 Crossref 公开元数据 · '
    '评分口径 相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10，默认推荐阈值 70 · '
    '不做任何绕过付费墙的下载 · 文献全文请通过所在机构的合法订阅或出版商开放获取渠道获取</div>',
    unsafe_allow_html=True,
)
