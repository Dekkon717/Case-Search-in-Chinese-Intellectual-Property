"""运行固定知识产权检索回测，形成可重复的回归检查。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def run_case(search_script: Path, db: Path, case: dict[str, object], top_k: int) -> dict[str, object]:
    command = [
        sys.executable,
        str(search_script),
        "--db",
        str(db),
        "--query",
        str(case["query"]),
        "--matter",
        str(case.get("matter", "civil")),
        "--limit",
        str(top_k),
        "--json",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "search_cases.py 执行失败")
    payload = json.loads(completed.stdout)
    result_ids = [str(item["case_id"]) for item in payload.get("results", [])]
    expected = [str(item) for item in case.get("expected_ids", [])]
    hits = [case_id for case_id in expected if case_id in result_ids]
    non_matter = [item["case_id"] for item in payload.get("results", []) if item.get("matter") != case.get("matter", "civil")]
    passed = len(hits) >= int(case.get("min_expected_hits", 1)) and not non_matter
    return {
        "name": case["name"],
        "query": case["query"],
        "matter": case.get("matter", "civil"),
        "top_ids": result_ids,
        "expected_hits": hits,
        "expected_hit_count": len(hits),
        "non_matter_ids": non_matter,
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行固定知识产权检索回测")
    parser.add_argument("--db", required=True)
    parser.add_argument("--fixture", default=str(Path(__file__).resolve().parents[1] / "tests" / "backtest-fixtures.json"))
    parser.add_argument("--out")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    cases = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    search_script = Path(__file__).resolve().with_name("search_cases.py")
    results = [run_case(search_script, Path(args.db).resolve(), case, args.top_k) for case in cases]
    repo_root = Path(__file__).resolve().parents[1]
    def display_path(value: str) -> str:
        resolved = Path(value).resolve()
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError:
            return resolved.name
    payload = {
        "run_date": date.today().isoformat(),
        "fixture": display_path(args.fixture),
        "database": display_path(args.db),
        "top_k": args.top_k,
        "case_count": len(results),
        "passed_count": sum(bool(item["passed"]) for item in results),
        "pass": all(bool(item["passed"]) for item in results),
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
