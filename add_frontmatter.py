#!/usr/bin/env python3
"""
人民法院案例库 · 添加 YAML Front Matter
========================================

为脱敏后的案例 Markdown 文件添加 YAML 元信息头（front matter）。

数据来源：
  - 原始 JSON（/tmp/rmfyalk_full_cases.json）→ 结构化元数据
  - 脱敏后的 .md 文件 → 脱敏标题 / 正文内容 / 原文链接

用法：
  python3 add_frontmatter.py <目录> [--apply]
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# ---------------------------------------------------------------------------
# 元数据提取
# ---------------------------------------------------------------------------

TYPE_MAP = {"01": "指导性案例", "02": "参考案例", "04": "特色案事例"}
STATUS_MAP = {"01": "有效", "02": "已失效"}


def load_json_index(json_path: str) -> Dict[str, dict]:
    """从原始 JSON 构建 {入库编号: {summary, detail}} 索引。"""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    index: Dict[str, dict] = {}
    for case in data.get("cases", []):
        detail = case.get("detail", {})
        inner = detail.get("data", {}).get("data", {})
        case_no = inner.get("cpws_al_no", "")
        if case_no:
            index[case_no] = {
                "summary": case.get("summary", {}),
                "detail": inner,
            }
    return index


def parse_infos(info_str: str) -> Dict[str, str]:
    """解析 summary.info 字段。

    格式:
      短格式: "case_no / judgment_date / case_docket / 入库日期：entry_date"
      长格式: "case_no / 民事 / 案由 / 法院 / judgment_date / case_docket / 程序 / 入库日期：entry_date"
    """
    parts = [p.strip() for p in info_str.split("/")]
    result: Dict[str, str] = {}

    if len(parts) >= 1:
        # parts[0] is case_no, already have it
        pass
    if len(parts) >= 2:
        result["judgment_date"] = parts[1]
    if len(parts) >= 3:
        docket = parts[2]
        if "入库日期" in docket:
            result["case_docket"] = ""
            result["entry_date"] = docket.replace("入库日期：", "").strip()
            return result
        result["case_docket"] = docket
    if len(parts) >= 7:
        # Long format: parts[0]=no, parts[1]=民事, parts[2]=案由, parts[3]=法院, parts[4]=日期, parts[5]=案号, parts[6+]=程序/入库
        result["case_category"] = parts[1]
        result["cause_of_action"] = parts[2]
        result["court"] = parts[3]
        result["judgment_date"] = parts[4]
        result["case_docket"] = parts[5]

        # Remaining: procedure + 入库日期
        for i in range(6, len(parts)):
            p = parts[i].strip()
            if "入库日期" in p:
                result["entry_date"] = p.replace("入库日期：", "").strip()
            elif p and not result.get("procedure"):
                result["procedure"] = p

    # Also check the last parts for entry_date
    for p in parts:
        if "入库日期" in p:
            result["entry_date"] = p.replace("入库日期：", "").strip()

    return result


def build_frontmatter(
    summary: dict, detail: dict, anonymized_title: str, source_url: str
) -> List[str]:
    """构建 YAML front matter 行列表。"""
    fm: List[str] = ["---"]

    def _add(key: str, value: Any, quote: bool = False):
        if value is None or value == "" or value == []:
            return
        if isinstance(value, str) and ("：" in value or "#" in value or ":" in value):
            quote = True
        if quote and isinstance(value, str):
            fm.append(f'{key}: "{value}"')
        elif isinstance(value, list):
            fm.append(f"{key}:")
            for item in value:
                # Escape YAML special chars in list items
                item_str = str(item).replace('"', '\\"')
                fm.append(f'  - "{item_str}"')
        elif isinstance(value, bool):
            fm.append(f"{key}: {'true' if value else 'false'}")
        else:
            fm.append(f"{key}: {value}")

    # ---------- 基础字段 ----------
    _add("title", anonymized_title, quote=True)

    case_no = detail.get("cpws_al_no", "")
    _add("case_no", case_no)

    case_type_code = detail.get("cpws_al_type", "")
    _add("case_type", TYPE_MAP.get(case_type_code, ""))

    sub = detail.get("cpws_al_sub_title", "")
    _add("subtitle", sub, quote=True)

    # ---------- 从 summary.info 解析 ----------
    info_str = summary.get("info", "")
    parsed = parse_infos(info_str) if info_str else {}

    category = parsed.get("case_category", "")
    _add("case_category", category)

    cause = parsed.get("cause_of_action", "")
    _add("cause_of_action", cause)

    court = parsed.get("court", "")
    _add("court", court)

    jd = parsed.get("judgment_date") or detail.get("cpws_al_zs_date", "")
    _add("judgment_date", jd)

    docket = parsed.get("case_docket") or detail.get("cpws_al_ajzh", "")
    _add("case_docket", docket)

    proc = parsed.get("procedure", "")
    _add("procedure", proc)

    entry = parsed.get("entry_date", "")
    if not entry:
        rk = detail.get("cpws_al_rk_time", "")
        if rk:
            entry = rk.split(" ")[0]
    _add("entry_date", entry)

    # ---------- 关键词 ----------
    keywords = detail.get("cpws_al_keyword", [])
    if keywords:
        _add("keywords", keywords)

    # ---------- 状态 ----------
    status_code = detail.get("cpws_al_status", "")
    _add("status", STATUS_MAP.get(status_code, ""))

    # ---------- 庭室 ----------
    ts = detail.get("cpws_al_ts_name", "")
    if ts:
        ts = ts.strip("（）()")
        _add("trial_division", ts)

    # ---------- 案例ID ----------
    gid = detail.get("cpws_al_id", "")
    _add("case_id", gid)

    # ---------- 来源 ----------
    source_ids = detail.get("cpws_al_source_id", [])
    if source_ids:
        source_map = {
            "0101": "最高人民法院",
            "0302": "公安部",
            "0303": "司法部",
            "0304": "教育部",
            "0305": "民政部",
            "0306": "全国妇联",
            "0307": "共青团中央",
            "0308": "公安部",
            "0309": "国务院妇女儿童工作委员会办公室",
        }
        sources = [source_map.get(s, s) for s in source_ids]
        _add("source", sources)

    # ---------- 原文链接 ----------
    _add("source_url", source_url)

    # ---------- 采集时间 ----------
    _add("collected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    fm.append("---")
    fm.append("")  # blank line between front matter and content
    return fm


# ---------------------------------------------------------------------------
# 文件处理
# ---------------------------------------------------------------------------


def process_file(
    md_file: Path,
    index: Dict[str, dict],
    apply: bool = False,
) -> Optional[str]:
    """处理单个 MD 文件：添加 YAML front matter。

    Returns:
        新文件名（如果标题因脱敏而改名），否则 None
    """
    content = md_file.read_text(encoding="utf-8")
    lines = content.splitlines()

    # 提取入库编号
    case_no = ""
    for line in lines:
        m = re.match(r"\*\*入库编号\*\*[：:]\s*(.+)", line)
        if m:
            case_no = m.group(1).strip()
            break

    if not case_no or case_no not in index:
        print(f"  ⚠️  {md_file.name} — 未找到匹配的元数据 (case_no={case_no})")
        return None

    rec = index[case_no]
    summary = rec["summary"]
    detail = rec["detail"]

    # 脱敏后的标题（H1）
    anon_title = ""
    for line in lines:
        if line.startswith("# "):
            anon_title = line[2:].strip()
            break

    # 原文链接
    source_url = ""
    for line in lines:
        m = re.match(r"\*\*原文链接\*\*[：:]\s*(.+)", line)
        if m:
            source_url = m.group(1).strip()
            break

    # 构建 front matter
    fm_lines = build_frontmatter(summary, detail, anon_title, source_url)

    # 找到正文起始位置（第一个 `## ` 或 `---` 分割线之后）
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            body_start = i + 1
            break
    if body_start == 0:
        # No --- found, find first ##
        for i, line in enumerate(lines):
            if line.startswith("## "):
                body_start = i
                break

    if body_start == 0:
        body_start = 1  # Fallback: skip H1

    # 组合：front matter + 正文
    new_lines = fm_lines + lines[body_start:]
    new_content = "\n".join(new_lines) + "\n"

    if apply:
        md_file.write_text(new_content, encoding="utf-8")

    return anon_title


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

JSON_PATH = "/tmp/rmfyalk_full_cases.json"


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 add_frontmatter.py <目录> [--apply]")
        sys.exit(1)

    dir_path = Path(sys.argv[1]).resolve()
    if not dir_path.is_dir():
        print(f"错误：不是目录 → {dir_path}")
        sys.exit(1)

    apply = "--apply" in sys.argv

    if not Path(JSON_PATH).exists():
        print(f"错误：JSON 数据文件不存在 → {JSON_PATH}")
        print("请先运行采集脚本生成 /tmp/rmfyalk_full_cases.json")
        sys.exit(1)

    print("加载原始元数据...")
    index = load_json_index(JSON_PATH)
    print(f"  已索引 {len(index)} 个案例")

    md_files = sorted(
        [f for f in dir_path.glob("*.md") if not f.name.startswith("_")]
    )
    if not md_files:
        print("目录中没有 .md 文件。")
        sys.exit(1)

    print(f"\n处理 {len(md_files)} 个文件{' (实际写入)' if apply else ' (预览)'}...\n")

    ok = 0
    for f in md_files:
        result = process_file(f, index, apply=apply)
        if result:
            print(f"  ✓ {f.name}")
            ok += 1

    print(f"\n完成！{ok}/{len(md_files)} 个文件。")


if __name__ == "__main__":
    main()
