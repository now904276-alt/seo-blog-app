"""GSC OAuth 認証の一回限りのセットアップ（ローカル実行専用・Render では使わない）。

Search Console プロパティの所有者アカウントで一度承認し、
リフレッシュトークン入りの認可情報 JSON を出力する。
出力された JSON の中身を Render の GSC_OAUTH_TOKEN_JSON に設定すると、
improvement/gsc_fetcher.py がそれを使って Search Analytics API を読む。

使い方:
  python scripts/gsc_oauth_setup.py <OAuthクライアントJSONのパス> <出力先トークンパス>

例:
  python scripts/gsc_oauth_setup.py ~/.secrets/gsc-oauth-client.json ~/.secrets/gsc-oauth-token.json

実行するとブラウザが開くので、Search Console の所有者アカウントで承認する。
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    client_path, out_path = sys.argv[1], sys.argv[2]

    flow = InstalledAppFlow.from_client_secrets_file(client_path, scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    if not creds.refresh_token:
        print("ERROR: refresh_token が取得できませんでした", file=sys.stderr)
        sys.exit(1)

    with open(out_path, "w") as f:
        f.write(creds.to_json())
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
