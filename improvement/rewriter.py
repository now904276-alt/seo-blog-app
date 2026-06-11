"""パフォーマンスデータに基づいて記事を自動改善する。

改善ルール（優先順）:
  1. meta:    インプレッションがあるのに CTR が期待値の半分未満
              → title / meta_description のみ書き換え（安い・効果が出やすい）
  2. expand:  掲載順位 5〜20 位でインプレッションあり
              → 本文を拡充（不足トピック + FAQ 追記）して上位を狙う
  3. rewrite: 公開60日超でインプレッションほぼゼロ
              → 切り口を変えて全面リライト

コスト制御: 1回の実行で最大 MAX_ACTIONS_PER_RUN 本まで。
効果測定のため、直近 COOLDOWN_DAYS 日以内に改善した記事は対象外。
"""

import json
import re
from datetime import datetime, timedelta

import anthropic
import markdown

from config import ANTHROPIC_API_KEY
from models import get_db
from improvement.scorer import expected_ctr
from pipeline.article_generator import _insert_internal_links

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-6"

MAX_ACTIONS_PER_RUN = 5
COOLDOWN_DAYS = 21

# ルール閾値
META_MIN_IMPRESSIONS = 100
META_CTR_RATIO = 0.5
EXPAND_MIN_IMPRESSIONS = 50
EXPAND_POSITION_RANGE = (5, 20)
REWRITE_MIN_AGE_DAYS = 60
REWRITE_MAX_IMPRESSIONS = 10

MD_EXTENSIONS = ["tables", "fenced_code", "toc"]


def select_candidates(conn) -> list[dict]:
    """最新スナップショットと記事情報から改善対象を選ぶ。"""
    latest = conn.execute(
        "SELECT MAX(date) AS d FROM performance_logs WHERE source='gsc'"
    ).fetchone()["d"]
    if not latest:
        return []

    cooldown_cutoff = (
        datetime.utcnow() - timedelta(days=COOLDOWN_DAYS)
    ).isoformat()
    age_cutoff = (
        datetime.utcnow() - timedelta(days=REWRITE_MIN_AGE_DAYS)
    ).isoformat()

    rows = conn.execute(
        """SELECT a.id, a.slug, a.title, a.meta_description, a.content_markdown,
                  a.target_keyword, a.published_at, a.last_reviewed_at,
                  COALESCE(p.impressions, 0) AS impressions,
                  COALESCE(p.ctr, 0) AS ctr,
                  COALESCE(p.position, 0) AS position
           FROM articles a
           LEFT JOIN performance_logs p
             ON p.article_id = a.id AND p.date = ? AND p.source = 'gsc'
           WHERE a.status = 'published'
           ORDER BY COALESCE(p.impressions, 0) DESC""",
        (latest,),
    ).fetchall()

    candidates = []
    for r in rows:
        if r["last_reviewed_at"] and r["last_reviewed_at"] > cooldown_cutoff:
            continue

        action = None
        if (
            r["impressions"] >= META_MIN_IMPRESSIONS
            and r["ctr"] < META_CTR_RATIO * expected_ctr(r["position"])
        ):
            action = "meta"
        elif (
            EXPAND_POSITION_RANGE[0] <= r["position"] <= EXPAND_POSITION_RANGE[1]
            and r["impressions"] >= EXPAND_MIN_IMPRESSIONS
        ):
            action = "expand"
        elif (
            r["impressions"] <= REWRITE_MAX_IMPRESSIONS
            and r["published_at"]
            and r["published_at"] < age_cutoff
        ):
            action = "rewrite"

        if action:
            candidates.append({**dict(r), "action": action})

    # meta → expand → rewrite の優先順、各グループ内はインプレッション降順
    order = {"meta": 0, "expand": 1, "rewrite": 2}
    candidates.sort(key=lambda c: (order[c["action"]], -c["impressions"]))
    return candidates[:MAX_ACTIONS_PER_RUN]


def improve_articles() -> dict:
    """改善対象を選んで実行する。"""
    conn = get_db()
    candidates = select_candidates(conn)
    if not candidates:
        conn.close()
        return {"improved": 0, "reason": "no_candidates"}

    existing = conn.execute(
        "SELECT slug, title FROM articles WHERE status='published'"
    ).fetchall()
    existing_titles = [{"slug": r["slug"], "title": r["title"]} for r in existing]

    results = []
    for c in candidates:
        try:
            if c["action"] == "meta":
                _improve_meta(conn, c)
            elif c["action"] == "expand":
                _expand_content(conn, c, existing_titles)
            else:
                _full_rewrite(conn, c, existing_titles)
            results.append({"slug": c["slug"], "action": c["action"], "ok": True})
        except (anthropic.APIError, json.JSONDecodeError, KeyError) as e:
            conn.rollback()
            results.append(
                {"slug": c["slug"], "action": c["action"], "ok": False,
                 "error": type(e).__name__}
            )

    conn.close()
    return {"improved": sum(1 for r in results if r["ok"]), "results": results}


def _mark_reviewed(conn, article_id: int):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE articles
           SET rewrite_count = rewrite_count + 1,
               last_reviewed_at = ?, updated_at = ?
           WHERE id = ?""",
        (now, now, article_id),
    )
    conn.commit()


def _improve_meta(conn, c: dict):
    """CTR が低い記事の title / meta_description を書き換える。"""
    prompt = f"""You are improving SEO metadata for an article that ranks but gets few clicks.

Target keyword: "{c['target_keyword']}"
Current title: {c['title']}
Current meta description: {c['meta_description']}
Average position: {c['position']:.1f} / CTR: {c['ctr'] * 100:.2f}% (below expectation for this position)

Write a more compelling title and meta description. Be specific (numbers, concrete benefits), include the keyword naturally, no clickbait.

Return ONLY valid JSON: {{"title": "max 60 chars", "description": "max 155 chars"}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    meta = json.loads(match.group() if match else text)

    conn.execute(
        "UPDATE articles SET title=?, meta_description=? WHERE id=?",
        (meta["title"], meta["description"], c["id"]),
    )
    _mark_reviewed(conn, c["id"])


def _expand_content(conn, c: dict, existing_titles: list[dict]):
    """順位 5〜20 位の記事に不足トピックと FAQ を追記する。"""
    prompt = f"""This article ranks at position {c['position']:.1f} for "{c['target_keyword']}" and needs deeper coverage to reach the top results.

Current article (Markdown):
{c['content_markdown']}

Write ADDITIONAL Markdown sections to append to this article:
- 1-2 sections covering important subtopics the article is missing
- A "## Frequently Asked Questions" section with 4-6 concise Q&As (### for each question)
- Use specific, concrete details (pricing, limits, features as of 2026)
- Do NOT repeat content already in the article
- The current year is 2026

Output ONLY the new Markdown sections. No preamble."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    addition = response.content[0].text.strip()

    combined_md = c["content_markdown"].rstrip() + "\n\n" + addition + "\n"
    html = markdown.markdown(combined_md, extensions=MD_EXTENSIONS)
    html = _insert_internal_links(html, existing_titles)

    conn.execute(
        "UPDATE articles SET content_markdown=?, content_html=?, word_count=? WHERE id=?",
        (combined_md, html, len(combined_md.split()), c["id"]),
    )
    _mark_reviewed(conn, c["id"])


def _full_rewrite(conn, c: dict, existing_titles: list[dict]):
    """インプレッションがつかない古い記事を、切り口を変えて全面リライトする。"""
    prompt = f"""This article gets almost no search impressions and needs a complete rewrite with a fresh, more specific angle.

Target keyword: "{c['target_keyword']}"
Old article (for reference, do not copy its structure):
{c['content_markdown'][:3000]}

Rewrite requirements:
- Write 2000-3000 words in English, Markdown with ## and ### headings
- Pick ONE clearly distinct angle that better matches search intent for the keyword
- Include a comparison table, pros & cons, specific pricing/limits as of 2026
- Include a "## Frequently Asked Questions" section with 4-6 Q&As
- End with a "## Verdict" section with a clear recommendation
- The current year is 2026. Never use 2024 or 2025.
- Do NOT include the article title as H1

Output ONLY the Markdown article body."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    new_md = response.content[0].text.strip()

    meta_prompt = f"""Based on this rewritten article about "{c['target_keyword']}", generate SEO metadata.

Article (first 500 chars): {new_md[:500]}

Return ONLY valid JSON: {{"title": "max 60 chars, include the keyword", "description": "max 155 chars with a call to action"}}"""

    meta_response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": meta_prompt}],
    )
    text = meta_response.content[0].text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    meta = json.loads(match.group() if match else text)

    html = markdown.markdown(new_md, extensions=MD_EXTENSIONS)
    html = _insert_internal_links(html, existing_titles)

    # slug は変えない（URL の安定性を優先）
    conn.execute(
        """UPDATE articles
           SET title=?, meta_description=?, content_markdown=?, content_html=?,
               word_count=? WHERE id=?""",
        (meta["title"], meta["description"], new_md, html,
         len(new_md.split()), c["id"]),
    )
    _mark_reviewed(conn, c["id"])
