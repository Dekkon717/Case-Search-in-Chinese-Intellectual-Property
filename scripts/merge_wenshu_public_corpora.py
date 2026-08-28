"""把裁判文书网衍生公开数据集转换并合并到统一知识产权案例库。

脚本不绕过裁判文书网登录或验证码；输入数据来自公开发布、明确说明以中国
裁判文书网为来源的研究数据集。每条记录保留数据集、分片和行号信息，方便
回溯；正文仍标记为机器提取，不能替代律师对原文的复核。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable


IP_WORDS = ("知识产权", "商标", "著作权", "版权", "专利", "不正当竞争", "商业秘密", "植物新品种", "集成电路布图")
CAUSE_MAP = {
    "商标": "侵害商标权纠纷",
    "著作权": "著作权权属、侵权纠纷",
    "版权": "著作权权属、侵权纠纷",
    "专利": "专利权权属、侵权纠纷",
    "不正当竞争": "不正当竞争纠纷",
    "商业秘密": "侵害商业秘密纠纷",
    "植物新品种": "植物新品种权权属、侵权纠纷",
    "集成电路布图": "集成电路布图设计专有权纠纷",
}


def redact(text: str) -> str:
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "1**********", text)
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "******************", text)
    text = re.sub(r"(?<!\d)\d{16,19}(?!\d)", "****************", text)
    return text


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def province_for(court: str) -> str:
    provinces = {
        "北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市",
        "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
        "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
        "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
        "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
        "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
        "甘肃": "甘肃省", "青海": "青海省", "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区",
        "西藏": "西藏自治区", "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
    }
    for key, value in provinces.items():
        if key in court:
            return value
    return "全国"


def category_for(text: str, cause: str = "") -> tuple[str, str]:
    haystack = f"{cause} {text}"
    for word, mapped in CAUSE_MAP.items():
        if word in haystack:
            return ("著作权" if word == "版权" else word, mapped)
    return "知识产权", "知识产权纠纷（案由待核验）"


def date_for(text: str, fallback: int | str | None = None) -> str:
    match = re.search(r"[（(〔]\s*((?:19|20)\d{2})\s*[）)〕]", text)
    year = match.group(1) if match else str(fallback or "")
    return f"{year}-01-01" if re.fullmatch(r"(?:19|20)\d{2}", year) else "1900-01-01"


def case_number(text: str) -> str:
    match = re.search(r"[（(〔]\s*((?:19|20)\d{2})\s*[）)〕][^\n，,。]{0,80}?号", text)
    return match.group(0).strip() if match else "待从裁判文书正文核验"


def court_from(text: str) -> str:
    match = re.search(r"([^\n]{0,60}(?:最高人民法院|高级人民法院|中级人民法院|基层人民法院|知识产权法院))", text)
    return match.group(1).strip() if match else "待核实"


def base_record(case_id: str, title: str, number: str, court: str, category: str, cause: str,
                procedure: str, judgment_date: str, full_text: str, source_url: str,
                review_status: str, citation: str, source_type: str = "effective_judgment",
                source_tier: int = 5) -> dict[str, Any]:
    full_text = redact(full_text.strip())
    rule = full_text[-3000:] if full_text else ""
    return {
        "case_id": case_id,
        "title": title.strip() or "未命名知识产权裁判文书",
        "case_number": number.strip() or "待从裁判文书正文核验",
        "court": court.strip() or "待核实",
        "court_level": "最高" if "最高人民法院" in court else "高级/中级/基层（以原文为准）",
        "province": province_for(court), "city": "",
        "case_type": category, "cause_of_action": cause, "procedure": procedure or "民事",
        "judgment_date": judgment_date, "effective_status": "公开文书，生效状态待核实",
        "source_type": source_type, "source_tier": source_tier, "source_url": source_url,
        "obtained_at": date.today().isoformat(),
        "rights": {"right_type": category}, "claims": [], "defenses": [],
        "material_facts": [full_text[:4000]] if full_text else [],
        "disputed_issues": [cause], "evidence": [], "infringing_acts": [], "comparison": {},
        "applicable_laws": [], "court_reasoning": [rule] if rule else [],
        "key_rules": ["机器提取记录；正式意见须回到来源原文核验"] ,
        "disposition": "裁判主文请回到来源原文核验",
        "claimed_amount": None, "awarded_amount": None, "reasonable_expenses": None,
        "punitive_damages": False, "punitive_multiplier": None, "damages": {},
        "law_version_status": "待核实", "review_status": review_status,
        "citations": [{"field": "source", "paragraph": citation}], "full_text": full_text,
    }


def iter_c3rd(zip_path: Path) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json") or not name.startswith("C3RD/"):
                continue
            payload = json.loads(archive.read(name))
            for raw in payload.get("ctxs", {}).values():
                cats = raw.get("Category") or []
                cat_text = json.dumps(cats, ensure_ascii=False)
                if not any(word in cat_text for word in IP_WORDS):
                    continue
                source_id = str(raw.get("CaseId") or sha(str(raw.get("Case", ""))))
                if source_id in seen:
                    continue
                seen.add(source_id)
                title = str(raw.get("Case") or "")
                cause_raw = str((raw.get("CaseCause") or [""])[0])
                category, cause = category_for(" ".join([title, cat_text]), cause_raw)
                text = "\n".join(filter(None, [raw.get("CaseRecord"), raw.get("JudgeAccusation"), raw.get("JudgeReason"), raw.get("JudgeResult")]))
                yield base_record(
                    f"C3RD-IP-{source_id}", title, case_number(title), court_from(title), category, cause,
                    str(raw.get("CaseProc") or "民事"), date_for(title), text,
                    "https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html",
                    "机器提取（C3RD，来源为中国裁判文书网）",
                    f"C3RD 数据集文件 {name}，CaseId={source_id}；由中国裁判文书网公开文书构建",
                )


def iter_thefinai(path: Path) -> Iterable[dict[str, Any]]:
    for index, raw in enumerate(json.loads(path.read_text(encoding="utf-8")), start=1):
        text = str(raw.get("text") or "")
        if not any(word in text for word in IP_WORDS):
            continue
        category, cause = category_for(text, str(raw.get("category") or ""))
        title = text.split("原告", 1)[0].strip().replace("  ", " ")[:180]
        number = case_number(text)
        yield base_record(
            f"PLEIAS-IP-{sha(text)[:20]}", title, number, court_from(text), category, cause,
            "民事" if "民事" in text[:300] else "行政" if "行政" in text[:300] else "其他",
            date_for(text, raw.get("date")), text,
            "https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html",
            "机器提取（PleIAs/中国法院裁判文书公开语料）",
            f"TheFinAI/corpus-shard-20；分片={raw.get('shard_path')}；行号={raw.get('row_index')}",
        )


def iter_appeal(path: Path) -> Iterable[dict[str, Any]]:
    for raw in json.loads(path.read_text(encoding="utf-8")):
        combined = json.dumps(raw, ensure_ascii=False)
        if not any(word in combined for word in IP_WORDS):
            continue
        for side in ("first-instance", "second-instance"):
            doc = raw.get(side) or {}
            text = "\n".join(str(doc.get(k) or "") for k in ("header", "claim", "fact_description", "reason", "judgment"))
            if not text.strip():
                continue
            category, cause = category_for(text)
            title = str(doc.get("header") or "").split("\n", 1)[0][:180]
            yield base_record(
                f"APPEAL-IP-{raw.get('index')}-{side[0].upper()}-{sha(text)[:12]}", title, case_number(text),
                court_from(text), category, cause, "二审" if side.startswith("second") else "一审", date_for(text), text,
                "https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html",
                "机器提取（AppealCase，来源为中国裁判文书网）",
                f"AppealCase 数据集 index={raw.get('index')}，文书={side}",
            )


def iter_claimgen(path: Path) -> Iterable[dict[str, Any]]:
    for raw in json.loads(path.read_text(encoding="utf-8")):
        fact = str(raw.get("plaintiffFactSegment") or "")
        cause_raw = str(raw.get("cause") or "")
        if not any(word in f"{cause_raw} {fact}" for word in IP_WORDS):
            continue
        category, cause = category_for(fact, cause_raw)
        claims = raw.get("claims")
        claim_text = " ".join(claims) if isinstance(claims, list) else str(claims or "")
        text = f"事实与理由：{fact}\n诉讼请求：{claim_text}"
        yield base_record(
            f"CLAIMGEN-IP-{raw.get('id')}-{sha(text)[:12]}", f"裁判文书网衍生主张样本-{raw.get('id')}",
            "待从裁判文书正文核验", "待核实", category, cause, "民事", date_for(text), text,
            "https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html",
            "机器提取（ClaimGen-CN，非完整裁判文书）",
            f"ClaimGen-CN 样本 id={raw.get('id')}；数据说明标注来源为中国裁判文书网",
            source_type="other_verified_public_case", source_tier=6,
        )


def deduplicate(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_text: set[str] = set()
    for record in records:
        title = re.sub(r"\s+", "", str(record.get("title", ""))).lower()
        number = str(record.get("case_number", ""))
        text_hash = sha(str(record.get("full_text", "")))[:24]
        if text_hash in seen_text:
            continue
        key = (title, number) if number and not number.startswith("待") else (title, text_hash)
        if key in seen:
            continue
        seen.add(key)
        seen_text.add(text_hash)
        out.append(record)
    return out, len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description="合并裁判文书网来源的公开知识产权数据")
    parser.add_argument("--base", required=True)
    parser.add_argument("--c3rd", required=True)
    parser.add_argument("--thefinai", required=True)
    parser.add_argument("--appeal", required=True)
    parser.add_argument("--claimgen")
    parser.add_argument("--target", type=int, default=6100)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    candidates: list[dict[str, Any]] = []
    candidates.extend(iter_c3rd(Path(args.c3rd)))
    candidates.extend(iter_thefinai(Path(args.thefinai)))
    candidates.extend(iter_appeal(Path(args.appeal)))
    if args.claimgen:
        candidates.extend(iter_claimgen(Path(args.claimgen)))
    unique_candidates, _ = deduplicate(candidates)
    merged, _ = deduplicate([*base, *unique_candidates])
    if len(merged) < args.target:
        raise SystemExit(f"去重后仅有 {len(merged)} 条，未达到目标 {args.target}；请增加 TheFinAI 分片或放宽来源范围")
    merged = merged[: args.target]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"base": len(base), "candidates": len(unique_candidates), "total": len(merged),
                      "by_source": dict(Counter(x["source_type"] for x in merged))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
