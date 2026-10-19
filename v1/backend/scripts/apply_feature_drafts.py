"""管理 shop_feature_drafts —— 查看 / 确认 / 应用到 shops

Examples:
  python scripts/apply_feature_drafts.py --list-pending --limit 30
  python scripts/apply_feature_drafts.py --approve-confidence 0.75
  python scripts/apply_feature_drafts.py --apply-approved
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from app.services.feature_draft_repository import (
    approve_by_confidence,
    apply_approved_to_shops,
    list_drafts,
    update_draft_status,
)


def cmd_list_pending(limit: int):
    """列出 pending 草稿."""
    drafts = list_drafts(status="pending", limit=limit)
    if not drafts:
        print("没有 pending 草稿")
        return
    for d in drafts:
        print(
            f"draft_id={d['id']} shop_id={d['shop_id']} name={d['shop_name']} "
            f"price={d['avg_price']} confidence={d.get('confidence', 0):.2f} "
            f"tastes={d.get('tastes_json')} scenes={d.get('scenes_json')}"
        )
    print(f"\n共 {len(drafts)} 条 pending 草稿（限制 {limit}）")


def cmd_approve_confidence(min_conf: float):
    """按置信度批量确认."""
    n = approve_by_confidence(min_conf)
    print(f"已将 {n} 条 confidence >= {min_conf} 的 pending drafts 标记为 approved")


def cmd_apply_approved():
    """将 approved drafts 写入 shops."""
    n = apply_approved_to_shops()
    print(f"已将 {n} 条 approved drafts 写入 shops 正式字段")


def main():
    parser = argparse.ArgumentParser(description="管理 shop_feature_drafts")
    parser.add_argument("--list-pending", action="store_true", help="列出 pending 草稿")
    parser.add_argument("--limit", type=int, default=30, help="最大显示数量（默认 30）")
    parser.add_argument("--approve-confidence", type=float, default=None,
                        help="按置信度批量确认（例如 0.75）")
    parser.add_argument("--apply-approved", action="store_true",
                        help="将 approved drafts 写入 shops 正式字段")
    parser.add_argument("--approve-id", type=int, default=None,
                        help="手动确认单条 draft")
    parser.add_argument("--reject-id", type=int, default=None,
                        help="手动拒绝单条 draft")
    args = parser.parse_args()

    if args.list_pending:
        cmd_list_pending(args.limit)
        return

    if args.approve_id is not None:
        update_draft_status(args.approve_id, "approved")
        print(f"draft_id={args.approve_id} → approved")
        return

    if args.reject_id is not None:
        update_draft_status(args.reject_id, "rejected")
        print(f"draft_id={args.reject_id} → rejected")
        return

    if args.approve_confidence is not None:
        cmd_approve_confidence(args.approve_confidence)
        return

    if args.apply_approved:
        cmd_apply_approved()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
