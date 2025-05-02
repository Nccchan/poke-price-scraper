#!/usr/bin/env python3
"""
GitHub Actions で毎朝 06:00 JST に実行。
Playwright でメルカリ検索ページを開き、
販売中商品の中央値を latest.csv に追記します。
"""

import re, csv, sys, time, datetime as dt
from pathlib import Path
from statistics import median
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── キーワードと表示名だけ必要に応じて変更 ───────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────────────

CSV_FILE    = Path("latest.csv")
NAV_TIMEOUT = 60_000         # ms

def fetch_prices(keyword: str) -> list[int]:
    """Playwright で検索ページを開き、販売中価格の int リストを返す"""
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

        def try_once() -> list[int]:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)

            # 自動スクロールで追加商品をロード
            for _ in range(8):          # 8×1000px = 8000px
                page.mouse.wheel(0, 1000)
                time.sleep(0.5)

            # DOM から価格をすべて取得
            texts = page.eval_on_selector_all(
                'li[data-testid="item-cell"] span',
                'els => els.map(e => e.textContent)'
            )
            prices = [
                int(re.sub(r"[^\d]", "", t))
                for t in texts if re.search(r"¥\\s*\\d", t)
            ]
            return prices

        try:
            prices = try_once()
        except PWTimeout:
            prices = []

        browser.close()

    if not prices:
        print("[WARN] 価格が 0 件でした。キーワードや待機時間を調整してください。")
        return []

    prices.sort()
    if len(prices) >= 10:           # 外れ値 10 % カット
        k = len(prices) // 10
        prices = prices[k: len(prices) - k]
    print(f"[INFO] ヒット件数 = {len(prices)}")
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
