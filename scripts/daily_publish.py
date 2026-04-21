"""Cron から web service の /internal/daily-publish を叩くトリガー。

Render の Cron Job は永続ディスクにアクセスできないため、
記事生成・DB 書き込みは disk を持つ web service 側で実行する。
"""

import json
import os
import sys
import urllib.error
import urllib.request


def main():
    site_url = os.environ.get("SITE_URL", "").rstrip("/")
    secret = os.environ.get("CRON_SECRET")

    if not site_url:
        print("[daily_publish] SITE_URL not set", file=sys.stderr)
        sys.exit(1)
    if not secret:
        print("[daily_publish] CRON_SECRET not set", file=sys.stderr)
        sys.exit(1)

    url = f"{site_url}/internal/daily-publish"
    print(f"[daily_publish] POST {url}")

    req = urllib.request.Request(
        url,
        method="POST",
        headers={"X-Cron-Secret": secret, "Content-Type": "application/json"},
        data=b"{}",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")
            print(f"[daily_publish] HTTP {resp.status}: {body}")
            if resp.status >= 400:
                sys.exit(1)
            parsed = json.loads(body) if body else {}
            if parsed.get("status") == "error":
                sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[daily_publish] HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[daily_publish] URL error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
