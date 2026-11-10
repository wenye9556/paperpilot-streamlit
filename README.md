# PaperPilot 文献雷达 · Streamlit 在线工作台

> 输入一句研究意图，看清这个方向值得读什么。
> 检索 OpenAlex 全网文献 → 五维打分排序 → 智能挑选 → 一键生成调研报告与引用导出。

一个面向科研入门者的文献调研工作台。把「找文献 → 判断值不值得读 → 精读 → 出调研报告」压缩成几次点击。

---

## 它做什么

| 阶段 | 能力 |
| --- | --- |
| 意图解析 | 一句大白话研究方向 → 英文学术检索式与中文主题标签 |
| 多源检索 | OpenAlex 全网文献；可选 22 刊顶刊池**按 ISSN 源头过滤**（非事后筛除） |
| 五维打分 | 相关 0.40 / 新颖 0.20 / 质量 0.15 / 方法 0.15 / 启发 0.10，程序按权重现算 |
| 合规获取 | 只标注开放获取状态，**不下载、不绕过付费墙** |
| 智能挑选 | 按阈值（综合分 ≥ 70）自动勾选推荐精读条目，保留评分依据 |
| 报告沉淀 | 调研报告 + BibTeX / RIS / CSV 导出，可直接进文献管理软件 |

---

## 数据来源与合规

- 数据源：**OpenAlex**（开放学术索引，CC0）。无需 API Key，公共配额即可使用。
- 本工作台**不做任何绕过付费墙的下载**；文献全文请通过所在机构的合法订阅或出版商开放获取渠道获取。
- 可选：在侧边栏填入自己的 OpenAlex API Key 以提高配额。

---

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

浏览器打开提示的地址（默认 <http://localhost:8501>）。

---

## 部署到 Streamlit Community Cloud

1. 把本仓库推到 GitHub（公开仓库最简单）。
2. 打开 <https://share.streamlit.io>，用 GitHub 账号登录并授权。
3. 点 **Create app** → 选本仓库 → Branch 填 `main` → Main file path 填 `app.py`。
4. （可选）在 App URL 里自定义子域名。
5. 点 **Deploy**，约 2–3 分钟即可得到 `https://<你的子域名>.streamlit.app` 公开链接。

> `requirements.txt` 只依赖 `streamlit`，其余全部使用 Python 标准库，构建很快。

---

## 验证示例

检索主题：`truck drone collaborative delivery routing`，勾选「仅顶刊池（22 刊）」。

| 指标 | 数值 |
| --- | --- |
| 检索命中 | 88 |
| 本页文献 | 50 |
| 顶刊篇数 | 50 |
| 开放获取 | 31 |
| 平均被引 | 25 |
| 年份区间 | 2023–2026 |

---

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `app.py` | Streamlit 界面：侧边栏检索条件、统计概览、结果卡片、报告渲染、导出 |
| `core.py` | 核心引擎：检索、五维打分、智能挑选、报告生成、BibTeX / RIS / CSV 导出（纯标准库） |
| `requirements.txt` | 依赖清单（仅 `streamlit`） |
| `.streamlit/config.toml` | 主题与服务器配置 |

---

## 22 刊顶刊池（按 ISSN）

EJOR · COR · Transportation Science · OMEGA · TR Part A/B/C/D/E · Networks ·
Mathematics of OR · Operations Research · Management Science · M&SOM · POM · IJOC ·
IEEE TITS · IEEE TEVC · IEEE TASE · IEEE TCYB · IEEE IoT-J · IEEE TII

---

## 许可

本仓库仅用于赛事作品演示。数据来源 OpenAlex（CC0）。
