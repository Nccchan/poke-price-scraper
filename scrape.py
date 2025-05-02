#!/usr/bin/env python3
"""
Enhanced Playwright script for Mercari search scraping.
Improves reliability with better selectors and fallback mechanisms.
"""

import json, re, csv, sys, time, datetime as dt
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── ここを書き替えて他はそのまま ─────────────────────
KEYWORD      = "ロケット団の栄光 BOX シュリンク付き"
PRODUCT_NAME = "ロケット団の栄光 BOX（シュリンク付き）"
# ────────────────────────────────────────────────

CSV_FILE    = Path("latest.csv")
NAV_TIMEOUT = 90_000   # ms
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

def fetch_prices(keyword: str) -> list[int]:
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )
    
    prices = []
    with sync_playwright() as p:
        # ブラウザを起動し、より現実的なユーザーエージェントを設定
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_navigation_timeout(NAV_TIMEOUT)
        
        try:
            # Cookieバナーなどを回避するためのテクニック
            page.goto(url, wait_until="domcontentloaded")
            print(f"[INFO] Navigated to: {url}")
            
            # 複数のセレクタを試す (旧セレクタと新セレクタの両方)
            selectors = [
                '[data-testid="item-cell"]',
                '.merItemThumbnail',
                'mer-item-thumbnail',
                '[data-location="search"] [data-testid="thumbnail"]',
                ".merItem"
            ]
            
            # いずれかのセレクタが見つかるまで待機
            for selector in selectors:
                try:
                    print(f"[INFO] Trying selector: {selector}")
                    page.wait_for_selector(selector, timeout=20000)
                    print(f"[INFO] Found items with selector: {selector}")
                    break
                except PWTimeout:
                    print(f"[INFO] Selector not found: {selector}")
            
            # よりゆっくりと、段階的にスクロール
            for step in range(1, 5):
                print(f"[INFO] Scroll step {step}")
                page.mouse.wheel(0, 1000)
                time.sleep(3)  # スクロール間の待機時間を長めに
            
            # 複数の価格セレクタを試す
            price_selectors = [
                '[data-testid="item-price"]',
                '.merPrice',
                '.merItemThumbnail__price',
                '.merItem__price',
                '[data-location="search"] [data-testid="price"]'
            ]
            
            # DOM から価格を取得する試み
            dom_prices = []
            for price_selector in price_selectors:
                try:
                    print(f"[INFO] Trying price selector: {price_selector}")
                    page.wait_for_selector(price_selector, timeout=15000)
                    
                    # JavaScript を使って要素のテキストを取得
                    texts = page.eval_on_selector_all(
                        price_selector,
                        'els => els.map(e => e.textContent)'
                    )
                    
                    if texts:
                        print(f"[INFO] Found {len(texts)} prices with selector: {price_selector}")
                        
                        # 価格テキストから数字だけを抽出
                        dom_prices = [
                            int(re.sub(r"[^\d]", "", t))
                            for t in texts
                            if re.search(r"\d", t)
                        ]
                        
                        if dom_prices:
                            print(f"[DEBUG] DOM price count = {len(dom_prices)}")
                            break
                except Exception as e:
                    print(f"[WARN] Error with price selector {price_selector}: {e}")
            
            # ページのHTML全体をデバッグ用に確認（問題が続く場合）
            if not dom_prices:
                print("[INFO] No prices found with selectors, checking page content")
                html = page.content()
                # 価格パターンを直接検索 (¥XXX,XXX または￥XXX,XXX の形式)
                price_pattern = r'[¥￥]([0-9,]+)'
                direct_prices = re.findall(price_pattern, html)
                if direct_prices:
                    print(f"[INFO] Found {len(direct_prices)} prices with direct regex")
                    dom_prices = [
                        int(re.sub(r"[^\d]", "", p))
                        for p in direct_prices
                        if re.search(r"\d", p)
                    ]
                    if dom_prices:
                        print(f"[DEBUG] Direct regex price count = {len(dom_prices)}")
            
            # JSON からの抽出を試みる
            json_prices = []
            try:
                # __NEXT_DATA__ スクリプトタグからJSONを抽出
                raw_data = page.locator('script#__NEXT_DATA__').text_content() or ""
                if raw_data:
                    data = json.loads(raw_data)
                    
                    # 再帰的に価格情報を検索
                    def recurse(o):
                        if isinstance(o, dict):
                            if "price" in o and isinstance(o["price"], int):
                                return [o]
                            out = []
                            for v in o.values():
                                out += recurse(v)
                            return out
                        if isinstance(o, list):
                            out = []
                            for v in o:
                                out += recurse(v)
                            return out
                        return []
                    
                    items = recurse(data)
                    json_prices = [
                        it["price"] for it in items
                        if it.get("status") in ("STATUS_ON_SALE", "on_sale") or "status" not in it
                    ]
                    print(f"[DEBUG] JSON price count = {len(json_prices)}")
                
                # APIレスポンスもチェック
                for req in page.request.all():
                    if req.url and "api" in req.url and "search" in req.url:
                        try:
                            resp = req.response()
                            if resp:
                                resp_text = resp.text()
                                resp_json = json.loads(resp_text)
                                api_items = recurse(resp_json)
                                api_prices = [
                                    it["price"] for it in api_items
                                    if "price" in it and isinstance(it["price"], int)
                                ]
                                if api_prices:
                                    print(f"[DEBUG] API price count = {len(api_prices)}")
                                    json_prices.extend(api_prices)
                        except Exception as e:
                            print(f"[WARN] Error parsing API response: {e}")
            
            except Exception as e:
                print(f"[WARN] JSON parse error: {e}")
            
            # 最終的な価格リストを作成（JSONとDOMのどちらかが取れた方を使用）
            prices = json_prices or dom_prices
            print(f"[DEBUG] final DOM price count = {len(dom_prices)}")
            print(f"[DEBUG] final JSON price count = {len(json_prices)}")
            
            # スクリーンショットを撮影してデバッグ（必要に応じて）
            try:
                screenshot_path = Path("debug_screenshot.png")
                page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] Screenshot saved to {screenshot_path}")
            except Exception as e:
                print(f"[WARN] Failed to save screenshot: {e}")
                
        except Exception as e:
            print(f"[ERROR] Navigation/scraping error: {e}")
        
        finally:
            browser.close()
    
    # 価格リストを処理
    if prices:
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
        if prices:
            med = round(median(prices))
            append_csv(today, PRODUCT_NAME, med)
            print(f"Appended {today}, price={med}")
        else:
            print("[WARN] No prices found, appending NA")
            append_csv(today, PRODUCT_NAME, None)
            print(f"Appended {today}, price=None")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
