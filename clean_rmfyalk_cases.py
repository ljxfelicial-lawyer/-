#!/usr/bin/env python3
"""
人民法院案例库 Markdown 清洗脚本
=================================

清洗从 rmfyalk API 采集并转换的案例 Markdown 文件中的常见噪音：
  - 庭室信息重复括号：*（（XXX））* → *（XXX）*
  - 关联索引/底部区域过度全角空格缩进（4→2）
  - 连续 3 个以上空行 → 2 个空行
  - 全文末尾多余空白行
  - 残留的零宽字符 / HTML 实体

用法：
  python3 clean_rmfyalk_cases.py <目录路径>
  python3 clean_rmfyalk_cases.py <目录路径> --apply   # 实际写入（默认仅预览）
"""

import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 清洗规则
# ---------------------------------------------------------------------------


def clean_double_parens(text: str) -> str:
    """修复庭室信息中的括号嵌套：*（（民一庭））* → *（民一庭）*"""
    return re.sub(r"\*（（([^）]+)））\*", r"*（\1）*", text)


def clean_excessive_fullwidth_indent(text: str) -> str:
    """将行首 4 个以上全角空格缩减为 2 个。"""
    # 匹配行首 4+ 全角空格
    return re.sub(r"^(　){4,}", "　　　", text, flags=re.MULTILINE)


def normalize_blank_lines(text: str) -> str:
    """连续 3 个以上空行 → 2 个空行。"""
    return re.sub(r"\n{3,}", "\n\n", text)


def strip_trailing_blank_lines(text: str) -> str:
    """去除文件末尾多余的空白行（保留末尾恰好 1 个空行）。"""
    text = text.rstrip("\n")
    if text:
        text += "\n"
    return text


def remove_zero_width_chars(text: str) -> str:
    """删除零宽字符、BOM、软连字符等隐形噪音。"""
    text = text.replace("﻿", "")  # BOM
    text = text.replace("​", "")  # 零宽空格
    text = text.replace("‌", "")  # 零宽非连接符
    text = text.replace("‍", "")  # 零宽连接符
    text = text.replace("­", "")  # 软连字符
    text = text.replace("‎", "")  # LRM
    text = text.replace("‏", "")  # RLM
    return text


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """应用所有清洗规则。"""
    text = remove_zero_width_chars(text)
    text = clean_double_parens(text)
    text = clean_excessive_fullwidth_indent(text)
    text = normalize_blank_lines(text)
    text = strip_trailing_blank_lines(text)
    return text


def clean_directory(dir_path: Path, apply: bool = False) -> None:
    """清洗目录下所有 .md 文件。"""
    md_files = sorted(dir_path.glob("*.md"))
    if not md_files:
        print(f"目录中没有 .md 文件：{dir_path}")
        return

    print(f"目标目录: {dir_path}")
    print(f"文件数量: {len(md_files)}")
    print(f"模式: {'实际改写' if apply else '预览模式（不写入）'}")
    print()

    total_changes = 0
    for md_file in md_files:
        original = md_file.read_text(encoding="utf-8")
        cleaned = clean_text(original)

        if cleaned == original:
            continue

        total_changes += 1
        # 统计差异行数
        orig_lines = original.splitlines()
        clean_lines = cleaned.splitlines()
        diff = len(orig_lines) - len(clean_lines)

        print(f"  清洗: {md_file.name}")
        if diff != 0:
            print(f"        行数: {len(orig_lines)} → {len(clean_lines)}（{diff:+d}）")

        if apply:
            md_file.write_text(cleaned, encoding="utf-8")

    if total_changes == 0:
        print("所有文件已干净，无需清洗。")
    elif apply:
        print(f"\n已改写 {total_changes} 个文件。")
    else:
        print(f"\n共 {total_changes} 个文件需要清洗。")
        print("加上 --apply 参数执行实际改写。")


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 clean_rmfyalk_cases.py <目录> [--apply]")
        sys.exit(1)

    dir_path = Path(sys.argv[1]).resolve()
    apply = "--apply" in sys.argv

    if not dir_path.is_dir():
        print(f"错误：不是有效目录 → {dir_path}")
        sys.exit(1)

    clean_directory(dir_path, apply=apply)


if __name__ == "__main__":
    main()
