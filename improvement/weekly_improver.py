"""週次改善ループのオーケストレーター。app.py のエンドポイントから呼ばれる。

流れ: GSC データ取得 → スコア更新 → 改善対象の選定・リライト実行
"""

from improvement.gsc_fetcher import fetch_search_performance
from improvement.scorer import update_scores
from improvement.rewriter import improve_articles
from models import init_db


def run_weekly_improvement() -> dict:
    init_db()
    fetch_result = fetch_search_performance()
    score_result = update_scores()
    improve_result = improve_articles()
    return {
        "status": "completed",
        "fetch": fetch_result,
        "score": score_result,
        "improve": improve_result,
    }
