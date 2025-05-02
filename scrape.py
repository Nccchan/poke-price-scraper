#!/usr/bin/env python3
import re, time, datetime as dt, csv, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = ("https://jp.mercari.com/search"
       "?keyword=%E3%83%AD%E3%82%B1%E3%83%83%E3%83%88%E5%9B%A3%E3%81%AE%E6%A0%84%E5%85%89%20BOX%20%E3%82%B7%E3%83%A5%E3%83%AA%E3%83%B3%E3%82%AF%E4%BB%98%E3%81%8D"
       "&sort=score&order=desc&item_status=on_sale")

product_name = "ロケット団の栄光 BOX（シュリンク付き）"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PriceScraper/1.0)",
    "Accept-Language": "ja,en-US;q=0.9",
}

CSV_FILE = Path("latest.csv")

def fetch_prices(url: str) -> list[int]:
    time.sleep(1)                              # polite delay
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
       print("HTML length =", len(res.text))

    soup = BeautifulSoup(res.text, "lxml")
    price_texts = soup.find_all(text=re.compile(r"¥\d[\d,]*"))
    prices = [int(p.replace("¥", "").replace(",", "")) for p in price_texts]
    prices.sort()
    n = len(prices)
    if n >= 10:                                # 中央 ±10% で外れ値除去
        k = n // 10
        prices = prices[k:n - k]
    return prices

def median(lst: list[int]) -> int | None:
    if not lst:
        return None
    m = len(lst) // 2
    s = sorted(lst)
    return s[m] if len(lst) % 2 else sum(s[m - 1:m + 1]) // 2

def append_csv(date: str, product: str, price: int | None):
    header = ["Date", "Product", "PriceJPY"]
    need_header = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(header)
        w.writerow([date, product, price or "NA"])

def main():
    today = dt.date.today().isoformat()
    product = "テラスタルフェス BOX（シュリンク付き）"
    try:
        prices = fetch_prices(URL)
        med = median(prices)
        append_csv(today, product, med)
        print(f"Appended {today}, price={med}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
