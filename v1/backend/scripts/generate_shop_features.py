"""DeepSeek 半自动补齐店铺推荐特征

Examples:
  python scripts/generate_shop_features.py --list-gaps --limit 30
  python scripts/generate_shop_features.py --limit 10 --dry-run
  python scripts/generate_shop_features.py --limit 30
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from app.services.feature_gap_service import compute_data_quality_score, list_missing_fields, needs_feature_completion
from app.services.feature_draft_repository import save_draft


def _connect():
    db_path = os.getenv("SQLITE_DB_PATH", str(Path(BACKEND_ROOT) / "data" / "chedian.db"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_gaps(limit: int):
    """列出缺失推荐特征的店铺."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM shops ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    count = 0
    for row in rows:
        shop = dict(row)
        if not needs_feature_completion(shop):
            continue
        if count >= limit:
            break
        missing = list_missing_fields(shop)
        score = compute_data_quality_score(shop)
        print(
            f"shop_id={shop['id']} name={shop['name']} "
            f"missing={','.join(missing)} quality={score}"
        )
        count += 1

    print(f"\n显示 {count} 条缺失店铺（限制 {limit}）")


def generate(limit: int, dry_run: bool):
    """为缺失特征的店铺用 DeepSeek 生成候选特征."""
    from app.services.deepseek_feature_service import generate_feature_draft

    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM shops ORDER BY id").fetchall()
    finally:
        conn.close()

    count = 0
    skipped = 0
    failed = 0

    for row in rows:
        shop = dict(row)
        if not needs_feature_completion(shop):
            continue
        if count >= limit:
            break

        missing = list_missing_fields(shop)
        print(f"[{count + 1}/{limit}] shop_id={shop['id']} name={shop['name']} missing={','.join(missing)}")

        if dry_run:
            count += 1
            continue

        result = generate_feature_draft(shop)
        if result is None:
            print(f"  -> 生成失败，跳过")
            failed += 1
            continue

        ok = save_draft(shop["id"], shop["name"], result)
        if ok:
            print(
                f"  -> saved | price={result.get('avg_price')} "
                f"tastes={result.get('tastes')} scenes={result.get('scenes')} "
                f"confidence={result.get('confidence', 0):.2f}"
            )
            count += 1
        else:
            skipped += 1

        # 避免请求过快
        import time
        time.sleep(0.5)

    if dry_run:
        print(f"\n[dry-run] 将生成 {count} 条候选特征（限制 {limit}）")
    else:
        print(f"\n生成完成: 成功={count} 失败={failed} 跳过={skipped}")


def main():
    parser = argparse.ArgumentParser(description="DeepSeek 半自动补齐店铺推荐特征")
    parser.add_argument("--list-gaps", action="store_true", help="列出缺失推荐特征的店铺")
    parser.add_argument("--limit", type=int, default=30, help="最大处理数量（默认 30）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不调 DeepSeek / 不写库")
    args = parser.parse_args()

    if args.list_gaps:
        list_gaps(args.limit)
        return

    # 检查 DeepSeek API key
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not args.dry_run and not key:
        print("错误: 未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置")
        sys.exit(1)

    print(f"Generate shop features: limit={args.limit} dry_run={args.dry_run}")
    generate(args.limit, args.dry_run)


if __name__ == "__main__":
    main()
