"""福建商标案例库的 SQLite 公共函数。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1"

JSON_OBJECT_FIELDS = ("rights", "comparison", "damages")
JSON_ARRAY_FIELDS = (
    "claims",
    "defenses",
    "material_facts",
    "disputed_issues",
    "evidence",
    "infringing_acts",
    "applicable_laws",
    "court_reasoning",
    "key_rules",
    "citations",
)

REQUIRED_FIELDS = (
    "case_id",
    "title",
    "case_number",
    "court",
    "judgment_date",
    "source_type",
    "source_tier",
    "source_url",
    "full_text",
)

SOURCE_TYPES = {
    "guiding_case": 1,
    "people_court_case_library": 2,
    "spc_typical_case": 3,
    "fujian_high_court_typical_case": 4,
    "effective_judgment": 5,
    "other_verified_public_case": 6,
}

SENSITIVE_PATTERNS = {
    "疑似身份证号": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "疑似手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "疑似银行卡号": re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
}

CASE_COLUMNS = (
    "case_id",
    "title",
    "case_number",
    "court",
    "court_level",
    "province",
    "city",
    "case_type",
    "cause_of_action",
    "procedure",
    "judgment_date",
    "effective_status",
    "source_type",
    "source_tier",
    "source_url",
    "obtained_at",
    "source_hash",
    "rights",
    "claims",
    "defenses",
    "material_facts",
    "disputed_issues",
    "evidence",
    "infringing_acts",
    "comparison",
    "applicable_laws",
    "court_reasoning",
    "key_rules",
    "disposition",
    "claimed_amount",
    "awarded_amount",
    "reasonable_expenses",
    "punitive_damages",
    "punitive_multiplier",
    "damages",
    "law_version_status",
    "review_status",
    "citations",
    "full_text",
    "search_text",
    "is_active",
    "created_at",
    "updated_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"数据库不存在：{path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_database(db_path: str | Path) -> tuple[Path, str]:
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                case_number TEXT NOT NULL,
                court TEXT NOT NULL,
                court_level TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT '福建省',
                city TEXT NOT NULL DEFAULT '',
                case_type TEXT NOT NULL DEFAULT '民事',
                cause_of_action TEXT NOT NULL DEFAULT '侵害商标权纠纷',
                procedure TEXT NOT NULL DEFAULT '',
                judgment_date TEXT NOT NULL,
                effective_status TEXT NOT NULL DEFAULT '待核实',
                source_type TEXT NOT NULL,
                source_tier INTEGER NOT NULL CHECK(source_tier BETWEEN 1 AND 6),
                source_url TEXT NOT NULL,
                obtained_at TEXT NOT NULL DEFAULT '',
                source_hash TEXT NOT NULL,
                rights TEXT NOT NULL DEFAULT '{}',
                claims TEXT NOT NULL DEFAULT '[]',
                defenses TEXT NOT NULL DEFAULT '[]',
                material_facts TEXT NOT NULL DEFAULT '[]',
                disputed_issues TEXT NOT NULL DEFAULT '[]',
                evidence TEXT NOT NULL DEFAULT '[]',
                infringing_acts TEXT NOT NULL DEFAULT '[]',
                comparison TEXT NOT NULL DEFAULT '{}',
                applicable_laws TEXT NOT NULL DEFAULT '[]',
                court_reasoning TEXT NOT NULL DEFAULT '[]',
                key_rules TEXT NOT NULL DEFAULT '[]',
                disposition TEXT NOT NULL DEFAULT '',
                claimed_amount REAL,
                awarded_amount REAL,
                reasonable_expenses REAL,
                punitive_damages INTEGER NOT NULL DEFAULT 0,
                punitive_multiplier REAL,
                damages TEXT NOT NULL DEFAULT '{}',
                law_version_status TEXT NOT NULL DEFAULT '待核实',
                review_status TEXT NOT NULL DEFAULT '机器提取',
                citations TEXT NOT NULL DEFAULT '[]',
                full_text TEXT NOT NULL,
                search_text TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cases_number ON cases(case_number);
            CREATE INDEX IF NOT EXISTS idx_cases_court ON cases(court);
            CREATE INDEX IF NOT EXISTS idx_cases_cause ON cases(cause_of_action);
            CREATE INDEX IF NOT EXISTS idx_cases_date ON cases(judgment_date);
            CREATE INDEX IF NOT EXISTS idx_cases_source_tier ON cases(source_tier);
            CREATE INDEX IF NOT EXISTS idx_cases_hash ON cases(source_hash);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        tokenizer = "trigram"
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
                    case_id UNINDEXED,
                    title,
                    case_number,
                    court,
                    cause_of_action,
                    search_text,
                    tokenize='trigram'
                )
                """
            )
        except sqlite3.OperationalError:
            tokenizer = "unicode61"
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
                    case_id UNINDEXED,
                    title,
                    case_number,
                    court,
                    cause_of_action,
                    search_text,
                    tokenize='unicode61'
                )
                """
            )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('fts_tokenizer', ?)",
            (tokenizer,),
        )
        conn.commit()
        return path, tokenizer
    finally:
        conn.close()


def detect_sensitive(text: str) -> list[str]:
    return [name for name, pattern in SENSITIVE_PATTERNS.items() if pattern.search(text)]


def validate_case(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        value = raw.get(field)
        if value is None or value == "":
            errors.append(f"缺少必填字段：{field}")
    date = str(raw.get("judgment_date", ""))
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        errors.append("judgment_date 必须使用 YYYY-MM-DD 格式")
    source_type = raw.get("source_type")
    if source_type and source_type not in SOURCE_TYPES:
        errors.append(f"未知 source_type：{source_type}")
    tier = raw.get("source_tier")
    if tier not in range(1, 7):
        errors.append("source_tier 必须是 1 至 6 的整数")
    if source_type in SOURCE_TYPES and tier in range(1, 7):
        expected = SOURCE_TYPES[source_type]
        if tier != expected:
            errors.append(f"source_type 与 source_tier 不匹配，应为 {expected}")
    url = str(raw.get("source_url", ""))
    if url and not url.startswith(("https://", "http://")):
        errors.append("source_url 必须是 http 或 https 地址")
    for field in JSON_OBJECT_FIELDS:
        if field in raw and not isinstance(raw[field], dict):
            errors.append(f"{field} 必须是 JSON 对象")
    for field in JSON_ARRAY_FIELDS:
        if field in raw and not isinstance(raw[field], list):
            errors.append(f"{field} 必须是 JSON 数组")
    return errors


def normalize_case(raw: dict[str, Any], existing_created_at: str | None = None) -> dict[str, Any]:
    now = utc_now()
    normalized: dict[str, Any] = {
        "case_id": str(raw["case_id"]).strip(),
        "title": str(raw["title"]).strip(),
        "case_number": str(raw["case_number"]).strip(),
        "court": str(raw["court"]).strip(),
        "court_level": str(raw.get("court_level", "")).strip(),
        "province": str(raw.get("province", "福建省")).strip(),
        "city": str(raw.get("city", "")).strip(),
        "case_type": str(raw.get("case_type", "民事")).strip(),
        "cause_of_action": str(raw.get("cause_of_action", "侵害商标权纠纷")).strip(),
        "procedure": str(raw.get("procedure", "")).strip(),
        "judgment_date": str(raw["judgment_date"]).strip(),
        "effective_status": str(raw.get("effective_status", "待核实")).strip(),
        "source_type": str(raw["source_type"]).strip(),
        "source_tier": int(raw["source_tier"]),
        "source_url": str(raw["source_url"]).strip(),
        "obtained_at": str(raw.get("obtained_at", "")).strip(),
        "disposition": str(raw.get("disposition", "")).strip(),
        "claimed_amount": raw.get("claimed_amount"),
        "awarded_amount": raw.get("awarded_amount"),
        "reasonable_expenses": raw.get("reasonable_expenses"),
        "punitive_damages": 1 if raw.get("punitive_damages") else 0,
        "punitive_multiplier": raw.get("punitive_multiplier"),
        "law_version_status": str(raw.get("law_version_status", "待核实")).strip(),
        "review_status": str(raw.get("review_status", "机器提取")).strip(),
        "full_text": str(raw["full_text"]).strip(),
        "is_active": 1 if raw.get("is_active", True) else 0,
        "created_at": existing_created_at or now,
        "updated_at": now,
    }
    for field in JSON_OBJECT_FIELDS:
        normalized[field] = json.dumps(raw.get(field, {}), ensure_ascii=False, sort_keys=True)
    for field in JSON_ARRAY_FIELDS:
        normalized[field] = json.dumps(raw.get(field, []), ensure_ascii=False)
    normalized["source_hash"] = str(raw.get("source_hash") or hashlib.sha256(
        normalized["full_text"].encode("utf-8")
    ).hexdigest())
    search_parts: list[str] = [
        normalized["title"],
        normalized["case_number"],
        normalized["court"],
        normalized["cause_of_action"],
        normalized["disposition"],
        normalized["full_text"],
    ]
    for field in JSON_OBJECT_FIELDS + JSON_ARRAY_FIELDS:
        search_parts.append(normalized[field])
    normalized["search_text"] = "\n".join(part for part in search_parts if part)
    return normalized


def upsert_case(conn: sqlite3.Connection, case: dict[str, Any], replace: bool = False) -> str:
    current = conn.execute(
        "SELECT created_at FROM cases WHERE case_id = ?", (case["case_id"],)
    ).fetchone()
    if current and not replace:
        raise ValueError(f"case_id 已存在：{case['case_id']}，如需更新请使用 --replace")
    duplicate = conn.execute(
        "SELECT case_id FROM cases WHERE source_hash = ? AND case_id <> ?",
        (case["source_hash"], case["case_id"]),
    ).fetchone()
    if duplicate:
        raise ValueError(f"正文与现有案例 {duplicate['case_id']} 重复")
    if current:
        case["created_at"] = current["created_at"]
        conn.execute("DELETE FROM cases WHERE case_id = ?", (case["case_id"],))
        action = "updated"
    else:
        action = "inserted"
    placeholders = ", ".join("?" for _ in CASE_COLUMNS)
    conn.execute(
        f"INSERT INTO cases ({', '.join(CASE_COLUMNS)}) VALUES ({placeholders})",
        tuple(case[column] for column in CASE_COLUMNS),
    )
    # 大型案例库可选择不携带三元组 FTS 索引以控制仓库体积；此时保留
    # 结构化表，关键词检索器仍可正常工作，后续导入也不应因此失败。
    fts_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases_fts'"
    ).fetchone()
    if fts_exists:
        conn.execute("DELETE FROM cases_fts WHERE case_id = ?", (case["case_id"],))
        conn.execute(
            "INSERT INTO cases_fts(case_id, title, case_number, court, cause_of_action, search_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                case["case_id"],
                case["title"],
                case["case_number"],
                case["court"],
                case["cause_of_action"],
                case["search_text"],
            ),
        )
    return action


def load_input(path: str | Path) -> list[dict[str, Any]]:
    input_path = Path(path).expanduser().resolve()
    text = input_path.read_text(encoding="utf-8-sig")
    if input_path.suffix.lower() == ".jsonl":
        result = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        result = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(item, dict) for item in result):
        raise ValueError("输入必须是 JSON 对象、JSON 对象数组或 JSONL")
    return result


def parse_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for field in JSON_OBJECT_FIELDS + JSON_ARRAY_FIELDS:
        try:
            item[field] = json.loads(item[field])
        except (TypeError, json.JSONDecodeError):
            pass
    item["punitive_damages"] = bool(item.get("punitive_damages"))
    return item


def query_terms(query: str) -> list[str]:
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query.lower())
    seen: set[str] = set()
    return [part for part in parts if not (part in seen or seen.add(part))]


def snippet(text: str, terms: Iterable[str], radius: int = 70) -> str:
    lower = text.lower()
    positions = [lower.find(term.lower()) for term in terms]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return text[: radius * 2].replace("\n", " ")
    start = max(0, min(positions) - radius)
    end = min(len(text), start + radius * 2)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix
