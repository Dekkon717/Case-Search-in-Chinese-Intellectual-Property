"""用公开判决数据集和最高人民法院典型案例名单扩充知识产权案例库。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import time
import urllib.request
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PDF_START = re.compile(r"(?m)^\s*(\d{1,3})\s*[（(]((?:19|20)\d{2})[）)]")
CASE_NUMBER = re.compile(
    r"[（(〔\[]\s*((?:19|20)\d{2})\s*[）)〕\]]\s*[^，,；;。\n]{0,90}?号"
)
ENTRY_NUMBER = re.compile(r"^\s*(\d{1,2})\s*[.．、]\s*(.+)$")
HEADING = re.compile(r"^(?:[一二三四五六七八九十]+[、.]|[（(][一二三四五六七八九十]+[）)])")
PLACEHOLDER_NUMBER = ("待", "未载明", "不详", "无案号")


class PageTextParser(HTMLParser):
    """把网页正文转成保留段落边界的纯文本行。"""

    BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.parts: list[str] = []
        self.skip_depth = 0

    def flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.parts)).strip()
        if text:
            self.lines.append(text)
        self.parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in self.BLOCK_TAGS:
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def close(self) -> None:
        super().close()
        self.flush()


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \n\t\uf0b7")


def normalize_case_number(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    value = value.replace("(", "（").replace(")", "）")
    value = value.replace("〔", "（").replace("〕", "）")
    value = value.replace("[", "（").replace("]", "）")
    return value


def number_keys(value: str) -> set[str]:
    value = compact(value)
    if not value or value.startswith(PLACEHOLDER_NUMBER):
        return set()
    matches = CASE_NUMBER.findall(value)
    if matches:
        result: set[str] = set()
        for match in CASE_NUMBER.finditer(value):
            result.add(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", normalize_case_number(match.group(0))))
        return result
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value)
    return {normalized} if len(normalized) >= 8 else set()


def title_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).lower()


def category_for(text: str) -> str:
    if "商业秘密" in text or "技术秘密" in text:
        return "商业秘密"
    if "植物新品种" in text or "品种权" in text:
        return "植物新品种"
    if "集成电路布图" in text:
        return "专利"
    if "商标" in text or "注册商标" in text:
        if "不正当竞争" in text:
            return "商标及不正当竞争"
        return "商标"
    if any(word in text for word in ("著作权", "版权", "作品放映权", "信息网络传播权", "复制权", "发行权")):
        return "著作权"
    if any(word in text for word in ("专利", "实用新型", "外观设计", "职务发明")):
        return "专利"
    if any(word in text for word in (
        "不正当竞争", "商业诋毁", "虚假宣传", "包装装潢", "知名商品", "垄断",
        "拒绝交易", "市场支配地位", "经营者集中", "横向协议", "纵向协议",
    )):
        return "不正当竞争"
    return "其他知识产权"


def cause_for(category: str, text: str) -> str:
    specific = (
        ("拒绝交易", "拒绝交易纠纷"),
        ("商业诋毁", "商业诋毁纠纷"),
        ("虚假宣传", "虚假宣传纠纷"),
        ("市场支配地位", "滥用市场支配地位纠纷"),
        ("横向垄断协议", "横向垄断协议纠纷"),
        ("纵向垄断协议", "纵向垄断协议纠纷"),
        ("技术秘密", "侵害技术秘密纠纷"),
        ("商业秘密", "侵害商业秘密纠纷"),
        ("植物新品种", "侵害植物新品种权纠纷"),
        ("信息网络传播权", "侵害作品信息网络传播权纠纷"),
        ("计算机软件著作权", "侵害计算机软件著作权纠纷"),
        ("外观设计专利", "侵害外观设计专利权纠纷"),
        ("发明专利", "侵害发明专利权纠纷"),
        ("实用新型专利", "侵害实用新型专利权纠纷"),
    )
    for keyword, cause in specific:
        if keyword in text:
            return cause
    return {
        "商标": "侵害商标权纠纷",
        "商标及不正当竞争": "侵害商标权及不正当竞争纠纷",
        "著作权": "著作权权属、侵权纠纷",
        "专利": "专利权权属、侵权纠纷",
        "不正当竞争": "不正当竞争纠纷",
        "商业秘密": "侵害商业秘密纠纷",
        "植物新品种": "侵害植物新品种权纠纷",
    }.get(category, "其他知识产权纠纷")


def procedure_for(text: str) -> str:
    if any(word in text for word in ("再审", "提审", "申请再审")):
        return "再审"
    if any(word in text for word in ("二审", "上诉")):
        return "二审"
    if "一审" in text:
        return "一审"
    return "待核实"


def province_for(court: str, region: str = "") -> str:
    if region:
        return region if region.endswith(("省", "市", "自治区")) else region + "省"
    mapping = {
        "北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市",
        "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
        "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
        "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
        "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
        "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
        "甘肃": "甘肃省", "青海": "青海省", "广西": "广西壮族自治区",
        "内蒙古": "内蒙古自治区", "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
        "西藏": "西藏自治区",
    }
    for key, value in mapping.items():
        if key in court:
            return value
    return "全国"


def court_level_for(court: str) -> str:
    if "最高人民法院" in court:
        return "最高"
    if "高级人民法院" in court:
        return "高级"
    if "中级人民法院" in court or "知识产权法院" in court:
        return "中级/专门法院"
    if "人民法院" in court:
        return "基层"
    return "待核实"


def exact_date_from_pdf(text: str) -> str:
    match = re.search(r"裁判日期[:：]\s*((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not match:
        return "1900-01-01"
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return "1900-01-01"


def extract_field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}[:：]\s*([^\n]+)", text)
    return compact(match.group(1)) if match else ""


def find_court(text: str) -> str:
    candidates = re.findall(r"(?m)^\s*([^\n，。；:：]{2,38}(?:人民法院|知识产权法院))\s*$", text)
    candidates = [compact(item) for item in candidates if len(compact(item)) <= 38]
    return candidates[0] if candidates else "待从裁判文书原文核验"


def extract_pdf_cases(pdf_path: Path, source: dict[str, Any], obtained: str) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf，请使用 Codex 工作区自带 Python 运行本脚本") from exc

    reader = PdfReader(str(pdf_path))
    raw_cases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        start = PDF_START.search(text)
        if start:
            if current:
                current["end_page"] = page_index - 1
                raw_cases.append(current)
            current = {
                "index": int(start.group(1)),
                "start_page": page_index,
                "end_page": page_index,
                "text": text[start.start():][:18000],
            }
        elif current and len(current["text"]) < 18000:
            current["text"] += "\n" + text[: max(0, 18000 - len(current["text"]))]
    if current:
        current["end_page"] = len(reader.pages)
        raw_cases.append(current)

    if len(raw_cases) != int(source.get("expected_cases", 245)):
        raise ValueError(f"Figshare PDF 应提取 {source.get('expected_cases', 245)} 件，实际 {len(raw_cases)} 件")

    result: list[dict[str, Any]] = []
    for raw in raw_cases:
        text = raw["text"]
        number_match = CASE_NUMBER.search(text[:800])
        case_number = normalize_case_number(number_match.group(0)) if number_match else "待从裁判文书原文核验"
        header_end = text.find("案件性质")
        title_start = number_match.end() if number_match else 0
        title = compact(text[title_start:header_end if header_end > title_start else title_start + 500])
        title = re.sub(r"^[号：:、.\s]+", "", title)
        if not title:
            title = f"知识产权惩罚性赔偿判决数据集第{raw['index']}件"
        nature = extract_field(text, "案件性质")
        region = extract_field(text, "案件地区")
        cause = extract_field(text, "案由")
        disposition = extract_field(text, "裁判结果") or "裁判结果待回到判决全文核验"
        court = find_court(text)
        category = category_for(cause + title)
        page_label = f"第{raw['start_page']}-{raw['end_page']}页"
        full_text = (
            f"Figshare公开数据集第{raw['index']}件；{case_number}；{title}；"
            f"案由：{cause or cause_for(category, title)}；裁判结果：{disposition}；原合集定位：{page_label}。"
            "本地索引仅保存判决元数据摘要，具体事实、证据、说理、金额和生效状态须回到CC BY 4.0原始判决合集复核。"
        )
        result.append({
            "case_id": f"FIG-IP-PD-{raw['index']:03d}",
            "title": title[:500],
            "case_number": case_number,
            "court": court,
            "court_level": court_level_for(court),
            "province": province_for(court, region),
            "city": "",
            "case_type": category,
            "cause_of_action": cause or cause_for(category, title),
            "procedure": procedure_for(nature + title),
            "judgment_date": exact_date_from_pdf(text),
            "effective_status": "公开判决，生效状态待核验",
            "source_type": "other_verified_public_case",
            "source_tier": 6,
            "source_url": source["url"],
            "obtained_at": obtained,
            "rights": {},
            "claims": [],
            "defenses": [],
            "material_facts": ["本条由公开判决合集的元数据页机器提取，案件事实须回到原文复核"],
            "disputed_issues": [cause or cause_for(category, title)],
            "evidence": [],
            "infringing_acts": [],
            "comparison": {},
            "applicable_laws": [],
            "court_reasoning": [],
            "key_rules": ["该案被公开研究数据集列为知识产权惩罚性赔偿样本，具体适用条件和计算方法须核验判决全文"],
            "disposition": disposition,
            "claimed_amount": None,
            "awarded_amount": None,
            "reasonable_expenses": None,
            "punitive_damages": True,
            "punitive_multiplier": None,
            "damages": {"dataset_selection": "知识产权惩罚性赔偿判决样本", "verification": "待逐案复核"},
            "law_version_status": "待核实",
            "review_status": "机器提取（Figshare CC BY 4.0判决合集）",
            "citations": [{"field": "source", "paragraph": f"Figshare文件59104196，{page_label}"}],
            "full_text": full_text,
        })
    return result


def download_if_needed(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 10000:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 CodexCaseIndexer/1.0"})
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, context=context, timeout=45) as response:
                payload = response.read()
            if len(payload) < 10000:
                raise ValueError(f"官方页面内容异常短：{len(payload)}字节")
            path.write_bytes(payload)
            return
        except Exception as exc:  # noqa: BLE001 - 需要保留最后一次网络错误
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"下载失败：{url}：{last_error}")


def html_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    parser = PageTextParser()
    parser.feed(text)
    parser.close()
    return [html.unescape(line) for line in parser.lines]


def extract_entries(lines: list[str], year: int) -> list[str]:
    starts = [
        index for index, line in enumerate(lines)
        if str(year) in line and "50件典型知识产权案例" in line
    ]
    start = starts[-1] if starts else 0
    entries: list[str] = []
    current_text = ""
    for line in lines[start + 1:]:
        if (entries or current_text) and "10大知识产权案件简介" in line:
            break
        match = ENTRY_NUMBER.match(line)
        if match:
            if current_text:
                entries.append(compact(current_text))
                if len(entries) == 50:
                    current_text = ""
                    break
            current_text = match.group(2)
            continue
        if current_text and not HEADING.match(line) and "50件典型知识产权案例" not in line:
            current_text += " " + line
        if len(entries) == 49 and current_text and "责任编辑" in line:
            break
    if current_text and len(entries) < 50:
        entries.append(compact(current_text))
    if len(entries) != 50:
        raise ValueError(f"{year}年官方页面应提取50件，实际提取{len(entries)}件")
    return entries


def official_case(entry: str, year: int, index: int, url: str, obtained: str) -> dict[str, Any]:
    number_match = CASE_NUMBER.search(entry)
    case_number = normalize_case_number(number_match.group(0)) if number_match else "待从裁判文书原文核验"
    cut = number_match.start() if number_match else len(entry)
    bracket = max(entry.rfind("〔", 0, cut), entry.rfind("[", 0, cut))
    title_end = bracket if bracket >= 0 and cut - bracket < 80 else cut
    title = compact(entry[:title_end]).rstrip("，,；;：:")
    title = re.sub(
        r"[（(]?\s*[^，。；（）()]{0,45}(?:人民法院|知识产权法院)\s*$",
        "",
        title,
    ).rstrip("（(，,；;：:")
    prefix = entry[max(0, cut - 80):cut]
    court_matches = re.findall(r"([^，,；;。〔〕\[\]（）()]{2,35}(?:人民法院|知识产权法院))", prefix)
    court = compact(court_matches[-1]) if court_matches else "待从裁判文书原文核验"
    category = category_for(title)
    full_text = (
        f"最高人民法院{year}年度50件典型知识产权案例名单第{index}件：{entry}。"
        "本条为最高人民法院官方典型案例名单索引；裁判事实、理由、主文、准确裁判日期及生效状态须回到原裁判文书核验。"
    )
    return {
        "case_id": f"SPC-TYP-{year}-{index:02d}",
        "title": title[:500] or f"{year}年度典型知识产权案例第{index}件",
        "case_number": case_number,
        "court": court,
        "court_level": court_level_for(court),
        "province": province_for(court),
        "city": "",
        "case_type": category,
        "cause_of_action": cause_for(category, title),
        "procedure": procedure_for(title),
        "judgment_date": "1900-01-01",
        "effective_status": "入选最高人民法院年度典型案例，生效状态待原文核验",
        "source_type": "spc_typical_case",
        "source_tier": 3,
        "source_url": url,
        "obtained_at": obtained,
        "rights": {},
        "claims": [],
        "defenses": [],
        "material_facts": ["最高人民法院年度典型案例名单索引，事实待原裁判文书核验"],
        "disputed_issues": [cause_for(category, title)],
        "evidence": [],
        "infringing_acts": [],
        "comparison": {},
        "applicable_laws": [],
        "court_reasoning": [],
        "key_rules": ["最高人民法院年度典型案例线索，具体裁判规则须回到裁判文书或案例简介核验"],
        "disposition": "待从原裁判文书核验",
        "claimed_amount": None,
        "awarded_amount": None,
        "reasonable_expenses": None,
        "punitive_damages": "惩罚性赔偿" in title,
        "punitive_multiplier": None,
        "damages": {},
        "law_version_status": "待核实",
        "review_status": "机器提取（最高人民法院年度典型案例名单）",
        "citations": [{"field": "index", "paragraph": f"{year}年度50件典型知识产权案例第{index}件"}],
        "full_text": full_text,
    }


def extract_official_cases(manifest: dict[str, Any], html_dir: Path, obtained: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in manifest["official_typical_case_pages"]:
        path = html_dir / source["file"]
        download_if_needed(source["url"], path)
        entries = extract_entries(html_lines(path), int(source["year"]))
        result.extend(
            official_case(entry, int(source["year"]), index, source["url"], obtained)
            for index, entry in enumerate(entries, start=1)
        )
    return result


def deduplicate(base: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen_numbers: set[str] = set()
    seen_titles: set[str] = set()
    seen_hashes: set[str] = set()
    for item in base:
        seen_numbers.update(number_keys(str(item.get("case_number", ""))))
        seen_titles.add(title_key(str(item.get("title", ""))))
        seen_hashes.add(hashlib.sha256(str(item.get("full_text", "")).encode("utf-8")).hexdigest())

    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for item in candidates:
        keys = number_keys(str(item.get("case_number", "")))
        tkey = title_key(str(item.get("title", "")))
        digest = hashlib.sha256(str(item.get("full_text", "")).encode("utf-8")).hexdigest()
        reason = ""
        if keys and keys & seen_numbers:
            reason = "案号重复"
        elif not keys and tkey and tkey in seen_titles:
            reason = "标题重复"
        elif digest in seen_hashes:
            reason = "正文摘要哈希重复"
        if reason:
            duplicates.append({"case_id": item["case_id"], "case_number": item["case_number"], "reason": reason})
            continue
        unique.append(item)
        seen_numbers.update(keys)
        seen_titles.add(tkey)
        seen_hashes.add(digest)
    return unique, duplicates


def deduplicate_existing(base: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """在扩容前清理既有跨来源重复，优先保留来源等级更高的记录。"""
    ranked = sorted(
        enumerate(base),
        key=lambda pair: (int(pair[1].get("source_tier", 6)), pair[0]),
    )
    kept_indices: list[int] = []
    duplicates: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    seen_titles: set[str] = set()
    seen_hashes: set[str] = set()
    for original_index, item in ranked:
        keys = number_keys(str(item.get("case_number", "")))
        tkey = title_key(str(item.get("title", "")))
        digest = hashlib.sha256(str(item.get("full_text", "")).encode("utf-8")).hexdigest()
        reason = ""
        if keys and keys & seen_numbers:
            reason = "既有库跨来源案号重复"
        elif not keys and tkey and tkey in seen_titles:
            reason = "既有库无案号记录标题重复"
        elif digest in seen_hashes:
            reason = "既有库正文摘要哈希重复"
        if reason:
            duplicates.append({
                "stage": "base_cleanup",
                "case_id": item["case_id"],
                "case_number": item.get("case_number", ""),
                "reason": reason,
            })
            continue
        kept_indices.append(original_index)
        seen_numbers.update(keys)
        seen_titles.add(tkey)
        seen_hashes.add(digest)
    kept = [base[index] for index in sorted(kept_indices)]
    return kept, duplicates


def write_outputs(
    out: Path,
    merged: list[dict[str, Any]],
    original_base_count: int,
    retained_base_count: int,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    manifest: dict[str, Any],
    obtained: str,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    by_type = Counter(str(item.get("case_type", "未分类")) for item in merged)
    by_source = Counter(str(item.get("source_type", "未知")) for item in merged)
    added_by_type = Counter(str(item.get("case_type", "未分类")) for item in selected)
    added_by_source = Counter(str(item.get("source_type", "未知")) for item in selected)
    summary = {
        "scope": "全国（含福建本地）",
        "generated_at": obtained,
        "base_cases": original_base_count,
        "base_duplicate_records_removed": original_base_count - retained_base_count,
        "retained_base_cases": retained_base_count,
        "added_cases": len(selected),
        "net_increase": len(merged) - original_base_count,
        "total_cases": len(merged),
        "expansion_ratio": round(len(merged) / original_base_count, 4) if original_base_count else None,
        "by_case_type": dict(sorted(by_type.items())),
        "by_source_type": dict(sorted(by_source.items())),
        "added_by_case_type": dict(sorted(added_by_type.items())),
        "added_by_source_type": dict(sorted(added_by_source.items())),
        "verified_or_official_count": sum(1 for item in merged if int(item.get("source_tier", 6)) <= 4),
        "pkulaw_index_lead_count": sum(
            1 for item in merged if "pkulaw.com" in str(item.get("source_url", ""))
        ),
        "figshare_dataset_count": sum(
            1 for item in merged if str(item.get("case_id", "")).startswith("FIG-IP-PD-")
        ),
        "rmfyalk_index_count": by_source.get("people_court_case_library", 0),
        "wenshu_index_count": by_source.get("effective_judgment", 0),
        "spc_typical_case_count": by_source.get("spc_typical_case", 0),
        "note": "本轮扩容优先保留Figshare CC BY 4.0判决样本及最高人民法院年度典型案例索引；所有机器提取记录仍须回到原文复核。",
    }
    (out / "collection-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "generated_at": obtained,
        "original_base_count": original_base_count,
        "retained_base_count": retained_base_count,
        "base_duplicate_records_removed": original_base_count - retained_base_count,
        "candidate_count": len(candidates),
        "candidate_duplicate_count": sum(
            1 for item in duplicates if item.get("stage") == "candidate_dedup"
        ),
        "total_duplicate_records_removed": len(duplicates),
        "unique_candidate_count": len(candidates) - sum(
            1 for item in duplicates if item.get("stage") == "candidate_dedup"
        ),
        "selected_count": len(selected),
        "target_total": original_base_count * 2,
        "final_total": len(merged),
        "duplicates": duplicates,
        "source_manifest": manifest,
    }
    (out / "expansion-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registry_path = out / "source-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    registry["figshare_ip_punitive_dataset"] = {
        "status": "公开可下载，CC BY 4.0",
        "collected_count": sum(1 for item in merged if str(item.get("case_id", "")).startswith("FIG-IP-PD-")),
        "url": manifest["dataset"]["url"],
        "access_note": "本地索引保存结构化元数据摘要，原判决合集通过DOI回溯",
    }
    registry["spc_annual_typical_cases"] = {
        "status": "最高人民法院官方页面",
        "collected_count": sum(1 for item in merged if str(item.get("case_id", "")).startswith("SPC-TYP-")),
        "years": [item["year"] for item in manifest["official_typical_case_pages"]],
        "access_note": "年度典型案例名单索引，裁判全文与生效状态仍需逐案核验",
    }
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = (
        "# 全国知识产权案例库来源说明\n\n"
        f"更新日期：{obtained}\n\n"
        f"本轮由 {original_base_count} 条扩容至 {len(merged)} 条；先移除跨来源重复记录 "
        f"{original_base_count - retained_base_count} 条，再补入 {len(selected)} 条，净增加 "
        f"{len(merged) - original_base_count} 条，达到原数量的 {len(merged) / original_base_count:.2f} 倍。\n\n"
        "## 本轮新增来源\n\n"
        f"- Figshare 数据集《245 Judicial Decisions Applying Punitive Damages in Chinese IP cases》，"
        f"DOI：{manifest['dataset']['doi']}，许可：{manifest['dataset']['license']}。\n"
        "- 最高人民法院历年中国法院50件典型知识产权案例官方名单；逐条保留对应年度页面。\n\n"
        "## 使用边界\n\n"
        "新增记录均为机器结构化索引。未在来源中明确出现的法院、裁判日期、金额、裁判规则不作推测；"
        "正式法律意见必须打开来源原文核对案号、程序、生效状态、证据、说理、主文及当时有效法。\n"
    )
    (out / "provenance.md").write_text(provenance, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="将全国知识产权案例库扩充至原数量两倍")
    parser.add_argument("--base", required=True, help="既有 cases.json")
    parser.add_argument("--pdf", required=True, help="Figshare 245件判决合集PDF")
    parser.add_argument("--manifest", required=True, help="扩容来源清单JSON")
    parser.add_argument("--official-dir", required=True, help="官方网页缓存目录")
    parser.add_argument("--out", required=True, help="输出案例库目录")
    parser.add_argument("--target-total", type=int, help="目标总数；默认是既有数量的两倍")
    args = parser.parse_args()

    base_path = Path(args.base).resolve()
    raw_base = json.loads(base_path.read_text(encoding="utf-8"))
    base, base_duplicates = deduplicate_existing(raw_base)
    manifest = json.loads(Path(args.manifest).resolve().read_text(encoding="utf-8"))
    obtained = date.today().isoformat()
    pdf_cases = extract_pdf_cases(Path(args.pdf).resolve(), manifest["dataset"], obtained)
    official_cases = extract_official_cases(manifest, Path(args.official_dir).resolve(), obtained)
    candidates = pdf_cases + sorted(
        official_cases,
        key=lambda item: (-int(item["case_id"].split("-")[2]), int(item["case_id"].split("-")[3])),
    )
    unique, candidate_duplicates = deduplicate(base, candidates)
    duplicates = base_duplicates + [dict(item, stage="candidate_dedup") for item in candidate_duplicates]
    target_total = args.target_total or len(raw_base) * 2
    add_count = target_total - len(base)
    if add_count <= 0:
        raise ValueError("目标总数必须大于既有案例数")
    if len(unique) < add_count:
        raise ValueError(f"去重后仅有{len(unique)}条候选，无法新增{add_count}条")
    selected = unique[:add_count]
    merged = base + selected
    write_outputs(
        Path(args.out).resolve(), merged, len(raw_base), len(base), selected, candidates, duplicates, manifest, obtained
    )
    print(json.dumps({
        "original_base": len(raw_base),
        "retained_base": len(base),
        "base_duplicates_removed": len(base_duplicates),
        "pdf_candidates": len(pdf_cases),
        "official_candidates": len(official_cases),
        "duplicates": len(duplicates),
        "selected": len(selected),
        "total": len(merged),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
