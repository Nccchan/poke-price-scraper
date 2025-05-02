#!/usr/bin/env python3
"""
GitHub Actions で毎朝 06:00 JST に実行。
Playwright でメルカリ検索ページを開き、
販売中商品の中央値を latest.csv に追記します。
"""

import json, re, csv, sys, time, datetime as dt
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── ここを書き換えれば他はそのまま ─────────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ───────────────────────────────────────────────────────

CSV_FILE    = Path("latest.csv")
NAV_TIMEOUT = 90_000   # ms  (= 90 秒)

def fetch_prices(keyword: str) -> list[int]:
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )

    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page(locale="ja-JP")
        page.set_default_navigation_timeout(NAV_TIMEOUT)

        # ページ読み込み
        page.goto(url, wait_until="domcontentloaded")

        # 商品カードが出るまで待つ
        page.wait_for_selector('[data-testid="item-cell"]',
                               timeout=NAV_TIMEOUT)

        # 追加ロードのため自動スクロール
        for _ in range(10):              # 10 × 1000 px ≒ 1 万 px
            page.mouse.wheel(0, 1_000)
            time.sleep(0.6)

        time.sleep(2)                    # Ajax 描画完了待ち

        # 価格スパンが描画されるまで最大 15 秒待機
        try:
            page.wait_for_selector('[data-testid="item-price"]',
                                   timeout=15_000)
        except PWTimeout:
            print("[WARN] price spans not found (15 s timeout)")

        # DOM から価格を取得
        dom_prices = [
            int(re.sub(r"[^\d]", "", t))
            for t in page.locator('[data-testid="item-price"]')
                         .all_text_contents()
            if re.search(r"\d", t)
        ]
        print(f"[DEBUG] DOM price count = {len(dom_prices)}")

        # 保険として __NEXT_DATA__ の JSON も解析
        raw = page.locator('script#__NEXT_DATA__').text_content()
    # ここで Playwright セッション終了

    json_prices = []
    try:
        data = json.loads(raw)

        # 再帰して price を集める
        def rec(o):
            if isinstance(o, dict):
                if "price" in o and isinstance(o["price"], int):
                    return [o]
                out = []
                for v in o.values():
                    out += rec(v)
                return out
            if isinstance(o, list):
                out = []
                for v in o:
                    out += rec(v)
                return out
            return []

        items = rec(data)
        json_prices = [
            it["price"] for it in items
            if it.get("status") in ("STATUS_ON_SALE", "on_sale")
        ]
        print(f"[DEBUG] JSON price count = {len(json_prices)}")
    except Exception as e:
        print("[WARN] JSON parse error:", e)

    # JSON が優先、無ければ DOM
    prices = json_prices or dom_prices
    prices.sort()

    # 外れ値 10 % カット
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
        print("[ERROR]", e, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
