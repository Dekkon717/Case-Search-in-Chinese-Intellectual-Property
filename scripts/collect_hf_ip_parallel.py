"""并行下载法院裁判文书语料分片，并筛选知识产权文书。"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq


KEYWORDS = ("知识产权", "商标", "著作权", "版权", "专利", "不正当竞争", "商业秘密", "植物新品种", "集成电路布图")


def fetch(item: dict, dataset: str, cache: Path) -> tuple[str, list[dict]]:
    rel = str(item["path"])
    local = cache / Path(rel).name
    url = f"https://huggingface.co/datasets/{dataset}/resolve/main/{rel}"
    for attempt in range(1, 5):
        try:
            if not local.exists() or local.stat().st_size == 0:
                local.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(url, timeout=120) as response:
                    local.write_bytes(response.read())
            table = pq.read_table(local, columns=["source", "date", "text", "token_count", "category"])
            selected: list[dict] = []
            for row_index, row in enumerate(table.to_pylist()):
                if row.get("source") != "common_corpus_Chinese-Court-Decisions":
                    continue
                text = str(row.get("text") or "")
                if any(word in text for word in KEYWORDS):
                    row.update({"dataset": dataset, "shard_path": rel, "row_index": row_index})
                    selected.append(row)
            return rel, selected
        except Exception:
            if local.exists():
                local.unlink()
            if attempt == 4:
                raise
            time.sleep(attempt * 2)
    raise RuntimeError(rel)


def main() -> int:
    parser = argparse.ArgumentParser(description="并行筛选公开法院裁判文书语料中的知识产权记录")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dataset", default="TheFinAI/corpus-shard-20")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max", type=int, default=10000)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    cache = Path(args.cache)
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, item, args.dataset, cache) for item in manifest]
        for done_index, future in enumerate(as_completed(futures), start=1):
            rel, selected = future.result()
            rows.extend(selected)
            print(f"[{done_index}/{len(futures)}] {rel}: +{len(selected)}, total={len(rows)}", flush=True)
            if len(rows) >= args.max:
                break
    rows = rows[: args.max]
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": len(rows), "out": str(Path(args.out).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
