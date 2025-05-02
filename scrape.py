#!/usr/bin/env python3
import json, re, sys, datetime as dt
from statistics import median
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

KEYWORD = "ロケット団の栄光 BOX シュリンク付き"

def fetch_prices(keyword: str) -> list[int]:
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page()
        page.set_default_navigation_timeout(90_000)          # ← 90 秒
        page.goto(url, wait_until="domcontentloaded")         # ← 変更
        # 価格スパンを先に拾う（保険）
        dom_prices = [
            int(re.sub(r"[^\d]", "", t))
            for t in page.locator('[data-testid="item-price"]').all_text_contents()
            if re.search(r"\d", t)
        ]
        # __NEXT_DATA__ を読む
        raw = page.locator('script#__NEXT_DATA__').text_content()

    print(f"[DEBUG] DOM price count = {len(dom_prices)}")
    data = json.loads(raw)
    items = (
        data.get("props", {})
            .get("pageProps", {})
            .get("results", {})            # ← initialState に無い場合はこちら
            .get("items", [])
    )
    print(f"[DEBUG] JSON items first 3 =",
          json.dumps(items[:3], ensure_ascii=False)[:400])

    json_prices = [
        it.get("price") for it in items
        if isinstance(it.get("price"), int)
        and it.get("status") in ("STATUS_ON_SALE", "on_sale")
    ]
    prices = json_prices or dom_prices
    return prices

def main():
    prices = fetch_prices(KEYWORD)
    print("[RESULT] prices =", prices)
    if prices:
        print("[RESULT] median =", median(prices))
    else:
        print("[RESULT] median = None")

if __name__ == "__main__":
    main()
