"""Google Search Console から検索パフォーマンスを取得し performance_logs に保存する。

API: webmasters v3 / searchanalytics.query
https://developers.google.com/webmaster-tools/v1/searchanalytics/query
認証: サービスアカウント（JSON キーを GSC_SERVICE_ACCOUNT_JSON 環境変数で渡す。
サービスアカウントのメールアドレスを GSC プロパティのユーザーに追加しておくこと）
"""

import json
import os
from datetime import date, timedelta
from urllib.parse import urlparse

from google.oauth2 import service_account
from googleapiclient.discovery import build

from models import get_db

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
LOOKBACK_DAYS = 28
# GSC のデータは直近数日分が未確定のため、集計終端を3日前にする
DATA_LAG_DAYS = 3
DEFAULT_PROPERTY = "https://aidewalt.com/"


def _get_service():
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GSC_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("webmasters", "v3", credentials=creds, cache_discovery=False)


def _url_to_slug(page_url: str) -> str | None:
    """記事URLを slug に変換する。記事ページ以外（トップ・カテゴリ等）は None。"""
    path = urlparse(page_url).path.strip("/")
    if not path or "/" in path:
        return None
    return path


def fetch_search_performance() -> dict:
    """直近28日のページ別パフォーマンスを取得して performance_logs に upsert する。

    スナップショット方式: 28日間の集計値を「集計終端日」の行として保存する。
    UNIQUE(article_id, date, source) により同日再実行は上書きになる。
    """
    site_url = os.environ.get("GSC_PROPERTY", DEFAULT_PROPERTY)
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=LOOKBACK_DAYS)

    service = _get_service()
    response = (
        service.searchanalytics()
        .query(
            siteUrl=site_url,
            body={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["page"],
                "rowLimit": 25000,
            },
        )
        .execute()
    )
    rows = response.get("rows", [])

    conn = get_db()
    articles = conn.execute("SELECT id, slug FROM articles").fetchall()
    slug_to_id = {r["slug"]: r["id"] for r in articles}

    matched = 0
    skipped = 0
    for row in rows:
        slug = _url_to_slug(row["keys"][0])
        article_id = slug_to_id.get(slug) if slug else None
        if not article_id:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO performance_logs
               (article_id, date, impressions, clicks, ctr, position, source)
               VALUES (?, ?, ?, ?, ?, ?, 'gsc')
               ON CONFLICT(article_id, date, source) DO UPDATE SET
                 impressions=excluded.impressions,
                 clicks=excluded.clicks,
                 ctr=excluded.ctr,
                 position=excluded.position""",
            (
                article_id,
                end.isoformat(),
                row.get("impressions", 0),
                row.get("clicks", 0),
                row.get("ctr", 0),
                row.get("position", 0),
            ),
        )
        matched += 1

    conn.commit()
    conn.close()
    return {
        "rows": len(rows),
        "matched": matched,
        "skipped": skipped,
        "window": f"{start.isoformat()} → {end.isoformat()}",
        "snapshot_date": end.isoformat(),
    }
