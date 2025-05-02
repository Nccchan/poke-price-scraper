#!/usr/bin/env python3
"""
GitHub Actions で毎朝 06:00 JST に実行。
Playwright でメルカリ検索ページを開き、
__NEXT_DATA__ の JSON から販売中商品の中央値を latest.csv に追記します。
"""

import json, re, csv, sys, time, datetime as dt
from pathlib import Path
from statistics import median
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── キーワードと表示名をここで設定 ───────────────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────────────────────────

CSV_FILE    = Path("latest.csv")
NAV_TIMEOUT = 60_000

def fetch_prices(keyword: str) -> list[int]:
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(locale="ja-JP")
        page.set_default_navigation_timeout(NAV_TIMEOUT)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)
        except PWTimeout:
            browser.close()
            return []

        # __NEXT_DATA__ の JSON を取得
        raw = page.eval_on_selector(
            'script#__NEXT_DATA__',
            'el => el.textContent'
        )
        browser.close()

    data = json.loads(raw)
    # items は data.props.pageProps.initialState.search.items
    try:
        items = (data["props"]["pageProps"]["initialState"]
                      ["search"]["items"])
    except KeyError:
        items = []

    prices = [item["price"] for item in items if item.get("status") == "on_sale"]
    prices.sort()
    print(f"[INFO] JSON から取得した件数 = {len(prices)}")

    if len(prices) >= 10:
        k = len(prices) // 10
        prices = prices[k : len(prices) - k]
    return prices


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
        med = round(median(prices)) if prices else None
        append_csv(today, PRODUCT_NAME, med)
        print(f"Appended {today}, price={med}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
