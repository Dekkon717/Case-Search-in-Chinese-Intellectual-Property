"""检查案例库的完整性、重复和明显敏感信息。"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from case_db import (
    REQUIRED_FIELDS,
    SOURCE_TYPES,
    connect,
    detect_sensitive,
    parse_json_fields,
)


def is_verifiable_case_number(value: object) -> bool:
    """排除“待核验”等占位文本，只对真实案号执行重复检查。"""
    text = str(value or "").strip()
    return bool(text) and not text.startswith(("待", "未获取", "不详"))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验全国知识产权案例库")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    args = parser.parse_args()
    try:
        conn = connect(args.db)
    except (OSError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    rows = [parse_json_fields(dict(row)) for row in conn.execute("SELECT * FROM cases")]
    conn.close()
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        warnings.append("数据库为空，还没有可检索的案例")

    hashes = Counter(str(row.get("source_hash", "")) for row in rows)
    numbers = Counter(
        str(row.get("case_number", "")).strip()
        for row in rows
        if is_verifiable_case_number(row.get("case_number"))
    )
    for row in rows:
        label = str(row.get("case_id", "未知案例"))
        for field in REQUIRED_FIELDS:
            if row.get(field) in (None, ""):
                errors.append(f"{label}：缺少 {field}")
        if row.get("source_type") not in SOURCE_TYPES:
            errors.append(f"{label}：source_type 无效")
        if row.get("source_tier") not in range(1, 7):
            errors.append(f"{label}：source_tier 无效")
        if row.get("effective_status") != "已生效":
            warnings.append(f"{label}：生效状态为 {row.get('effective_status')}")
        if row.get("law_version_status") != "现行":
            warnings.append(f"{label}：法律版本状态为 {row.get('law_version_status')}")
        if row.get("review_status") != "人工复核":
            warnings.append(f"{label}：尚未标记为人工复核")
        sensitive = detect_sensitive(str(row.get("full_text", "")))
        if sensitive:
            errors.append(f"{label}：正文包含" + "、".join(sensitive))
        if not str(row.get("source_url", "")).startswith(("https://", "http://")):
            errors.append(f"{label}：source_url 不是 http/https 地址")
        if not row.get("citations"):
            warnings.append(f"{label}：没有原文引用定位")

    for value, count in hashes.items():
        if value and count > 1:
            errors.append(f"正文哈希重复 {count} 次：{value[:16]}…")
    for value, count in numbers.items():
        if value and count > 1:
            warnings.append(f"案号出现 {count} 次：{value}；请确认是否为不同文书版本")

    print(f"案例数量：{len(rows)}")
    print(f"错误：{len(errors)}；警告：{len(warnings)}")
    if errors:
        print("\n错误：")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f"- {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
