"""Google Autocomplete からロングテールキーワードを取得し、DBに保存する。"""

import json
import urllib.request
import urllib.parse
from datetime import datetime

import anthropic

from config import ANTHROPIC_API_KEY
from models import get_db

# 重複判定は分類タスクなので軽量モデルを使う
DEDUP_MODEL = "claude-haiku-4-5"
# 語彙類似度がこれ以上なら LLM 判定を待たずに重複としてスキップ
LEXICAL_SKIP_THRESHOLD = 0.6
# LLM 判定が使えないときの保守的な語彙類似度上限
LEXICAL_FALLBACK_THRESHOLD = 0.35
# 1回の選定で重複判定する候補の上限（コスト・時間の上限）
MAX_CANDIDATES_TO_CHECK = 15


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


def _lexical_similarity(a: str, b: str) -> float:
    """単語集合の Jaccard 類似度（3文字以下の語は無視）。"""
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _is_duplicate_topic(candidate: str, existing_keywords: list[str]) -> bool:
    """既存記事と実質的に重複するトピックかを LLM で判定する。

    語彙では区別できない近重複（例: "best ai writing tools for students" と
    "best ai writing tools for novels"）を捕捉する。判定に失敗した場合は
    保守的な語彙類似度しきい値にフォールバックする。
    """
    existing_list = "\n".join(f"- {k}" for k in existing_keywords[:100])
    prompt = f"""Existing article topics on an AI tools comparison blog:
{existing_list}

Candidate keyword for a NEW article: "{candidate}"

Would an article on the candidate keyword substantially duplicate any existing article (same tool category and audience, only superficial differences)? Answer with exactly one word: YES or NO."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=DEDUP_MODEL,
            max_tokens=4,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().upper()
        return answer.startswith("YES")
    except anthropic.APIError:
        # LLM が使えないときは語彙類似度を厳しめに適用して安全側に倒す
        max_sim = max(
            (_lexical_similarity(candidate, k) for k in existing_keywords),
            default=0.0,
        )
        return max_sim >= LEXICAL_FALLBACK_THRESHOLD


def pick_next_keyword() -> dict | None:
    """DBから次に書くキーワードを1件選ぶ。

    既存記事と重複するトピックは絶対評価でスキップする（rejected として記録）。
    全候補が重複なら None を返す（近重複を出すくらいなら休む）。
    """
    conn = get_db()

    existing_keywords = [
        r["target_keyword"]
        for r in conn.execute(
            "SELECT target_keyword FROM articles WHERE status='published'"
        ).fetchall()
    ]

    candidates = conn.execute(
        "SELECT id, keyword FROM keywords "
        "WHERE status='pool' ORDER BY discovered_at ASC LIMIT 50"
    ).fetchall()

    if not candidates:
        conn.close()
        return None

    checked = 0
    picked = None
    for c in candidates:
        if checked >= MAX_CANDIDATES_TO_CHECK:
            break

        # 1段目: 語彙類似度で明白な重複を弾く（API 呼び出し不要）
        max_sim = max(
            (_lexical_similarity(c["keyword"], k) for k in existing_keywords),
            default=0.0,
        )
        if max_sim >= LEXICAL_SKIP_THRESHOLD:
            conn.execute(
                "UPDATE keywords SET status='rejected' WHERE id=?", (c["id"],)
            )
            continue

        # 2段目: 意味的な重複を LLM で判定
        checked += 1
        if existing_keywords and _is_duplicate_topic(
            c["keyword"], existing_keywords
        ):
            conn.execute(
                "UPDATE keywords SET status='rejected' WHERE id=?", (c["id"],)
            )
            continue

        picked = c
        break

    if not picked:
        conn.commit()
        conn.close()
        return None

    conn.execute(
        "UPDATE keywords SET status='assigned' WHERE id=?", (picked["id"],)
    )
    conn.commit()
    conn.close()
    return {"id": picked["id"], "keyword": picked["keyword"]}
