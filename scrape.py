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

# ── キーワードと表示名だけ編集 ──────────────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ──────────────────────────────────────────────────

CSV_FILE = Path("latest.csv")
NAV_TIMEOUT = 60_000        # navigation / selector 待ちを 60 秒に拡張


def _collect_prices(page) -> list[int]:
    """page から価格テキストを抜き出して数値リストを返す"""
    texts = page.eval_on_selector_all(
        'li[data-testid="item-cell"] span',
        'els => els.map(e => e.textContent)'
    )
    return [
        int(re.sub(r"[^\d]", "", t))
        for t in texts if re.search(r"¥\s*\d", t)
    ]


def fetch_prices(keyword: str) -> list[int]:
    """Playwright で検索ページを開き、販売中商品の価格リストを返す"""
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(locale="ja-JP")
        page.set_default_navigation_timeout(NAV_TIMEOUT)

        def try_once() -> list[int] | None:
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT)
                for _ in range(6):     # 自動スクロール
                    page.mouse.wheel(0, 1000)
                    time.sleep(0.4)
                return _collect_prices(page)
            except PWTimeout:
                return None

        prices = try_once()
        if not prices:           # 1 回目失敗なら 5 秒待ってもう 1 度
            time.sleep(5)
            prices = try_once()

        browser.close()

    prices.sort()
    if len(prices) >= 10:        # 外れ値 10 % を削除
        k = len(prices) // 10
        prices = prices[k: len(prices) - k]
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
