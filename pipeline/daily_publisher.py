"""Daily publish のコアロジック。app.py のエンドポイントから呼ばれる。"""

from models import init_db
from pipeline.keyword_researcher import (
    discover_keywords,
    load_seed_keywords,
    pick_next_keyword,
)
from pipeline.article_generator import generate_article


def run_daily_publish() -> dict:
    """1記事生成・公開し、結果を dict で返す。"""
    init_db()

    kw = pick_next_keyword()
    if not kw:
        seeds = load_seed_keywords()
        added = discover_keywords(seeds)
        kw = pick_next_keyword()
        if not kw:
            return {"status": "skipped", "reason": "no_keywords", "seeds_added": added}

    article_id = generate_article(kw["keyword"], kw["id"])
    if not article_id:
        return {"status": "error", "reason": "generation_returned_none", "keyword": kw["keyword"]}

    return {"status": "published", "article_id": article_id, "keyword": kw["keyword"]}
