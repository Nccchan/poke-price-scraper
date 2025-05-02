#!/usr/bin/env python3
"""
毎朝 06:00 JST に実行される GitHub Actions 用。
メルカリ公式の公開 API から
『ロケット団の栄光 BOX（シュリンク付き）』販売中商品の中央値を取り、
latest.csv に追記します。
"""

import json, time, datetime as dt, csv, sys
from pathlib import Path
import requests

# ── ここだけキーワードを変えれば他はそのまま動きます ─────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────

API_URL = "https://api.mercari.jp/v2/entities:search"
HEADERS = {
    "User-Agent":   "MercariScraper/1.0",
    "Content-Type": "application/json",
    # これが無いと 400 になる
    "X-Platform":   "web"
}

CSV_FILE = Path("latest.csv")


def fetch_prices(keyword: str) -> list[int]:
    """公式 API で販売中商品の価格リスト(int) を返す"""
    time.sleep(1)                               # polite delay
    payload = {
        "pageToken": "",
        "pageSize": 120,                        # 最高 120 件
        "searchSessionId": "",
        "indexRouting": "INDEX_ROUTING_SEARCH",
        "thumbnailTypes": ["THUMBNAIL_TYPE_WEB"],
        "keyword": keyword,
        "sort": "SORT_SCORE",
        "order": "ORDER_DESC",
        "statusIds": ["STATUS_ON_SALE"]         # 販売中のみ
    }
    r = requests.post(API_URL, headers=HEADERS,
                      data=json.dumps(payload), timeout=20)
    r.raise_for_status()
    js = r.json()
    return [item["price"] for item in js.get("items", [])]


def median(lst: list[int]) -> int | None:
    if not lst:
        return None
    s = sorted(lst)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) // 2


def append_csv(date: str, product: str, price: int | None):
    header = ["Date", "Product", "PriceJPY"]
    need_header = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(header)
        w.writerow([date, product, price if price is not None else "NA"])


def main():
    today = dt.date.today().isoformat()
    try:
        prices = fetch_prices(KEYWORD)
        med = median(prices)
        append_csv(today, PRODUCT_NAME, med)
        print(f"Appended {today}, price={med}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
