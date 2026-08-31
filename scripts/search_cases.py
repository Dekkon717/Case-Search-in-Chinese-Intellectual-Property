"""对本地案例库进行可解释的混合关键词检索。

默认只检索民事知识产权案件，避免把刑事、行政和执行文书混入民事类案。
使用 ``--matter all`` 可恢复跨程序检索。检索仍是线索工具，不构成法律结论。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from typing import Iterable

from case_db import connect, parse_json_fields, query_terms, snippet


FIELD_WEIGHTS = {
    "title": 7.0,
    "disputed_issues": 6.0,
    "key_rules": 6.0,
    "defenses": 5.0,
    "comparison": 4.5,
    "infringing_acts": 4.0,
    "evidence": 3.5,
    "material_facts": 3.0,
    "court_reasoning": 2.0,
    "full_text": 1.0,
}

AUTHORITY_BONUS = {1: 5.0, 2: 4.0, 3: 3.0, 4: 2.5, 5: 1.5, 6: 0.5}
# 公开研究语料通常是机器提取且生效状态待核验，先降低其内容字段对排序的
# 影响；这不是对案件实体结论的否定，而是提醒使用者优先核对高权威来源。
SOURCE_QUALITY_FACTOR = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.95, 5: 0.7, 6: 0.55}

# 仅用于扩大召回，不改变用户原始检索词的展示。系数小于1，避免同义词
# 命中压过用户明确输入的词语。
TERM_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "许可": ("授权", "许可合同", "被许可", "独占许可", "非独占许可"),
    "终止": ("解除", "期限届满", "授权终止", "停止使用"),
    "混淆可能性": ("混淆误认", "近似", "混淆行为", "指示商品来源"),
    "软件": ("计算机软件", "软件程序", "软件著作权"),
    "源代码": ("源程序", "程序代码", "部分复制", "实质性相似"),
    "域名": ("网络域名", "地址栏", "搜索引擎"),
    "不正当竞争": ("混淆行为", "仿冒", "攀附商誉"),
    "关联公司": ("人格混同", "共同侵权", "实际控制人"),
    "合理使用": ("正当使用", "描述性使用", "指示商品来源"),
    "著作权": ("版权", "作品权属", "复制权"),
    "商标": ("注册商标", "标识", "字号"),
}

QUERY_VOCABULARY = set(TERM_EXPANSIONS) | {
    synonym for values in TERM_EXPANSIONS.values() for synonym in values
}
QUERY_VOCABULARY.update(
    {
        "合同", "解除", "终止", "期限", "届满", "续约", "默示", "混淆", "可能性",
        "修改", "复制", "部署", "域名", "关联公司", "商誉", "侵权", "赔偿", "合理使用",
        "描述性使用", "源代码", "软件", "著作权", "商标", "不正当竞争", "商业秘密",
        "保密措施", "接触可能性", "实质相同",
    }
)

POLLUTION_TOKENS = ("本院认为", "依照", "原告", "被告", "审判长", "案由：")


def field_quality_factor(row: dict[str, object], field: str) -> float:
    """降低疑似把正文拼进标题/法院字段的机器记录权重。"""
    if field == "title":
        value = str(row.get(field, ""))
        if len(value) > 180 or any(token in value for token in POLLUTION_TOKENS):
            return 0.25
    if field == "court":
        value = str(row.get(field, ""))
        if len(value) > 80 or any(token in value for token in POLLUTION_TOKENS):
            return 0.25
    return 1.0


def build_filters(args: argparse.Namespace) -> tuple[str, list[object]]:
    clauses = ["is_active = 1"]
    values: list[object] = []
    if args.court:
        clauses.append("court LIKE ?")
        values.append(f"%{args.court}%")
    if args.cause:
        clauses.append("cause_of_action LIKE ?")
        values.append(f"%{args.cause}%")
    if args.procedure:
        clauses.append("procedure = ?")
        values.append(args.procedure)
    if args.year_from:
        clauses.append("judgment_date >= ?")
        values.append(f"{args.year_from}-01-01")
    if args.year_to:
        clauses.append("judgment_date <= ?")
        values.append(f"{args.year_to}-12-31")
    return " AND ".join(clauses), values


def expand_terms(terms: list[str]) -> list[tuple[str, float, str]]:
    """返回(term, weight_factor, origin)；origin用于解释扩展来源。"""
    result: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    for term in terms:
        if term not in seen:
            result.append((term, 1.0, "原始词"))
            seen.add(term)
        for synonym in TERM_EXPANSIONS.get(term, ()):
            if synonym not in seen:
                result.append((synonym, 0.35, f"{term}的同义/关联词"))
                seen.add(synonym)
    return result


def normalize_query_terms(query: str) -> list[str]:
    """对未分隔的中文自然语言做轻量法律词切分。

    不依赖第三方分词包：优先使用本技能的法律词表最长匹配，无法匹配时
    退化为双字片段。原本已经分隔的词语保持不变。
    """
    raw_terms = query_terms(query)
    vocabulary = sorted(QUERY_VOCABULARY, key=len, reverse=True)
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        if not re.fullmatch(r"[\u4e00-\u9fff]+", raw) or len(raw) <= 4:
            pieces = [raw]
        else:
            pieces = []
            position = 0
            while position < len(raw):
                match = next((word for word in vocabulary if raw.startswith(word, position)), None)
                if match:
                    pieces.append(match)
                    position += len(match)
                else:
                    pieces.append(raw[position : position + 2])
                    position += 2
        for piece in pieces:
            if piece and piece not in seen:
                result.append(piece)
                seen.add(piece)
    return result


def occurrence_score(value: object, terms: Iterable[tuple[str, float, str]], weight: float) -> float:
    if value is None:
        return 0.0
    text = str(value).lower()
    score = 0.0
    for term, factor, _origin in terms:
        count = text.count(term.lower())
        if count:
            score += weight * factor * min(count, 3)
    return score


def infer_matter(row: dict[str, object]) -> str:
    """从标题、案由、程序和正文开头推断文书程序类型。"""
    title = str(row.get("title", ""))
    cause = str(row.get("cause_of_action", ""))
    procedure = str(row.get("procedure", ""))
    head = " ".join((title, cause, procedure, str(row.get("full_text", ""))[:500]))
    if any(token in " ".join((title, cause, procedure)) for token in ("刑事", "犯罪", "罪")):
        return "criminal"
    if any(token in " ".join((title, cause, procedure)) for token in ("行政", "行政诉讼", "行政处罚")):
        return "administrative"
    if any(token in " ".join((title, cause, procedure)) for token in ("执行", "执行裁定", "被执行人")):
        return "enforcement"
    if any(token in head for token in ("刑事判决书", "公诉机关", "刑事裁定书")):
        return "criminal"
    return "civil"


def recency_bonus(judgment_date: str) -> float:
    try:
        years = max(0, (date.today() - date.fromisoformat(judgment_date)).days / 365.25)
        return max(0.0, 1.5 - years * 0.15)
    except ValueError:
        return 0.0


def rank_rows(rows: list[dict[str, object]], terms: list[str], matter: str) -> list[dict[str, object]]:
    weighted_terms = expand_terms(terms)
    ranked: list[dict[str, object]] = []
    for row in rows:
        row_matter = infer_matter(row)
        if matter != "all" and row_matter != matter:
            continue
        tier = int(row["source_tier"])
        source_factor = SOURCE_QUALITY_FACTOR.get(tier, 0.7)
        score = sum(
            occurrence_score(
                row.get(field),
                weighted_terms,
                weight * field_quality_factor(row, field) * source_factor,
            )
            for field, weight in FIELD_WEIGHTS.items()
        )
        score += AUTHORITY_BONUS.get(tier, 0.0)
        if row.get("effective_status") == "已生效":
            score += 2.0
        if row.get("law_version_status") == "现行":
            score += 1.0
        if row.get("review_status") == "人工复核":
            score += 1.0
        score += recency_bonus(str(row.get("judgment_date", "")))
        if score <= 0:
            continue
        matched_fields = []
        for field in FIELD_WEIGHTS:
            text = str(row.get(field, "")).lower()
            if any(term.lower() in text for term, _factor, _origin in weighted_terms):
                matched_fields.append(field)
        matched_terms = [
            term for term, _factor, _origin in weighted_terms
            if any(term.lower() in str(row.get(field, "")).lower() for field in FIELD_WEIGHTS)
        ]
        ranked.append(
            {
                "score": round(score, 4),
                "case_id": row["case_id"],
                "title": row["title"],
                "case_number": row["case_number"],
                "court": row["court"],
                "province": row["province"],
                "city": row["city"],
                "matter": row_matter,
                "case_type": row["case_type"],
                "judgment_date": row["judgment_date"],
                "procedure": row["procedure"],
                "cause_of_action": row["cause_of_action"],
                "effective_status": row["effective_status"],
                "source_type": row["source_type"],
                "source_tier": row["source_tier"],
                "source_url": row["source_url"],
                "disposition": row["disposition"],
                "key_rules": row.get("key_rules", []),
                "matched_fields": matched_fields,
                "matched_terms": matched_terms,
                "snippet": snippet(str(row.get("full_text", "")), terms),
            }
        )
    ranked.sort(key=lambda item: (-float(item["score"]), int(item["source_tier"])))
    return ranked


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索全国知识产权案例")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--query", required=True, help="自然语言检索词")
    parser.add_argument("--court", help="法院关键词")
    parser.add_argument("--cause", help="案由关键词")
    parser.add_argument("--procedure", help="一审、二审或再审")
    parser.add_argument("--matter", choices=("civil", "criminal", "administrative", "enforcement", "all"),
                        default="civil", help="文书程序类型，默认civil；all表示不限制")
    parser.add_argument("--year-from", type=int, help="起始年份")
    parser.add_argument("--year-to", type=int, help="结束年份")
    parser.add_argument("--limit", type=int, default=10, help="返回数量，默认10")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    terms = normalize_query_terms(args.query)
    if not terms:
        print("错误：query 没有可检索的词语。", file=sys.stderr)
        return 2
    try:
        conn = connect(args.db)
    except (OSError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    where, values = build_filters(args)
    rows = [parse_json_fields(dict(row)) for row in conn.execute(f"SELECT * FROM cases WHERE {where}", values)]
    conn.close()
    ranked = rank_rows(rows, terms, args.matter)
    result = {
        "query": args.query,
        "terms": terms,
        "expanded_terms": [term for term, _factor, _origin in expand_terms(terms)],
        "matter": args.matter,
        "filters": {
            "court": args.court,
            "cause": args.cause,
            "procedure": args.procedure,
            "year_from": args.year_from,
            "year_to": args.year_to,
        },
        "count": min(len(ranked), max(0, args.limit)),
        "warning": "这是可解释关键词检索，不是法律结论；默认仅检索民事文书，仍需逐案核验来源原文。",
        "results": ranked[: max(0, args.limit)],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"检索词：{args.query}；程序：{args.matter}；结果：{result['count']} 条")
        for index, item in enumerate(result["results"], start=1):
            print(f"{index}. {item['title']} | {item['case_number']} | {item['court']}")
            print(f"   得分 {item['score']}；文书类型 {item['matter']}；来源等级 {item['source_tier']}；{item['disposition']}")
            print(f"   命中字段：{', '.join(item['matched_fields'])}")
            print(f"   {item['snippet']}")
            print(f"   {item['source_url']}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
