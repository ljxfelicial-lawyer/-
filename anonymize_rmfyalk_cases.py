#!/usr/bin/env python3
"""
人民法院案例库 · 主体名称脱敏脚本
==================================

从案例 Markdown 的标题 +"以下简称"精确提取当事人名称，全文替换为通用代号。

提取源（高信噪比）：
  1. 案件标题："XX诉YY及ZZ…纠纷案"
  2. "以下简称"构造："全称（以下简称简称）"

保留：法院/检察院名、法条引用、案号、日期、诉讼身份词。

用法：
  python3 anonymize_rmfyalk_cases.py <目录>                # 预览映射表
  python3 anonymize_rmfyalk_cases.py <目录> --apply         # 实际改写
  python3 anonymize_rmfyalk_cases.py <目录> --apply --dry   # 输出 .anonymized.md
"""

import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# 标签
# ---------------------------------------------------------------------------
_TG = list("甲乙丙丁戊己庚辛壬癸")
_DZ = list("子丑寅卯辰巳午未申酉戌亥")


def _co_label(i: int) -> str:
    if i < len(_TG) * len(_DZ):
        return f"{_TG[i // len(_DZ)]}{_DZ[i % len(_DZ)]}公司"
    return f"公司{i + 1}"


def _pe_label(i: int) -> str:
    if i < len(_TG):
        return f"{_TG[i]}某"
    return f"当事人{i + 1}"


# ---------------------------------------------------------------------------
# 公司后缀识别
# ---------------------------------------------------------------------------
_CORP_SUFFIXES = (
    r'有限公司|有限责任公司|股份有限公司|集团有限公司|集团公司?'
    r'|分[公支]公司|[支分]行|分理处|营业部'
    r'|中心(?:（有限合伙）)?'
    r'|(?:律师事务所|会计师事务所|税务师事务所|鉴定所|事务所)'
    r'|[村镇商业人民]?银行|信用联[社合]|信用合作社'
    r'|保险(?:股份有限)?公司|保险'
    r'|(?:连锁)?幼儿园|小学|中学|学校|学院|大学'
    r'|医院|餐(?:饮|厅|吧)|游吧|道馆|乐园'
    r'|物业(?:管理)?(?:有限(?:责任)?公司)?'
    r'|房地产(?:开发)?(?:有限(?:责任)?公司)?'
    r'|酒店|宾馆|旅社|网吧'
    r'|工作室|经营部|服务部|农场|市场'
    r'|协会|学会|基金会|[广播]?电视台'
)

_SUFFIX_RE = re.compile(_CORP_SUFFIXES)


def _is_corp_name(s: str) -> bool:
    """判断字符串是否像一个公司/机构名。"""
    return bool(_SUFFIX_RE.search(s) or re.search(r'[某].{0,4}(?:公司|银行|中心)$', s))


def _is_court(name: str) -> bool:
    """判断是否为法院/检察院名。"""
    return bool(re.search(r'人民(?:法院|检察院)|法院|检察院', name))


# ---------------------------------------------------------------------------
# Step 1：从标题提取当事人
# ---------------------------------------------------------------------------

# 标题模式：原告诉被告及第三人XX纠纷案
_TITLE_RE = re.compile(
    r'^#\s*(.+?)(?:诉|与|及|和)(.+?)(?:纠纷|争议|案|'
    r'民事公益诉讼|民事|刑事|行政|国家赔偿|执行)'
)

# "等"字分隔的当事人列表
_PARTY_SEP_RE = re.compile(r'[、，,及和与]')


def _parse_title(title_line: str) -> List[str]:
    """解析案件标题，提取所有当事人名称。

    例如：
      "甲某诉乙公司及丙某…纠纷案" → ["甲某", "乙公司", "丙某"]
      "某检察院诉某游吧未成年人保护民事公益诉讼案" → ["某检察院", "某游吧"]
    """
    # 去掉 # 前缀
    title = title_line.lstrip("# ").strip()

    # 匹配：原告...（诉/与/及）被告...纠纷案
    # 从右向左找"纠纷案"/"案"
    m = re.match(r'^(.+?)(?:纠纷[一-鿿]*案|争议案|纠纷|民事公益诉讼案|案)$', title)
    if m:
        body = m.group(1)
    else:
        body = title

    # 按"诉"分割 → [原告方, 被告方]
    if '诉' in body:
        parts = body.split('诉', 1)
    else:
        parts = [body]

    # 将每一方按分隔符进一步展开
    entities: List[str] = []
    for part in parts:
        # 拆分"及""与""、"
        sub = re.split(r'[及和与、，,]\s*', part)
        for ent in sub:
            ent = ent.strip()
            if not ent:
                continue
            # 去掉修饰词："原审""被上诉人"等
            ent = re.sub(
                r'^(?:原审|一审|二审|再审)?'
                r'(?:申请再审人|再审申请人|被申请人|上诉人|被上诉人'
                r'|原告|被告|第三人|申请执行人|被执行人|异议人|利害关系人|案外人)?',
                '', ent
            ).strip()
            # 去掉尾部的案由/纠纷类型（如"借款合同纠纷""纠纷""案"等）
            ent = re.sub(
                r'(借款合同|服务合同|买卖合同|侵权|权属|转让|租赁|'
                r'建设施工|建设[一-鿿]*工程|委托|合伙|劳动|劳务|婚姻|'
                r'继承|抚养|赡养|监护|相邻|不当得利|无因管理|证券|保险|'
                r'票据|破产|公司|合伙|知识产权|专利权|商标|著作|不正当竞争|'
                r'名誉|人格|担保|抵押|质押|保证|代位|撤销|确认|变更|'
                r'公益诉讼|代表人诉讼|'
                r')?(纠纷|争议|案|诉讼)$',
                '', ent
            ).strip()
            if ent and '某' in ent:
                # 去掉末尾的"等"字
                ent = ent.rstrip('等')
                entities.append(ent)

    # 过滤检察院（保留但归类为机构）
    # 当事人中的"人民检察院"不脱敏
    return [e for e in entities if not _is_court(e) and len(e) >= 2]


# ---------------------------------------------------------------------------
# Step 2：从"以下简称"提取全称+简称
# ---------------------------------------------------------------------------

# 更精确的正则：全称紧邻"（以下简称"
# 匹配模式：含某的多字名称 + 公司后缀 + "（以下简称"简称"）"
_ALIAS_RE = re.compile(
    r'([一-鿿\d（）()·]{2,18}?某[一-鿿\d（）()·]{1,15}'
    r'(?:' + _CORP_SUFFIXES + r'))'
    r'\s*[（(]以下简称\s*([一-鿿]{2,15})\s*[）)]'
)


def _clean_full_name(raw: str) -> str:
    """剥离前导的连接词、动词、上下文噪音。"""
    # 1) 沿"与/及/和/）/"切开，取最后一段
    for sep in ('及', '与', '和', '）', ')', '、', '。', '；'):
        idx = raw.rfind(sep)
        if idx > 0:
            candidate = raw[idx + 1:].strip()
            if '某' in candidate and len(candidate) >= 4:
                return candidate
    return raw.strip()


def _extract_aliases(text: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """提取"以下简称"构造。

    Returns:
      - name_map: {全称: 出现次数}
      - alias_map: {简称: 全称}
    """
    name_map: Dict[str, int] = {}
    alias_map: Dict[str, str] = {}

    for m in _ALIAS_RE.finditer(text):
        full_name = _clean_full_name(m.group(1))
        alias = m.group(2).strip()

        if 4 <= len(full_name) <= 40 and 2 <= len(alias) <= 15:
            name_map[full_name] = name_map.get(full_name, 0) + 1
            alias_map[alias] = full_name
        # Also add the raw full name if different (for wider coverage)
        raw_full = m.group(1).strip()
        if raw_full != full_name and 4 <= len(raw_full) <= 40:
            name_map[raw_full] = name_map.get(raw_full, 0) + 1

    return name_map, alias_map


# ---------------------------------------------------------------------------
# Step 3：从正文补漏明显遗漏的当事人
# ---------------------------------------------------------------------------

def _find_missing_entities(
    text: str,
    known_names: Set[str],
) -> List[str]:
    """正文中显眼的当事人名称补漏。仅匹配高置信度模式。"""
    result: List[str] = []

    known_alias_values = set()  # We'll collect from alias dict

    strict_re = re.compile(
        r'(?:^|[。，；、：\n（()）\s])'
        r'([一-鿿]{1,12}某[一-鿿]{1,12}'
        r'(?:' + _CORP_SUFFIXES + r'))'
        r'(?:$|[。，；、：\n）)等])'
    )
    for m in strict_re.finditer(text):
        name = m.group(1).strip().lstrip("，。；、：\n\r\t （()")
        # Strip trailing non-name characters (like "等", "纠纷", "合同", etc.)
        name = re.sub(r'[等纠纷合同争议]$', '', name).strip()
        if name in known_names:
            continue
        if any(name in k for k in known_names if k != name):
            continue
        if 4 <= len(name) <= 35 and '某' in name:
            result.append(name)

    return result


def _find_person_names(
    text: str,
    known_names: Set[str],
) -> List[str]:
    """从正文中补漏遗漏的人名。

    边界：名称为 2-3 个汉字含某，左边是标点/句首/连接词，右边是标点/句尾/连接词/虚词。
    """
    result: List[str] = []
    # 边界：中文标点、句首、连接词
    person_re = re.compile(
        r'(?:^|[。，；、：\n（）\s]'
        r'|诉|与|及|和|对|向|被|以|将|在|从|因|就|故|由|经)'
        r'([一-鿿]{1}某[一-鿿]{0,1})'
        r'(?=[。，；、：\n（）\s]'
        r'|$'
        r'|诉|与|及|和|对|向|被|以|将|在|从|因|就|故|由|经'
        r'|之|的|等|系|属|未|不|无|有|应|已|亦|均|也|即|又|但|而|还|便|再|则'
        r'|为|作|提|主|请|申|辩|认|偿|付|赔|履|担'
        r'|驾|签|出|购|售|同|拒|返|交|登|销|变|确'
        r'|讲|记|称|道|说|指|知|明)'
    )
    for m in person_re.finditer(text):
        name = m.group(1).strip()
        if len(name) < 2:
            continue
        if re.search(r'(?:公司|银行|中心|保险|法院|检察院|政府)', name):
            continue
        if name in known_names:
            continue
        result.append(name)
    return result


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def build_all_mappings(
    md_files: List[Path],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """构建 (公司映射, 个人映射)。"""
    all_cos: Dict[str, int] = {}
    all_pers: Dict[str, int] = {}
    global_alias: Dict[str, str] = {}

    for md_file in sorted(md_files):
        text = md_file.read_text(encoding="utf-8")

        # 1) 标题
        lines = text.splitlines()
        for line in lines:
            if line.startswith("# ") and '某' in line:
                entities = _parse_title(line)
                for ent in entities:
                    if _is_corp_name(ent):
                        all_cos[ent] = all_cos.get(ent, 0) + 1
                    elif 2 <= len(ent) <= 5:
                        all_pers[ent] = all_pers.get(ent, 0) + 1

        # 2) 以下简称
        name_map, alias_map = _extract_aliases(text)
        for n, c in name_map.items():
            all_cos[n] = all_cos.get(n, 0) + c
        global_alias.update(alias_map)

        # 3) 补漏——公司
        known = set(all_cos.keys()) | set(all_pers.keys()) | set(global_alias.keys())
        missing_cos = _find_missing_entities(text, known)
        for n in missing_cos:
            all_cos[n] = all_cos.get(n, 0) + 1

        # 4) 补漏——人名（正文中显眼的人名）
        known2 = set(all_cos.keys()) | set(all_pers.keys()) | set(global_alias.keys())
        missing_pers = _find_person_names(text, known2)
        for n in missing_pers:
            all_pers[n] = all_pers.get(n, 0) + 1

    # 过滤单次出现的短名 & 长度上限（排除把整句当公司名的噪音）
    cos_f: Dict[str, int] = {}
    for n, c in all_cos.items():
        if len(n) > 25:       # 超过 25 字的肯定不是单独实体名
            continue
        if c >= 2 or len(n) >= 8:
            cos_f[n] = c

    pers_f: Dict[str, int] = {}
    # 只在短公司名中检查子串冲突（长公司名通常是噪音合并体）
    short_cos = {cn for cn in cos_f if len(cn) <= 15}
    for n, c in all_pers.items():
        if any(n in cn and n != cn for cn in short_cos):
            continue
        pers_f[n] = c

    # 标签
    co_items = sorted(cos_f.items(), key=lambda x: (-x[1], -len(x[0])))
    pe_items = sorted(pers_f.items(), key=lambda x: (-x[1], -len(x[0])))

    co_map = {name: _co_label(i) for i, (name, _) in enumerate(co_items)}
    pe_map = {name: _pe_label(i) for i, (name, _) in enumerate(pe_items)}

    # 简称继承
    for alias, full in global_alias.items():
        if full in co_map and alias not in co_map:
            co_map[alias] = co_map[full]

    return co_map, pe_map


# ---------------------------------------------------------------------------
# 替换
# ---------------------------------------------------------------------------

def apply_map(text: str, mapping: Dict[str, str]) -> str:
    for name in sorted(mapping.keys(), key=len, reverse=True):
        text = text.replace(name, mapping[name])
    return text


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 anonymize_rmfyalk_cases.py <目录> [--apply] [--dry]")
        sys.exit(1)

    dp = Path(sys.argv[1]).resolve()
    if not dp.is_dir():
        print(f"错误：不是目录 → {dp}")
        sys.exit(1)

    apply = "--apply" in sys.argv
    dry = "--dry" in sys.argv

    files = sorted(dp.glob("*.md"))
    if not files:
        print("无 .md 文件。")
        sys.exit(1)

    print(f"解析 {len(files)} 个文件（标题 + 以下简称）...")
    co_map, pe_map = build_all_mappings(files)
    full_map = {**co_map, **pe_map}

    def _show(title, mp):
        if not mp:
            return
        print(f"\n{'─' * 60}")
        print(f"【{title} · {len(mp)} 个】")
        print(f"{'─' * 60}")
        for orig, label in sorted(mp.items(), key=lambda x: x[1]):
            print(f"  {orig:<45} → {label}")

    _show("公司 / 机构", co_map)
    _show("自然人", pe_map)

    print(f"\n{'=' * 60}")
    print(f"共 {len(full_map)} 个主体将被替换")

    if not apply:
        print("\n预览模式 — 未执行。加 --apply 执行。")
        return

    print(f"\n执行脱敏...")
    changed = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        new_text = apply_map(text, full_map)
        if new_text == text:
            continue
        out = f.parent / (f.stem + ".anonymized.md") if dry else f
        out.write_text(new_text, encoding="utf-8")
        changed += 1
        print(f"  {'→' if dry else '✓'} {f.name}")

    print(f"\n完成！{changed}/{len(files)} 个文件。")

    map_path = dp / "_anonymize_map.txt"
    with open(map_path, "w", encoding="utf-8") as mf:
        for orig, label in sorted(full_map.items(), key=lambda x: (x[1], -len(x[0]))):
            mf.write(f"{label} ← {orig}\n")
    print(f"映射表: {map_path}")


if __name__ == "__main__":
    main()
