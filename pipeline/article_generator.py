"""Claude API を使って記事を生成する。"""

import json
import re
from datetime import datetime

import anthropic
import markdown

from config import ANTHROPIC_API_KEY
from models import get_db


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-6"


def generate_article(keyword: str, keyword_id: int) -> int | None:
    """キーワードから記事を生成し、DBに保存して article_id を返す。"""

    # 1. 既存記事のタイトル一覧を取得（内部リンク用）
    conn = get_db()
    existing = conn.execute(
        "SELECT slug, title FROM articles WHERE status='published'"
    ).fetchall()
    existing_titles = [
        {"slug": r["slug"], "title": r["title"]} for r in existing
    ]
    conn.close()

    # 2. 記事を生成
    content_md = _generate_content(keyword, existing_titles)
    if not content_md:
        return None

    # 3. メタデータを生成
    meta = _generate_meta(keyword, content_md)

    # 4. Markdown → HTML
    content_html = markdown.markdown(
        content_md,
        extensions=["tables", "fenced_code", "toc"],
    )

    # 5. 内部リンクを挿入
    content_html = _insert_internal_links(content_html, existing_titles)

    # 6. DBに保存
    slug = meta["slug"]
    word_count = len(content_md.split())
    now = datetime.utcnow().isoformat()

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO articles
            (slug, title, meta_description, content_html, content_markdown,
             category, target_keyword, status, published_at, updated_at, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)""",
            (
                slug,
                meta["title"],
                meta["description"],
                content_html,
                content_md,
                meta["category"],
                keyword,
                now,
                now,
                word_count,
            ),
        )
        article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "UPDATE keywords SET status='published', assigned_article_id=? WHERE id=?",
            (article_id, keyword_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return article_id


def _generate_content(keyword: str, existing_titles: list[dict]) -> str:
    """Claude API で記事本文を生成する。"""

    existing_list = "\n".join(
        f"- {t['title']} (/{t['slug']})" for t in existing_titles[:20]
    )

    prompt = f"""Write a comprehensive, SEO-optimized article about: "{keyword}"

Requirements:
- Write 2000-3000 words in English
- Use Markdown formatting with H2 (##) and H3 (###) headings
- Include a comparison table in Markdown table format
- Include Pros and Cons for each tool mentioned
- Include a "Verdict" or "Our Pick" section at the end
- Write in a helpful, authoritative tone (use "we" perspective)
- Naturally mention that tools can be tried through links in the article
- Do NOT include the article title as H1 (it's handled by the template)

Existing articles on this site (link to relevant ones naturally):
{existing_list if existing_list else "No existing articles yet."}

Output ONLY the Markdown article body. No frontmatter, no title heading."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _generate_meta(keyword: str, content_md: str) -> dict:
    """Claude API でメタデータを生成する。"""

    prompt = f"""Based on this article about "{keyword}", generate SEO metadata.

Article (first 500 chars): {content_md[:500]}

Return a JSON object with:
- "title": SEO title, max 60 characters, include the main keyword
- "description": Meta description, max 155 characters, include a call to action
- "slug": URL slug, lowercase, hyphens, no special characters, max 60 chars
- "category": one of "comparison", "review", "guide", "listicle"

Return ONLY valid JSON, no explanation."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Extract JSON from possible markdown code block
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    return json.loads(text)


def _insert_internal_links(html: str, existing_titles: list[dict]) -> str:
    """記事HTML内に内部リンクを挿入する。"""
    for item in existing_titles[:5]:
        title = item["title"]
        slug = item["slug"]
        # タイトル内のキーワードが本文に出現していたらリンク化（最初の1回のみ）
        for word in title.split()[:3]:
            if len(word) < 4:
                continue
            pattern = re.compile(rf"\b({re.escape(word)})\b", re.IGNORECASE)
            if pattern.search(html):
                link = f'<a href="/{slug}">{word}</a>'
                html = pattern.sub(link, html, count=1)
                break
    return html
