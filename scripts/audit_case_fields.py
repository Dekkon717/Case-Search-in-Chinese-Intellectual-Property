"""审计案例字段质量，不修改数据库。

该脚本用轻量规则发现标题/法院字段污染、案号占位、日期异常、敏感信息
和文书类型分布。它输出的是待复核清单，不会擅自改写原始案例。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from case_db import connect, detect_sensitive, parse_json_fields
from search_cases import infer_matter


CASE_NUMBER_RE = re.compile(r"[（(〔]\s*(?:19|20)\d{2}\s*[）)〕].{0,100}?号")
OFFICIAL_WENSHU_ENTRY = "https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html"
POLLUTION_TOKENS = ("本院认为", "依照", "原告", "被告", "审判长", "案由：")


def add_sample(samples: dict[str, list[str]], key: str, case_id: str, limit: int) -> None:
    if len(samples[key]) < limit:
        samples[key].append(case_id)


def display_path(path: str) -> str:
    resolved = Path(path).resolve()
    root = Path(__file__).resolve().parents[1]
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.name


def audit(db_path: str, sample_limit: int = 10) -> dict[str, object]:
    conn = connect(db_path)
    rows = [parse_json_fields(dict(row)) for row in conn.execute("SELECT * FROM cases")]
    conn.close()
    counts: Counter[str] = Counter()
    matter_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        case_id = str(row.get("case_id", ""))
        title = str(row.get("title", ""))
        court = str(row.get("court", ""))
        number = str(row.get("case_number", "")).strip()
        judgment_date = str(row.get("judgment_date", ""))
        source_url = str(row.get("source_url", ""))
        matter = infer_matter(row)
        matter_counts[matter] += 1
        review_counts[str(row.get("review_status", ""))] += 1
        source_counts[str(row.get("source_type", ""))] += 1
        if len(title) > 180 or any(token in title for token in POLLUTION_TOKENS):
            counts["title_suspected_pollution"] += 1
            add_sample(samples, "title_suspected_pollution", case_id, sample_limit)
        if len(court) > 80 or any(token in court for token in POLLUTION_TOKENS):
            counts["court_suspected_pollution"] += 1
            add_sample(samples, "court_suspected_pollution", case_id, sample_limit)
        if number.startswith(("待", "未获取", "不详")):
            counts["case_number_placeholder"] += 1
            add_sample(samples, "case_number_placeholder", case_id, sample_limit)
        elif not CASE_NUMBER_RE.search(number) and not re.search(r"\d{4}-\d{1,4}-\d{1,4}-", number):
            counts["case_number_unrecognized"] += 1
            add_sample(samples, "case_number_unrecognized", case_id, sample_limit)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", judgment_date) or judgment_date.startswith("1900-"):
            counts["date_suspected_placeholder"] += 1
            add_sample(samples, "date_suspected_placeholder", case_id, sample_limit)
        if source_url == OFFICIAL_WENSHU_ENTRY:
            counts["generic_wenshu_entry_url"] += 1
            add_sample(samples, "generic_wenshu_entry_url", case_id, sample_limit)
        sensitive = detect_sensitive(str(row.get("full_text", "")))
        if sensitive:
            counts["pii_regex_hit"] += 1
            add_sample(samples, "pii_regex_hit", case_id, sample_limit)
    result = {
        "generated_at": date.today().isoformat(),
        "database": display_path(db_path),
        "record_count": len(rows),
        "counts": dict(sorted(counts.items())),
        "matter_counts": dict(sorted(matter_counts.items())),
        "review_status_counts": dict(sorted(review_counts.items())),
        "source_type_counts": dict(sorted(source_counts.items())),
        "samples": dict(samples),
        "interpretation": {
            "title_or_court_pollution": "疑似污染只进入清单，需人工核对后再修复",
            "generic_wenshu_entry_url": "公开入口可追溯性不足，应补充具体文书详情链接",
            "pii_regex_hit": "命中即阻止发布，先脱敏再入库",
            "matter_counts": "由标题、案由、程序和正文开头推断，仅用于检索过滤",
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="审计知识产权案例字段质量")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--out", help="可选 JSON 输出路径")
    parser.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args()
    result = audit(args.db, max(1, args.sample_limit))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
