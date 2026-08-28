"""从公开 Hugging Face Parquet 分片中筛选来源为中国裁判文书的知识产权文书。

数据集 TheFinAI/corpus-shard-20 的原始语料许可为 Apache-2.0；其中
``common_corpus_Chinese-Court-Decisions`` 行明确标注为中国法院裁判文书。
本脚本只保留文本中出现知识产权案由/权利关键词的记录，并输出原文与来源
分片路径，便于后续去重和回溯。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq


KEYWORDS = (
    "知识产权",
    "商标",
    "著作权",
    "版权",
    "专利",
    "不正当竞争",
    "商业秘密",
    "植物新品种",
    "集成电路布图",
)


def download(url: str, target: Path, retries: int = 4) -> None:
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                target.write_bytes(response.read())
            return
        except Exception:
            if target.exists():
                target.unlink()
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def main() -> int:
    parser = argparse.ArgumentParser(description="筛选法院裁判文书语料中的知识产权记录")
    parser.add_argument("--manifest", required=True, help="Hugging Face API 导出的 parquet 清单 JSON")
    parser.add_argument("--cache", required=True, help="分片缓存目录")
    parser.add_argument("--out", required=True, help="筛选结果 JSON")
    parser.add_argument("--dataset", default="TheFinAI/corpus-shard-20")
    parser.add_argument("--max", type=int, default=10000, help="最多保留多少条")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    candidates: list[dict] = []
    cache = Path(args.cache)
    for index, item in enumerate(manifest, start=1):
        rel = str(item["path"])
        url = f"https://huggingface.co/datasets/{args.dataset}/resolve/main/{rel}"
        local = cache / Path(rel).name
        print(f"[{index}/{len(manifest)}] {rel}", flush=True)
        download(url, local)
        table = pq.read_table(local, columns=["source", "date", "text", "token_count", "category"])
        for row_index, row in enumerate(table.to_pylist()):
            if row.get("source") != "common_corpus_Chinese-Court-Decisions":
                continue
            text = str(row.get("text") or "")
            if not any(word in text for word in KEYWORDS):
                continue
            row["dataset"] = args.dataset
            row["shard_path"] = rel
            row["row_index"] = row_index
            candidates.append(row)
            if len(candidates) >= args.max:
                break
        if len(candidates) >= args.max:
            break
        print(f"  selected={len(candidates)}", flush=True)
    Path(args.out).write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": len(candidates), "out": str(Path(args.out).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
