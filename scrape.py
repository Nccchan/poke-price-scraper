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

from playwright.sync_api import sync_playwright

# ── キーワードと表示名をここで設定 ───────────────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────────────────────────

CSV_FILE = Path("latest.csv")


def fetch_prices(keyword: str) -> list[int]:
    """Playwright でメルカリ検索 → 販売中価格のリストを返す"""
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        page.goto(url, timeout=30_000)
        # ネットワークが静かになるまで待機
        page.wait_for_load_state("networkidle")

        # ── 自動スクロールで追加商品をロード ──────────────────
        for _ in range(6):            # 6×1000px ≒ 6000px
            page.mouse.wheel(0, 1000)
            time.sleep(0.4)           # Ajaxロード待ち
        # ──────────────────────────────────────────────────

        # DOM から価格テキストを全部取得
        texts = page.eval_on_selector_all(
            'li[data-testid="item-cell"] span',
            'els => els.map(e => e.textContent)'
        )
        browser.close()

    # "¥12,345" → 12345 に変換
    prices = [
        int(re.sub(r"[^\d]", "", t))
        for t in texts
        if re.search(r"¥\s*\d", t)
    ]
    prices.sort()

    # 外れ値 10% を除外
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
