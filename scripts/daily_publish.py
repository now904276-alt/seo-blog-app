"""毎日1記事を自動生成・公開するCronスクリプト。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import init_db
from pipeline.keyword_researcher import (
    discover_keywords,
    load_seed_keywords,
    pick_next_keyword,
)
from pipeline.article_generator import generate_article


def main():
    print("[daily_publish] Starting...")
    init_db()

    # 1. キーワードプールが空なら、シードから補充
    kw = pick_next_keyword()
    if not kw:
        print("[daily_publish] Keyword pool empty. Discovering from seeds...")
        seeds = load_seed_keywords()
        added = discover_keywords(seeds)
        print(f"[daily_publish] Added {added} keywords from seeds.")
        kw = pick_next_keyword()

    if not kw:
        print("[daily_publish] No keywords available. Skipping.")
        return

    print(f"[daily_publish] Generating article for: {kw['keyword']}")

    # 2. 記事生成
    try:
        article_id = generate_article(kw["keyword"], kw["id"])
        if article_id:
            print(f"[daily_publish] Published article #{article_id}")
        else:
            print("[daily_publish] Article generation returned None.")
    except Exception as e:
        print(f"[daily_publish] Error: {e}")
        raise


if __name__ == "__main__":
    main()
