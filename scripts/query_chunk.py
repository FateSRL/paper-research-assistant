"""根据准确 chunk ID 回查 SQLite；读取时不创建数据库、不写日志。"""

import argparse
import json
from pathlib import Path
import sqlite3

from paper_assistant.storage import PaperStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data/index/papers.sqlite3"


def main() -> int:
    parser = argparse.ArgumentParser(description="从 SQLite 回查 chunk 原文和论文来源")
    parser.add_argument("--chunk-id", required=True)
    args = parser.parse_args()
    try:
        with PaperStore(DATABASE_PATH, read_only=True) as store:
            chunk = store.get_chunk(args.chunk_id)
        if chunk is None:
            print(f"[NOT FOUND] 数据库中没有这个 chunk ID：{args.chunk_id}")
            return 2
        # 原文存在换行时 JSON 会转义显示，值本身保持原样；用 text 输出便于阅读。
        text = chunk.pop("text")
        print(json.dumps(chunk, ensure_ascii=False, indent=2))
        print("\n--- 保存的原文 ---")
        print(text)
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
