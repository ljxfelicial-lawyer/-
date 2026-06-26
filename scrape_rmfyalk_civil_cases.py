#!/usr/bin/env python3
"""
人民法院案例库 · 民事案例数据采集脚本
=========================================

采集 https://rmfyalk.court.gov.cn 中民事案例（含指导性案例和参考案例）的完整数据。

使用前准备：
  1. 在浏览器中登录 https://rmfyalk.court.gov.cn/
  2. 按 F12 打开开发者工具 → Application → Cookies → rmfyalk.court.gov.cn
  3. 找到名为 SESSION 的 Cookie，复制其值
  4. 在同目录下创建 cookies.txt，第一行写入 SESSION=<你复制的值>

  或者设置环境变量：
    export RMFYALK_SESSION="<SESSION值>"

用法：
  python3 scrape_rmfyalk_civil_cases.py           # 增量更新
  python3 scrape_rmfyalk_civil_cases.py --full     # 全量重新抓取
  python3 scrape_rmfyalk_civil_cases.py --test     # 测试模式（仅抓取前2页）

输出目录：
  知识库/案例库资源/人民法院案例库-民事（自动）/
"""

import os
import random
import re
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BASE_URL = "https://rmfyalk.court.gov.cn"
SEARCH_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/search"
CONTENT_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/content"
INDEX_API = f"{BASE_URL}/cpws_al_api/api/cpwsAl/indexTongji"

# 输出目录：知识库/案例库资源/人民法院案例库-民事（自动）
KB_ROOT = Path("/Users/ljx/Library/Mobile Documents/com~apple~CloudDocs/Documents/知识库")
OUT_ROOT = KB_ROOT / "案例库资源" / "人民法院案例库-民事（自动）"

# Cookie 文件路径（与脚本同目录）
COOKIE_FILE = Path(__file__).resolve().parent / "cookies.txt"

# 请求间隔（秒），避免对服务器造成压力
REQUEST_DELAY_BASE = 0.3


def request_delay() -> None:
    """随机抖动延迟，避免被反爬。"""
    time.sleep(REQUEST_DELAY_BASE + random.uniform(0, 0.15))

# 每页抓取条数（最大 50）
PAGE_SIZE = 50

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """清洗文本：合并空白字符、去除首尾空格。"""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def sanitize_filename(name: str) -> str:
    """生成安全的文件名。"""
    name = clean_text(name)
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:120].strip(" ._") or "untitled"


def html_to_markdown(html: str) -> str:
    """将 HTML 正文转换为 Markdown。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style"):
        tag.decompose()
    text = md(str(soup), heading_style="ATX").strip()
    text = text.replace("\\\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def parse_time(text: str) -> datetime | None:
    """解析时间字符串。"""
    if not text:
        return None
    normalized = text.replace("/", "-").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y年%m月%d日",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    match = re.search(r"(\d{4}-\d{2}-\d{2})", normalized)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def format_time_for_filename(text: str) -> str:
    """为文件名格式化时间。"""
    dt = parse_time(text)
    if dt:
        return dt.strftime("%Y-%m-%d_%H%M%S")
    return "unknown_time"


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


def load_session() -> str:
    """加载 SESSION Cookie。

    优先级：环境变量 RMFYALK_SESSION > cookies.txt 文件。
    """
    # 1) 环境变量
    session = os.environ.get("RMFYALK_SESSION", "").strip()
    if session:
        print("[认证] 使用环境变量 RMFYALK_SESSION")
        return session

    # 2) cookies.txt 文件
    if COOKIE_FILE.exists():
        for line in COOKIE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                if key.strip().upper() == "SESSION":
                    session = value.strip()
                    if session:
                        print(f"[认证] 使用 Cookie 文件: {COOKIE_FILE}")
                        return session
            else:
                # 整行就是值
                print(f"[认证] 使用 Cookie 文件（整行值）: {COOKIE_FILE}")
                return line

    print("[认证] 未找到 SESSION Cookie，尝试无认证访问...")
    return ""


def create_session(session_value: str) -> requests.Session:
    """创建带认证的 requests Session。"""
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Referer": f"{BASE_URL}/view/list.html",
            "Origin": BASE_URL,
        }
    )
    if session_value:
        s.cookies.set("SESSION", session_value, domain="rmfyalk.court.gov.cn")
    return s


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------


def api_search(
    session: requests.Session,
    page: int = 1,
    size: int = PAGE_SIZE,
    case_type: str = "02",  # 02 = 民事
    lib: str = "cpwsAl_qb",
    sort_field: str = "",
    max_retries: int = 3,
) -> dict:
    """调用搜索 API，返回原始 JSON。"""
    payload = {
        "page": page,
        "size": size,
        "lib": "qb",
        "searchParams": {
            "userSearchType": 1,
            "isAdvSearch": "2",
            "selectValue": "qw",
            "lib": lib,
            "sort_field": sort_field,
            "case_sort_id_cpwsAl": case_type,
        },
    }
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.post(SEARCH_API, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = 2 ** attempt + random.uniform(0, 1)
                print(f"    [重试] 搜索 API 第 {attempt + 1} 次失败，{wait:.1f}s 后重试: {exc}")
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def api_content(
    session: requests.Session, gid: str, max_retries: int = 3
) -> dict:
    """调用内容 API，返回原始 JSON。"""
    payload = {"gid": gid}
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = session.post(CONTENT_API, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = 2 ** attempt + random.uniform(0, 1)
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def parse_search_response(data: dict) -> tuple[list[dict], int]:
    """解析搜索 API 响应，返回 (案例摘要列表, 总条数)。"""
    if data.get("code") != "0":
        msg = data.get("msg", "未知错误")
        if data.get("code") == 401:
            raise PermissionError(
                "认证失败（401）。请确认 SESSION Cookie 有效。\n"
                "获取方法：浏览器登录 rmfyalk.court.gov.cn 后，\n"
                "在开发者工具 → Application → Cookies 中查找 SESSION 值。"
            )
        raise RuntimeError(f"搜索 API 返回错误 (code={data.get('code')}): {msg}")

    items = data.get("data", {}).get("datas", [])
    total = int(data.get("data", {}).get("totalCount", 0))
    return items, total


def parse_content_response(data: dict) -> dict | None:
    """解析内容 API 响应，返回案例详情 dict。"""
    if data.get("code") != "0":
        msg = data.get("msg", "未知错误")
        if data.get("code") == 401:
            raise PermissionError("认证失败（401）。请确认 SESSION Cookie 有效。")
        print(f"    [警告] 内容 API 返回错误: {msg}")
        return None

    return data.get("data", {}).get("data")


# ---------------------------------------------------------------------------
# Markdown 生成
# ---------------------------------------------------------------------------


# 案例正文模块：按案例类型和分类组织的字段映射
# 参考 content.js 中的 modeulNameArray 逻辑
SECTION_RULES = [
    # (条件字段, 条件值匹配, 标题, 字段key)
    # --- 指导性案例 ---
    ("cpws_al_type", "01", "裁判要点", "cpws_al_cpyz"),
    ("cpws_al_type", "01", "基本案情", "cpws_al_jbaq"),
    ("cpws_al_type", "01", "裁判结果", "cpws_al_cpjg"),
    ("cpws_al_type", "01", "裁判理由", "cpws_al_cply"),
    ("cpws_al_type", "01", "相关法条", "cpws_al_glsy"),
    # --- 参考案例（默认） ---
    ("cpws_al_type", "02", "基本案情", "cpws_al_jbaq"),
    ("cpws_al_type", "02", "裁判理由", "cpws_al_cply"),
    ("cpws_al_type", "02", "裁判要旨", "cpws_al_cpyz"),
    ("cpws_al_type", "02", "关联索引", "cpws_al_glsy"),
]


def resolve_sections(content: dict) -> list[tuple[str, str]]:
    """根据案例类型和分类，确定正文各模块的标题和顺序。

    参考 content.js 中的 switch/case 逻辑：
    - 民事执行案件（A0501）：基本案情→执行理由→执行要旨/执行实施要点→关联索引
    - 民事调解案件（A06） ：基本案情→调解结果→调解指引→案例价值→关联索引
    - 普通民事参考案例    ：基本案情→裁判理由→裁判要旨→关联索引
    - 民事指导性案例       ：裁判要点→基本案情→裁判结果→裁判理由→相关法条

    Returns:
        list of (section_title, field_key)
    """
    case_type = content.get("cpws_al_type", "")
    sort_ids = content.get("cpws_al_case_sort_id", [])
    sort_id_str = ",".join(sort_ids) if isinstance(sort_ids, list) else str(sort_ids or "")

    # 指导性案例
    if case_type == "01":
        if "A0501" in sort_id_str:
            return [
                ("执行实施要点", "cpws_al_cpyz"),
                ("基本案情", "cpws_al_jbaq"),
                ("执行结果", "cpws_al_cpjg"),
                ("执行理由", "cpws_al_cply"),
                ("相关法条", "cpws_al_glsy"),
            ]
        return [
            ("裁判要点", "cpws_al_cpyz"),
            ("基本案情", "cpws_al_jbaq"),
            ("裁判结果", "cpws_al_cpjg"),
            ("裁判理由", "cpws_al_cply"),
            ("相关法条", "cpws_al_glsy"),
        ]

    # 参考案例（默认 case_type == "02"）
    if "A0501" in sort_id_str:
        # 执行案件
        return [
            ("基本案情", "cpws_al_jbaq"),
            ("执行理由", "cpws_al_cply"),
            ("执行要旨", "cpws_al_cpyz"),
            ("关联索引", "cpws_al_glsy"),
        ]
    if "A06" in sort_id_str:
        # 调解案件
        return [
            ("基本案情", "cpws_al_jbaq"),
            ("调解结果", "cpws_al_cply"),
            ("调解指引", "cpws_al_cpyz"),
            ("案例价值", "cpws_al_aljz"),
            ("关联索引", "cpws_al_glsy"),
        ]

    # 默认参考案例
    return [
        ("基本案情", "cpws_al_jbaq"),
        ("裁判理由", "cpws_al_cply"),
        ("裁判要旨", "cpws_al_cpyz"),
        ("关联索引", "cpws_al_glsy"),
    ]


def build_markdown(case_summary: dict, detail: dict | None) -> str:
    """构建案例 Markdown 文本。

    Args:
        case_summary: 来自搜索 API 的摘要数据
        detail: 来自内容 API 的详情数据，如为 None 则仅输出摘要信息
    """
    gid = case_summary.get("id", "unknown")
    title = case_summary.get("cpws_al_title", "无标题")
    if detail:
        title = detail.get("cpws_al_title") or title

    lines: list[str] = []

    # 标题
    lines.append(f"# {title}")
    lines.append("")

    # 类型标签
    case_type = ""
    if detail:
        case_type = detail.get("cpws_al_type", "")
    if not case_type:
        case_type = case_summary.get("cpws_al_type", "")

    type_label = {
        "01": "指导性案例",
        "02": "参考案例",
        "04": "特色案事例",
    }.get(case_type, f"类型{case_type}")
    lines.append(f"**案例类型**：{type_label}")
    lines.append("")

    # 入库编号
    if detail and detail.get("cpws_al_no"):
        lines.append(f"**入库编号**：{detail['cpws_al_no']}")
        lines.append("")

    # 副标题
    if detail and detail.get("cpws_al_sub_title"):
        lines.append(f"**副标题**：{detail['cpws_al_sub_title']}")
        lines.append("")

    # 案例ID
    lines.append(f"**案例ID**：{gid}")
    lines.append("")

    # 摘要信息（搜索 API 的 cpws_al_infos 字段通常含法院/案号/裁判日期等）
    infos = case_summary.get("cpws_al_infos", "")
    if infos:
        lines.append(f"**案件信息**：{infos}")
        lines.append("")

    # 状态
    if case_summary.get("cpws_al_status") == "02":
        lines.append("> ⚠️ 该案例已失效")
        lines.append("")

    # 关键词
    if detail:
        keywords = detail.get("cpws_al_keyword", [])
        if keywords:
            kw_str = "　".join(keywords) if isinstance(keywords, list) else str(keywords)
            lines.append(f"**关键词**：{kw_str}")
            lines.append("")

    # 原文链接
    lib_code = "ck" if case_type == "02" else "zdx"
    detail_url = f"{BASE_URL}/view/content.html?id={gid}&lib={lib_code}"
    lines.append(f"**原文链接**：{detail_url}")
    lines.append("")

    # 修改时间
    if detail and detail.get("cpws_al_update_time"):
        lines.append(f"**文本调整时间**：{detail['cpws_al_update_time']}")
        lines.append("")

    # ---------------------------------------------------------------
    # 正文
    # ---------------------------------------------------------------
    if detail:
        lines.append("---")
        lines.append("")

        sections = resolve_sections(detail)
        for sec_title, field_key in sections:
            raw_html = detail.get(field_key, "")
            if raw_html:
                markdown_body = html_to_markdown(raw_html)
                lines.append(f"## {sec_title}")
                lines.append("")
                lines.append(markdown_body)
                lines.append("")

        # 庭室信息
        if detail.get("cpws_al_ts_name"):
            lines.append(f"*（{detail['cpws_al_ts_name']}）*")
            lines.append("")

        # 指导性案例文本提示
        if case_type == "01":
            lines.append("*（此系指导性案例发布时的文本）*")
            lines.append("")

    else:
        # 仅摘要（无详情时，显示列表页的裁判要点摘要）
        cpyz = case_summary.get("cpws_al_cpyz", "")
        if cpyz:
            lines.append("## 裁判要旨（摘要）")
            lines.append("")
            lines.append(html_to_markdown(cpyz))
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 状态管理（增量更新）
# ---------------------------------------------------------------------------


def load_existing_state(out_dir: Path) -> set[str]:
    """扫描输出目录，返回已保存的案例 ID 集合。"""
    existing: set[str] = set()
    if not out_dir.exists():
        return existing

    for md_file in out_dir.glob("*.md"):
        try:
            content_text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # 匹配 "**案例ID**：xxx"
        match = re.search(r"\*\*案例ID\*\*[：:]\s*(\S+)", content_text)
        if match:
            existing.add(match.group(1))
            continue

        # fallback: 从文件名提取（老格式）
        file_match = re.match(r"^[^_]+_[^_]+_(.+?)\.md$", md_file.name)
        if file_match:
            # 文件名中含 gid
            pass

    return existing


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="人民法院案例库 · 民事案例数据采集"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量重新抓取（覆盖已有文件）",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="测试模式：仅抓取前 2 页",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=PAGE_SIZE,
        help=f"每页条数（默认 {PAGE_SIZE}，最大 50）",
    )
    args = parser.parse_args()

    # --- 认证 ---
    session_value = load_session()
    if not session_value:
        print(
            "[警告] 未设置 SESSION Cookie，数据 API 可能返回 401。\n"
            "请按以下步骤获取 Cookie：\n"
            "  1. 在浏览器中登录 https://rmfyalk.court.gov.cn/\n"
            "  2. F12 → Application → Cookies → 找到 SESSION\n"
            "  3. 在脚本同目录创建 cookies.txt，写入 SESSION=<值>\n"
            "  或者: export RMFYALK_SESSION='<值>'"
        )

    session = create_session(session_value)
    page_size = min(args.size, 50)

    # --- 输出目录 ---
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # --- 读取已保存状态 ---
    existing_ids: set[str] = set()
    if not args.full:
        existing_ids = load_existing_state(OUT_ROOT)
        if existing_ids:
            print(f"[增量更新] 已有案例: {len(existing_ids)} 篇")
        else:
            print("[全量更新] 未发现已有数据，将从头开始抓取")
    else:
        print("[全量更新] --full 模式，将覆盖已有数据")

    # --- 测试连通性 ---
    print("[初始化] 检查 API 连通性...")
    try:
        index_data = session.post(INDEX_API, json={}, timeout=30).json()
        if index_data.get("code") == 0:
            total_all = index_data["data"]["allCount"]
            print(f"[初始化] 人民法院案例库共收录案例 {total_all} 篇")
    except Exception as exc:
        print(f"[初始化] 统计 API 调用失败: {exc}")

    # --- 首次搜索，获取总页数 ---
    print("[初始化] 搜索民事案例...")
    try:
        data = api_search(session, page=1, size=page_size)
        items, total = parse_search_response(data)
    except PermissionError as exc:
        print(f"\n{'=' * 60}")
        print(f" 认证失败！{exc}")
        print(f"{'=' * 60}")
        sys.exit(1)
    except Exception as exc:
        print(f"[错误] 搜索 API 请求失败: {exc}")
        sys.exit(1)

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    print(f"[初始化] 民事案例共 {total} 篇，{total_pages} 页（每页 {page_size} 条）")

    if args.test:
        total_pages = min(total_pages, 2)
        print(f"[测试] 仅抓取前 {total_pages} 页")

    # --- 逐页抓取 ---
    total_new = 0
    total_skipped = 0
    total_failed = 0
    stopped_early = False

    for page in range(1, total_pages + 1):
        if page > 1:
            try:
                data = api_search(session, page=page, size=page_size)
                items, _ = parse_search_response(data)
            except Exception as exc:
                print(f"[错误] 第 {page} 页搜索失败: {exc}")
                break
        # page=1 的 items 已在上面获取

        if not items:
            print(f"[停止] 第 {page} 页无数据")
            break

        print(f"\n[分页] 第 {page}/{total_pages} 页，共 {len(items)} 条")
        page_new = 0
        page_existing = 0

        for index, item in enumerate(items, start=1):
            gid = item.get("id", "")
            if not gid:
                print(f"  [{index}/{len(items)}] 跳过（无 ID）")
                continue

            # 增量模式：跳过已有
            if not args.full and gid in existing_ids:
                page_existing += 1
                total_skipped += 1
                continue

            # 获取详情
            detail = None
            try:
                content_data = api_content(session, gid)
                detail = parse_content_response(content_data)
            except PermissionError:
                print(f"\n[认证失效] Session 中途失效，请重新登录获取 Cookie")
                stopped_early = True
                break
            except Exception as exc:
                print(f"  [{index}/{len(items)}] 详情获取失败: {gid} ({exc})")
                # 即使详情失败，也尝试用摘要数据保存
                pass

            # 生成 Markdown
            markdown_text = build_markdown(item, detail)

            # 确定文件名
            title = detail.get("cpws_al_title", "") if detail else item.get("cpws_al_title", "")
            time_str = detail.get("cpws_al_update_time", "") if detail else ""
            file_time = format_time_for_filename(time_str) if time_str else "unknown_time"
            safe_title = sanitize_filename(title) if title else gid
            file_name = f"{file_time}_{gid}_{safe_title}.md"
            out_path = OUT_ROOT / file_name

            # 处理重名
            counter = 1
            while out_path.exists():
                existing_text = out_path.read_text(encoding="utf-8")
                if f"**案例ID**：{gid}" in existing_text:
                    # 同一个案例，跳过
                    break
                out_path = OUT_ROOT / f"{file_time}_{gid}_{safe_title}_{counter}.md"
                counter += 1
            else:
                out_path.write_text(markdown_text, encoding="utf-8")
                existing_ids.add(gid)
                total_new += 1
                page_new += 1
                print(f"  [{index}/{len(items)}] 新增: {out_path.name}")
                request_delay()
                continue

            # 重名且同一案例
            existing_ids.add(gid)
            page_existing += 1
            total_skipped += 1

        if stopped_early:
            break

        page_failed_detail = len(items) - page_new - page_existing
        total_failed += page_failed_detail

        # 如果整页都是已有案例，并且不是全量模式，停止增量更新
        if page_new == 0 and page_existing == len(items) and not args.full:
            print(f"[停止] 第 {page} 页案例均已存在，结束增量更新")
            break

    # --- 汇总 ---
    print(f"\n{'=' * 60}")
    print("完成！")
    print(f"  - 新增保存: {total_new} 篇")
    if total_skipped:
        print(f"  - 跳过已存在: {total_skipped} 篇")
    if total_failed:
        print(f"  - 失败: {total_failed} 篇")
    print(f"  - 数据目录: {OUT_ROOT.resolve()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
