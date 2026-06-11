"""Cron から web service の /internal/weekly-improve を叩くトリガー。

Render の Cron Job は永続ディスクにアクセスできないため、
GSC 取得・リライト・DB 書き込みは disk を持つ web service 側で実行する。
（scripts/daily_publish.py と同じ方式）
"""

import json
import os
import sys
import urllib.error
import urllib.request


def main():
    # Cloudflare が前段にいる場合、cron は .onrender.com 直URL を叩く。
    target = os.environ.get("CRON_TARGET_URL") or os.environ.get("SITE_URL", "")
    target = target.rstrip("/")
    secret = os.environ.get("CRON_SECRET")

    if not target:
        print("[weekly_improve] CRON_TARGET_URL / SITE_URL not set", file=sys.stderr)
        sys.exit(1)
    if not secret:
        print("[weekly_improve] CRON_SECRET not set", file=sys.stderr)
        sys.exit(1)

    url = f"{target}/internal/weekly-improve"
    print(f"[weekly_improve] POST {url}")

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Cron-Secret": secret,
            "Content-Type": "application/json",
            "User-Agent": "seo-blog-weekly-improve/1.0",
        },
        data=b"{}",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")
            print(f"[weekly_improve] HTTP {resp.status}: {body}")
            if resp.status >= 400:
                sys.exit(1)
            parsed = json.loads(body) if body else {}
            if parsed.get("status") == "error":
                sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[weekly_improve] HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[weekly_improve] URL error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
