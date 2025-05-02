#!/usr/bin/env python3
import json, re, csv, sys, time, datetime as dt
from pathlib import Path
from statistics import median
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
CSV_FILE     = Path("latest.csv")
NAV_TIMEOUT  = 60_000

def recursive_find_prices(obj) -> list[int] | None:
    """dict/list ツリーのどこかにある 'price' を集めた list を返す"""
    if isinstance(obj, dict):
        if "price" in obj:          # アイテム 1 件
            return [obj["price"]]
        out = []
        for v in obj.values():
            r = recursive_find_prices(v)
            if r:
                out.extend(r)
        return out or None
    elif isinstance(obj, list):
        out = []
        for v in obj:
            r = recursive_find_prices(v)
            if r:
                out.extend(r)
        return out or None
    return None

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

        raw = page.eval_on_selector('script#__NEXT_DATA__', 'el => el.textContent')
        soup_prices = page.eval_on_selector_all(
            '[data-testid="item-price"]',
            'els => els.map(e => e.textContent)'
        )
        browser.close()

    # --- JSON 側を優先 -------------------------------------------------
    prices = []
    try:
        data = json.loads(raw)
        found = recursive_find_prices(data)
        if found:
            prices = [int(v) for v in found if isinstance(v, int)]
    except Exception:
        pass

    # --- JSON で取れなければ DOM の価格を使う --------------------------
    if not prices and soup_prices:
        prices = [
            int(re.sub(r"[^\d]", "", t))
            for t in soup_prices if re.search(r"\d", t)
        ]

    prices.sort()
    print(f"[INFO] price count = {len(prices)}")
    if len(prices) >= 10:
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
        print("[ERROR]", e, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
