"""performance_logs の最新スナップショットから記事ごとの performance_score を算出する。

performance_score = 実測CTR / 掲載順位帯の期待CTR
  1.0 = 順位相応のクリック率。< 1.0 はタイトル・メタ説明に改善余地がある。
  インプレッションが少なすぎる記事は CTR が信頼できないため 0 とする。
"""

from models import get_db

# 掲載順位帯ごとの期待CTR（業界調査ベースの概算値。絶対値ではなく
# 「改善余地があるか」の相対判定にのみ使う）
EXPECTED_CTR_BANDS = [
    (1.5, 0.28),
    (2.5, 0.15),
    (3.5, 0.10),
    (5.5, 0.07),
    (10.5, 0.03),
    (20.5, 0.012),
]
DEFAULT_EXPECTED_CTR = 0.004

# これ未満のインプレッションでは CTR を評価しない
MIN_IMPRESSIONS_FOR_SCORE = 20


def expected_ctr(position: float) -> float:
    """掲載順位に対する期待CTRを返す。"""
    for upper, ctr in EXPECTED_CTR_BANDS:
        if position <= upper:
            return ctr
    return DEFAULT_EXPECTED_CTR


def update_scores() -> dict:
    """最新スナップショットを使って articles.performance_score を更新する。"""
    conn = get_db()
    latest = conn.execute(
        "SELECT MAX(date) AS d FROM performance_logs WHERE source='gsc'"
    ).fetchone()["d"]
    if not latest:
        conn.close()
        return {"updated": 0, "reason": "no_gsc_data"}

    rows = conn.execute(
        """SELECT article_id, impressions, ctr, position
           FROM performance_logs WHERE date=? AND source='gsc'""",
        (latest,),
    ).fetchall()

    updated = 0
    for r in rows:
        if r["impressions"] >= MIN_IMPRESSIONS_FOR_SCORE:
            score = round(r["ctr"] / expected_ctr(r["position"]), 3)
        else:
            score = 0.0
        conn.execute(
            "UPDATE articles SET performance_score=? WHERE id=?",
            (score, r["article_id"]),
        )
        updated += 1

    conn.commit()
    conn.close()
    return {"updated": updated, "snapshot_date": latest}
