"""Google Autocomplete からロングテールキーワードを取得し、DBに保存する。"""

import json
import urllib.request
import urllib.parse
from datetime import datetime
from models import get_db


def fetch_autocomplete(seed: str) -> list[str]:
    """Google Autocomplete API からサジェストを取得する。"""
    url = (
        "https://suggestqueries.google.com/complete/search?"
        f"client=firefox&q={urllib.parse.quote(seed)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    return data[1] if len(data) > 1 else []


def discover_keywords(seeds: list[str]) -> int:
    """シードキーワードからサジェストを取得し、新規のものをDBに保存する。"""
    conn = get_db()
    added = 0

    for seed in seeds:
        suggestions = fetch_autocomplete(seed)
        for kw in suggestions:
            kw = kw.strip().lower()
            if not kw:
                continue
            existing = conn.execute(
                "SELECT id FROM keywords WHERE keyword=?", (kw,)
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO keywords (keyword, status, source, discovered_at) "
                "VALUES (?, 'pool', 'autocomplete', ?)",
                (kw, datetime.utcnow().isoformat()),
            )
            added += 1

    conn.commit()
    conn.close()
    return added


def load_seed_keywords(path: str = "admin/seed_keywords.json") -> list[str]:
    """シードキーワードファイルを読み込む。"""
    with open(path) as f:
        return json.load(f)


def pick_next_keyword() -> dict | None:
    """DBからまだ使われていないキーワードを1件選ぶ。既存記事と被りにくいものを優先。"""
    conn = get_db()

    # 既存記事のキーワードを取得して、似たテーマを避ける
    existing = conn.execute(
        "SELECT target_keyword FROM articles WHERE status='published'"
    ).fetchall()
    existing_words = set()
    for row in existing:
        for word in row["target_keyword"].lower().split():
            if len(word) > 3:
                existing_words.add(word)

    # プールから候補を取得
    candidates = conn.execute(
        "SELECT id, keyword FROM keywords "
        "WHERE status='pool' ORDER BY discovered_at ASC LIMIT 50"
    ).fetchall()

    if not candidates:
        conn.close()
        return None

    # 既存記事との重複度が低いものを優先
    best = None
    best_overlap = 999
    for c in candidates:
        words = set(w for w in c["keyword"].lower().split() if len(w) > 3)
        overlap = len(words & existing_words)
        if overlap < best_overlap:
            best_overlap = overlap
            best = c

    if not best:
        best = candidates[0]

    conn.execute(
        "UPDATE keywords SET status='assigned' WHERE id=?", (best["id"],)
    )
    conn.commit()
    conn.close()
    return {"id": row["id"], "keyword": row["keyword"]}
