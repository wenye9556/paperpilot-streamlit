#!/usr/bin/env python3
"""PaperPilot 文献雷达 · 可选 LLM 增强层

用户自带任意 OpenAI 兼容接口（DeepSeek / 通义 / Kimi / OpenAI 等）。
- 不填写 Key 时，整个应用完全可用（本地可解释模式）；
- 填写后启用：意图解析、逐篇推荐理由、调研摘要润色。

安全口径：Key 只保存在当前会话内存，不写入磁盘、不写日志、不随代码分发。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

UA = "PaperPilot-Radar/2.0 (LLM optional)"


class LLMError(RuntimeError):
    """LLM 调用失败（网络、鉴权、返回格式等）。"""


@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 45

    @property
    def ready(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())


def endpoint(base_url: str) -> str:
    """把用户填的 Base URL 归一化成 chat/completions 完整地址。"""
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/chat/completions"):
        return u
    if u.endswith("/v1"):
        return u + "/chat/completions"
    return u + "/v1/chat/completions"


def _post(cfg: LLMConfig, messages: list[dict], temperature: float = 0.2,
          max_tokens: int = 1200) -> str:
    if not cfg.ready:
        raise LLMError("未配置 Base URL / API Key / 模型。")
    url = endpoint(cfg.base_url)
    body = json.dumps({
        "model": cfg.model.strip(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": int(max_tokens),
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {cfg.api_key.strip()}",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise LLMError(f"接口返回 HTTP {exc.code}：{detail or exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"接口请求失败：{type(exc).__name__}: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
        choices = payload.get("choices") or []
        content = (choices[0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        raise LLMError("接口返回不是合法的 OpenAI 兼容格式。") from exc
    if not content.strip():
        raise LLMError("接口返回了空内容。")
    return content.strip()


def _extract_json(text: str):
    """从模型输出中提取 JSON（容忍 ```json 包裹与前后说明文字）。"""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not starts:
        raise LLMError("模型未返回 JSON。")
    start = min(starts)
    opener = s[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except Exception as exc:  # noqa: BLE001
                    raise LLMError(f"JSON 解析失败：{exc}") from exc
    raise LLMError("模型返回的 JSON 不完整。")


def test_connection(cfg: LLMConfig) -> str:
    return _post(cfg, [{"role": "user", "content": "只回复两个字：可用"}], max_tokens=16)


def parse_intent(cfg: LLMConfig, text: str) -> dict:
    """把研究意图改写成英文检索式 + 中文标签。"""
    system = (
        "你是一个只输出 JSON 的学术检索式改写器。把中文研究意图改写成英文检索式，"
        "并抽取 2-6 个中文标签。英文检索式用空格分隔，不要用连字符；保留专业术语，"
        "不添加用户没说的概念。示例输入：城市物流无人机调度。"
        "示例输出：{\"query\":\"urban logistics drone scheduling\","
        "\"tags\":[\"城市物流\",\"无人机\",\"调度\"],\"note\":\"已翻译\"}。"
        "现在只输出 JSON，不要解释、不要 markdown、不要思考过程。"
    )
    content = _post(cfg, [
        {"role": "system", "content": system},
        {"role": "user", "content": f"研究意图：{text}"},
    ], temperature=0.1, max_tokens=1200)
    data = _extract_json(content)
    if not isinstance(data, dict):
        raise LLMError("意图解析返回格式不正确。")
    query = str(data.get("query") or "").strip()
    if not query:
        raise LLMError("意图解析未返回检索式。")
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:6]
    return {"query": query[:400], "tags": tags, "note": str(data.get("note") or "").strip()[:200]}


def explain_items(cfg: LLMConfig, query: str, items: list[dict]) -> dict[str, str]:
    """为每篇文献写一句基于标题/摘要的推荐理由，返回 {key: why}。

    采用 8 篇一批的小批量调用：既降低单次输出被截断的概率，
    也让免费额度下的失败可以局部恢复。
    """
    out: dict[str, str] = {}
    last_err: LLMError | None = None
    chunk_size = 8
    for start in range(0, min(len(items), 24), chunk_size):
        chunk = items[start:start + chunk_size]
        rows = []
        for local_i, x in enumerate(chunk):
            rows.append({
                "id": local_i,
                "title": x.get("title") or "",
                "venue": x.get("venue") or "",
                "year": x.get("year") or "",
                "abstract": (x.get("abstract") or "")[:220],
            })
        system = (
            "你是文献阅读助手。为给定文献各写一句不超过 25 字的中文推荐理由。"
            "只能使用给定的标题、载体、年份和摘要，不得编造方法、数据或结论；"
            "信息不足时写「建议看原文」。只输出 JSON 数组："
            "[{\"id\":0,\"why\":\"...\"}]，不要解释、不要 markdown。"
        )
        user = json.dumps({"query": query, "items": rows}, ensure_ascii=False)
        try:
            content = _post(cfg, [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ], temperature=0.2, max_tokens=1200)
            data = _extract_json(content)
            if not isinstance(data, list):
                raise LLMError("推荐理由返回格式不正确。")
            for row in data:
                if not isinstance(row, dict):
                    continue
                try:
                    idx = int(row.get("id"))
                except (TypeError, ValueError):
                    continue
                if 0 <= idx < len(chunk):
                    why = str(row.get("why") or "").strip()
                    if why:
                        key = chunk[idx].get("key") or str(start + idx)
                        out[key] = why[:120]
        except LLMError as exc:
            last_err = exc
            continue
    if not out:
        raise last_err or LLMError("推荐理由为空。")
    return out


def summarize(cfg: LLMConfig, query: str, stats: dict, insights: list[dict]) -> str:
    """基于统计与洞察写一段调研摘要，不允许编造文献结论。"""
    system = (
        "你是科研调研助手。根据给出的检索统计与元数据洞察，写一段 150-250 字的中文调研摘要。"
        "只能使用给定字段和数字，必须沿用字段原名（如「本页文献」「达标推荐」「顶刊篇数」「开放获取」），"
        "不要改写成「检索命中」「高被引」等其他口径；不得编造具体论文结论、作者观点或未给出的数据。"
        "语气客观，先给结论，再给 1-2 条选题线索，最后提醒需读原文核对。"
    )
    stat_view = {
        "本页文献": stats.get("page"),
        "达标推荐": stats.get("rec"),
        "顶刊篇数": stats.get("top"),
        "开放获取": stats.get("oa"),
        "平均被引": stats.get("avg_cited"),
        "年份区间": stats.get("years"),
        "推荐阈值": stats.get("threshold"),
    }
    payload = {
        "query": query,
        "stats": stat_view,
        "insights": [{"title": i.get("title"), "text": i.get("text")} for i in insights],
    }
    content = _post(cfg, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], temperature=0.3, max_tokens=900)
    return content.strip()[:1200]
