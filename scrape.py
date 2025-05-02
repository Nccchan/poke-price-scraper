#!/usr/bin/env python3
"""
GitHub Actions で毎朝 06:00 JST に実行。
Playwright でメルカリ検索ページを開き、
__NEXT_DATA__ の JSON から販売中商品の中央値を latest.csv に追記します。
先頭 3 件の JSON を preview.txt に書き出してデバッグ用に残します。
"""

import json, re, csv, sys, time, datetime as dt
from pathlib import Path
from statistics import median
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── キーワードと表示名だけ変更 ──────────────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────────────────────

CSV_FILE    = Path("latest.csv")
NAV_TIMEOUT = 60_000  # ms


# ───── dict / list を再帰して price を集める ────────────────
def recursive_find_prices(obj) -> list[int] | None:
    if isinstance(obj, dict):
        if "price" in obj and isinstance(obj["price"], int):
            return [obj["price"]]
        out = []
        for v in obj.values():
            r = recursive_find_prices(v)
            if r:
                out.extend(r)
        return out or None
    if isinstance(obj, list):
        out = []
        for v in obj:
            r = recursive_find_prices(v)
            if r:
                out.extend(r)
        return out or None
    return None


# ───── Playwright でページ取得 → 価格リスト返却 ───────────
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

        # __NEXT_DATA__ 文字列取得
        raw = page.eval_on_selector('script#__NEXT_DATA__',
                                    'el => el.textContent')

        # DOM 版の価格も保険で取得
        dom_texts = page.eval_on_selector_all(
            '[data-testid="item-price"]',
            'els => els.map(e => e.textContent)'
        )
        browser.close()

    # ---------- JSON 解析 -----------------------------------
    prices: list[int] = []
    try:
        data = json.loads(raw)

        # ★ デバッグ: 先頭 3 件をファイルへ書き出し ★
        preview = (
            data.get("props", {})
                .get("pageProps", {})
                .get("initialState", {})
                .get("search", {})
                .get("items", [])
        )[:3]
        Path("preview.txt").write_text(
            json.dumps(preview, ensure_ascii=False, indent=2)[:2000],
            encoding="utf-8"
        )
        print("[DEBUG] preview.txt を生成しました（Artifacts で確認できます）")
        # ------------------------------------------------------

        found = recursive_find_prices(data)
        if found:
            prices = [int(v) for v in found]
    except Exception as e:
        print("[WARN] JSON parse failed:", e)

    # ---------- JSON で取得できなければ DOM を使用 ----------
    if not prices and dom_texts:
        prices = [
            int(re.sub(r"[^\d]", "", t))
            for t in dom_texts if re.search(r"\d", t)
        ]

    prices.sort()
    print(f"[INFO] price count = {len(prices)}")

    # 外れ値 10 % カット
    if len(prices) >= 10:
        k = len(prices) // 10
        prices = prices[k: len(prices) - k]
    return prices


# ───── CSV 追記 ───────────────────────────────────────────
def append_csv(date: str, product: str, price: int | None):
    header = ["Date", "Product", "PriceJPY"]
    need_header = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(header)
        w.writerow([date, product, price if price is not None else "NA"])


# ───── メイン ────────────────────────────────────────────
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
