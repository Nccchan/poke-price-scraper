#!/usr/bin/env python3
import json, time, datetime as dt, csv, sys
from pathlib import Path
import requests

KEYWORD = "ロケット団の栄光 BOX シュリンク付き"
product_name = "ロケット団の栄光 BOX（シュリンク付き）"

API_URL = "https://api.mercari.jp/v2/entities:search"
HEADERS = {"User-Agent": "MercariScraper/1.0", "Content-Type": "application/json"}
CSV_FILE = Path("latest.csv")

def fetch_prices(keyword: str) -> list[int]:
    time.sleep(1)
    payload = {
        "query": keyword,
        "page_size": 120,
        "search_condition": {"status": ["on_sale"]},
        "sort": "score",
        "order": "desc"
    }
    res = requests.post(API_URL, headers=HEADERS, data=json.dumps(payload), timeout=20)
    res.raise_for_status()
    js = res.json()
    return [item["price"] for item in js.get("items", [])]

def median(lst: list[int]) -> int | None:
    if not lst:
        return None
    s = sorted(lst)
    m = len(s) // 2
    return s[m] if len(s) % 2 else sum(s[m-1:m+1]) // 2

def append_csv(date: str, product: str, price: int | None):
    header = ["Date", "Product", "PriceJPY"]
    need_header = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(header)
        w.writerow([date, product, price or "NA"])

def main():
    today = dt.date.today().isoformat()
    try:
        prices = fetch_prices(KEYWORD)
        med = median(prices)
        append_csv(today, product_name, med)
        print(f"Appended {today}, price={med}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
