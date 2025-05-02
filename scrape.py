#!/usr/bin/env python3
"""
Playwright でメルカリ検索ページを開き、
__NEXT_DATA__ の JSON から販売中商品の価格を取り出すテスト版。
必ずデバッグ行を print してログに残す。
"""

import json, re, sys, time, datetime as dt
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path

from playwright.sync_api import sync_playwright

# ── ここだけ自由に変えて OK ────────────────────────
KEYWORD = "ロケット団の栄光 BOX シュリンク付き"
# ────────────────────────────────────────────────

def fetch_prices(keyword: str) -> list[int]:
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )

    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # __NEXT_DATA__ を取得
        raw = page.eval_on_selector('script#__NEXT_DATA__', 'el => el.textContent')
        # DOM 価格も保険で取得
        dom_texts = page.eval_on_selector_all(
            '[data-testid="item-price"]', 'els => els.map(e => e.textContent)'
        )

    # ---------- デバッグ: 取れた長さだけまず表示 -----------------
    print(f"[DEBUG] raw JSON length = {len(raw)}")
    print(f"[DEBUG] DOM price texts = {len(dom_texts)} 件")
    sys.stdout.flush()          # ← バッファに残らないよう即出力
    # -------------------------------------------------------------

    try:
        data = json.loads(raw)
    except Exception as e:
        print("[ERROR] json.loads failed:", e)
        return []

    # JSON の先頭 3 件だけ抜く（パス固定せずツリー再帰）
    def rec(obj):
        if isinstance(obj, dict):
            if "price" in obj:
                return [obj]
            out = []
            for v in obj.values():
                r = rec(v)
                if r: out.extend(r)
            return out
        if isinstance(obj, list):
            out = []
            for v in obj:
                r = rec(v)
                if r: out.extend(r)
            return out
        return []

    items = rec(data)[:3]
    print("[DEBUG] preview JSON first 3 =", json.dumps(items, ensure_ascii=False)[:500])
    sys.stdout.flush()

    # price 抜き出し
    prices = [it["price"] for it in items if "price" in it]
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
