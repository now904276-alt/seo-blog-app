"""近重複記事の301集約を適用する。

admin/consolidation-plan.json の redirects マッピング（旧slug → 集約先slug）を読み、
未適用の記事を status='redirected' に変更する。冪等（適用済みはスキップ）なので
weekly improver の起動時に毎回呼んでよい。
"""

import json
import os
from datetime import datetime

from models import get_db

PLAN_PATH = "admin/consolidation-plan.json"


def apply_consolidation_plan() -> dict:
    """計画ファイルの未適用リダイレクトを適用する。"""
    if not os.path.exists(PLAN_PATH):
        return {"applied": 0, "reason": "no_plan_file"}

    with open(PLAN_PATH) as f:
        redirects = json.load(f).get("redirects", {})
    if not redirects:
        return {"applied": 0, "reason": "empty_plan"}

    conn = get_db()
    applied = 0
    skipped_missing_target = 0
    now = datetime.utcnow().isoformat()

    for old_slug, target_slug in redirects.items():
        # 集約先が公開状態で実在することを確認（リダイレクトチェーン・行き止まり防止）
        target = conn.execute(
            "SELECT id FROM articles WHERE slug=? AND status='published'",
            (target_slug,),
        ).fetchone()
        if not target:
            skipped_missing_target += 1
            continue

        # 未適用（まだ published のまま）の旧記事だけ更新する
        cur = conn.execute(
            """UPDATE articles
               SET status='redirected', redirect_to=?, updated_at=?
               WHERE slug=? AND status='published'""",
            (target_slug, now, old_slug),
        )
        applied += cur.rowcount

    conn.commit()
    conn.close()
    return {
        "applied": applied,
        "skipped_missing_target": skipped_missing_target,
        "plan_size": len(redirects),
    }
