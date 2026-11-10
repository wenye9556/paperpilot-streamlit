#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 在线工作台（Streamlit 版）

一句话研究意图 → 检索 OpenAlex → 五维打分 → 智能挑选 → 调研报告 → 引用导出。

部署：share.streamlit.io（主文件 app.py）。数据源为 OpenAlex 开放学术索引（CC0），
不做任何绕过付费墙的下载。
"""

from __future__ import annotations

import io
import json
from datetime import datetime

import streamlit as st

import core

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
      .pp-hero { font-size: 30px; font-weight: 700; letter-spacing: .5px; margin-bottom: 2px; }
      .pp-sub  { color: #64748B; font-size: 15px; margin-bottom: 14px; }
      .pp-dim  { font-size: 13px; color: #334155; }
      .pp-tag  { display:inline-block; background:#DBEAFE; color:#1E3A8A; border-radius:12px;
                 padding:1px 9px; font-size:12px; margin-right:6px; }
      .pp-tag-oa { background:#DCFCE7; color:#166534; }
      .pp-tag-rec{ background:#FEF3C7; color:#92400E; }
      .pp-title { font-size:15px; font-weight:600; line-height:1.45; }
      .pp-meta  { color:#64748B; font-size:13px; margin-top:2px; }
      .pp-score { font-size:20px; font-weight:700; color:#1D4ED8; }
      .pp-foot  { color:#94A3B8; font-size:12.5px; line-height:1.7; }
      div[data-testid="stMetricValue"] { font-size: 22px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="pp-hero">📡 PaperPilot 文献雷达</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="pp-sub">输入一句研究意图，看清这个方向值得读什么 —— '
    '检索 OpenAlex 全网文献 → 五维打分排序 → 一键生成推荐精读清单与调研报告。</div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# 会话状态
# --------------------------------------------------------------------------
SS = st.session_state
SS.setdefault("items", [])
SS.setdefault("stats", {})
SS.setdefault("query", "")
SS.setdefault("report", "")
SS.setdefault("searched_at", "")

# --------------------------------------------------------------------------
# 侧边栏：检索条件
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🔍 检索条件")

    query = st.text_input(
        "研究方向 / 研究意图",
        value=SS.get("query", ""),
        placeholder="例：城市物流无人机调度 / drone delivery urban logistics",
    )

    st.caption("点选示例主题可直接填入：")
    cols = st.columns(2)
    for idx, ex in enumerate(core.EXAMPLES):
        if cols[idx % 2].button(ex, key=f"ex{idx}", width="stretch"):
            query = ex

    st.divider()
    window_label = st.selectbox("时间窗", ["近 3 年", "近 1 年", "近 5 年", "不限"], index=0)
    window_map = {"近 1 年": 365, "近 3 年": 1095, "近 5 年": 1825, "不限": 0}
    window_days = window_map[window_label]

    min_cite = st.selectbox("最少引用", [0, 5, 20, 100], index=0,
                            format_func=lambda v: "不限" if v == 0 else f"≥ {v}")
    size = st.selectbox("结果条数", [25, 50, 100], index=1)

    top_only = st.checkbox("仅顶刊池（22 刊）", value=False,
                           help="按 ISSN 在检索源头过滤：" + "、".join(n for n, _ in core.TOP_JOURNALS[:6]) + " 等 22 刊")
    oa_only = st.checkbox("仅开放获取", value=False)

    with st.expander("高级：OpenAlex API Key（可选）"):
        api_key = st.text_input("提高配额用，留空走公共配额", type="password", label_visibility="collapsed")

    st.divider()
    do_search = st.button("🔍 开始检索", type="primary", width="stretch")

    st.caption("数据来源 OpenAlex（开放学术索引，CC0）。文献全文请通过所在机构的合法订阅或"
               "出版商开放获取渠道获取；本工作台不做任何绕过付费墙的下载。")

# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------
if do_search:
    q = (query or "").strip()
    if not q:
        st.warning("请先输入研究方向，或点选一个示例主题。")
    else:
        SS["query"] = q
        with st.spinner("正在检索 OpenAlex…"):
            try:
                res = core.openalex_search(
                    q, window_days=window_days, min_cite=min_cite, size=size,
                    top_only=top_only, oa_only=oa_only, api_key=api_key.strip(),
                )
                works = res["results"]
                if not works:
                    st.error("没有命中结果，试试换个说法或放宽筛选条件。")
                    SS["items"], SS["stats"], SS["report"] = [], {}, ""
                else:
                    SS["items"] = core.score_all(works, q)
                    SS["stats"] = core.summarize(SS["items"], res["count"])
                    SS["stats"]["elapsed_ms"] = res["elapsed_ms"]
                    SS["report"] = ""
                    SS["searched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    SS["last_req"] = res["request_url"]
            except Exception as exc:  # noqa: BLE001
                st.error(f"检索失败：{type(exc).__name__}: {exc}")
                st.caption("若为 429，说明公共配额已用尽，可在侧边栏填入自己的 OpenAlex API Key。")

items: list[dict] = SS["items"]
stats: dict = SS["stats"]

# --------------------------------------------------------------------------
# 统计概览
# --------------------------------------------------------------------------
if items:
    s = stats
    st.markdown(f"#### 检索意图：{SS['query']}")
    c = st.columns(6)
    c[0].metric("检索命中", f"{s.get('hit', 0)}")
    c[1].metric("本页文献", f"{s.get('page', 0)}")
    c[2].metric("顶刊篇数", f"{s.get('top', 0)}")
    c[3].metric("开放获取", f"{s.get('oa', 0)}")
    c[4].metric("平均被引", f"{s.get('avg_cited', 0)}")
    c[5].metric("年份区间", f"{s.get('years', '—')}")
    st.caption(f"检索于 {SS.get('searched_at', '')}"
               + (f" · 接口耗时 {s['elapsed_ms']} ms" if s.get("elapsed_ms") else "")
               + f" · 达到推荐阈值（综合分 ≥ {core.RECOMMEND_THRESHOLD}）：{s.get('rec', 0)} 篇")

    # 操作区
    a1, a2, a3, a4 = st.columns([1, 1, 1, 3])
    if a1.button("🤖 智能挑选", width="stretch"):
        picked = core.pick(items)
        SS["pick_note"] = f"已智能挑选 {len(picked)} 篇（阈值：综合分 ≥ {core.RECOMMEND_THRESHOLD}）。"
    if a2.button("📝 生成调研报告", width="stretch"):
        SS["report"] = core.build_report(items, SS["query"], stats)
    if a3.button("✅ 全选 / 清空", width="stretch"):
        turn_on = not all(x.get("sel") for x in items)
        for x in items:
            x["sel"] = turn_on
    sel_n = sum(1 for x in items if x.get("sel"))
    a4.caption(f"已选 {sel_n} / {len(items)} 篇。未选择时，报告取综合分前 10 篇、导出取全部结果。"
               + ("　" + SS.get("pick_note", "") if SS.get("pick_note") else ""))

    st.divider()

    # ----------------------------------------------------------------------
    # 结果列表
    # ----------------------------------------------------------------------
    sort_by = st.radio("排序", ["按综合分", "按引用量", "按年份"], horizontal=True, label_visibility="collapsed")
    if sort_by == "按引用量":
        view = sorted(items, key=lambda x: -x["cited"])
    elif sort_by == "按年份":
        view = sorted(items, key=lambda x: -x["year"])
    else:
        view = sorted(items, key=lambda x: -x["total"])

    for rank, it in enumerate(view, 1):
        d = it["dims"]
        head = f"{rank}. {it['title'][:110]}"
        score_txt = f"综合 {it['total']}"
        with st.expander(f"{score_txt}　|　{head}", expanded=(rank <= 3)):
            left, right = st.columns([3, 1])

            with left:
                tags = []
                if it["is_top"]:
                    tags.append(f'<span class="pp-tag">★ {it["top_name"] or it["venue"]}</span>')
                if it["is_oa"]:
                    tags.append('<span class="pp-tag pp-tag-oa">开放获取</span>')
                if it["rec"]:
                    tags.append('<span class="pp-tag pp-tag-rec">推荐精读</span>')
                st.markdown("".join(tags), unsafe_allow_html=True)

                meta = f'{it["venue"] or "未标注载体"} · {it["year"]} · 被引 {it["cited"]}'
                if it["authors"]:
                    au = "、".join(it["authors"][:4]) + (" 等" if len(it["authors"]) > 4 else "")
                    meta += f" · {au}"
                st.markdown(f'<div class="pp-meta">{meta}</div>', unsafe_allow_html=True)

                st.markdown(
                    f'<div class="pp-dim">相关 <b>{d["rel"]}</b>　新颖 <b>{d["nov"]}</b>　'
                    f'质量 <b>{d["qual"]}</b>　方法 <b>{d["method"]}</b>　启发 <b>{d["insp"]}</b>　'
                    f'　综合 <b>{it["total"]}</b></div>',
                    unsafe_allow_html=True,
                )
                st.progress(min(1.0, it["total"] / 100))
                st.caption("推荐理由：" + core.reason(it))

                if it["abstract"]:
                    st.markdown(f"> {it['abstract'][:600]}{'…' if len(it['abstract']) > 600 else ''}")
                else:
                    st.caption("（OpenAlex 未提供该篇摘要，可点右侧「原文」查看出版商页面）")

            with right:
                it["sel"] = st.checkbox("选入报告 / 导出", value=bool(it.get("sel")), key=f"sel{it['i']}")
                if it["url"]:
                    st.markdown(f"[🔗 原文]({it['url']})")
                if it["doi"]:
                    st.markdown(f"[DOI](https://doi.org/{it['doi']})")
                st.caption(f"五维权重：相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10")

    # ----------------------------------------------------------------------
    # 报告
    # ----------------------------------------------------------------------
    if SS.get("report"):
        st.divider()
        st.markdown(SS["report"])

    # ----------------------------------------------------------------------
    # 导出
    # ----------------------------------------------------------------------
    st.divider()
    st.markdown("#### 📤 导出")
    sel_items = [x for x in items if x.get("sel")]
    export_items = sel_items or items
    scope = f"已选 {len(sel_items)} 篇" if sel_items else f"全部 {len(items)} 篇"

    e1, e2, e3, e4 = st.columns(4)
    e1.download_button("⬇ BibTeX (.bib)", core.to_bibtex(export_items),
                       file_name="paperpilot.bib", mime="text/plain",
                       width="stretch")
    e2.download_button("⬇ RIS (.ris)", core.to_ris(export_items),
                       file_name="paperpilot.ris", mime="text/plain",
                       width="stretch")
    e3.download_button("⬇ Markdown 报告 (.md)",
                       SS.get("report") or core.build_report(items, SS["query"], stats),
                       file_name="paperpilot-report.md", mime="text/markdown",
                       width="stretch")
    csv_rows = "rank,title,venue,year,cited,total,rel,nov,qual,method,insp,doi\n"
    for i, x in enumerate(export_items, 1):
        d = x["dims"]
        title = '"' + x["title"].replace('"', '""') + '"'
        venue = '"' + (x["venue"] or "").replace('"', '""') + '"'
        csv_rows += (f'{i},{title},{venue},{x["year"]},{x["cited"]},{x["total"]},'
                     f'{d["rel"]},{d["nov"]},{d["qual"]},{d["method"]},{d["insp"]},{x["doi"]}\n')
    e4.download_button("⬇ CSV 数据表", "\ufeff" + csv_rows, file_name="paperpilot.csv",
                       mime="text/csv", width="stretch")
    st.caption(f"当前导出范围：{scope}。")

# --------------------------------------------------------------------------
# 空状态：产品说明
# --------------------------------------------------------------------------
else:
    st.info("在左侧输入研究方向（或点一个示例主题），然后点「🔍 开始检索」。")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 六阶段流水线")
        st.markdown(
            "1. **意图解析** —— 一句大白话方向 → 英文学术检索式\n"
            "2. **多源检索** —— OpenAlex 全网文献，可选 22 刊顶刊池按 ISSN 源头过滤\n"
            "3. **五维打分** —— 相关 .40 / 新颖 .20 / 质量 .15 / 方法 .15 / 启发 .10，程序现算\n"
            "4. **合规获取** —— 只标注开放获取状态，不下载、不绕过付费墙\n"
            "5. **智能挑选** —— 按阈值自动勾选推荐精读条目，保留评分依据\n"
            "6. **报告沉淀** —— 调研报告 + BibTeX / RIS 导出，可直接进文献管理软件"
        )
    with c2:
        st.markdown("#### 22 刊顶刊池（按 ISSN 源头过滤）")
        rows = core.top_journal_table()
        st.dataframe(
            [{"期刊": r["name"], "ISSN": r["issn"], "层级": r["tier"], "权重": r["weight"]}
             for r in rows],
            width="stretch", hide_index=True, height=380,
        )

st.divider()
st.markdown(
    '<div class="pp-foot">PaperPilot 文献雷达 · 在线工作台（Streamlit 版）　|　'
    '数据来源 OpenAlex（CC0）　|　打分权重 相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10，'
    '推荐阈值 70　|　不做任何绕过付费墙的下载</div>',
    unsafe_allow_html=True,
)
