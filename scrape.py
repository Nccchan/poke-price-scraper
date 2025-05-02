#!/usr/bin/env python3
"""
Git操作を組み込んだメルカリ価格収集ボット
CSVファイルを自動的にコミットしてリポジトリを更新
"""

import json, re, csv, sys, time, datetime as dt, os, random, subprocess
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── 検索対象商品リスト ─────────────────────────────
PRODUCTS = [
    {"name": "ロケット団の栄光 BOX", "keyword": "ロケット団の栄光 BOX シュリンク付"},
    {"name": "熱風のアリーナ BOX", "keyword": "ポケモンカード 熱風のアリーナ BOX シュリンク付"},
    {"name": "バトルパートナーズ BOX", "keyword": "ポケモンカード バトルパートナーズ BOX シュリンク付"},
    {"name": "テラスタルフェスティバル BOX", "keyword": "ポケモンカード テラスタルフェスティバル BOX シュリンク付"},
    {"name": "超電ブレイカー BOX", "keyword": "ポケモンカード 超電ブレイカー BOX シュリンク付"},
    # 他のカード商品を追加...
]
# ────────────────────────────────────────────────

# ── 設定パラメータ ─────────────────────────────────
CSV_FILE = Path("mercari_prices.csv")     # 結果CSV
STATE_FILE = Path("progress.json")        # 進捗状態ファイル
BATCH_SIZE = 3                            # バッチあたりの商品数
MAX_RETRIES = 3                           # 最大リトライ回数
NAV_TIMEOUT = 60_000                      # ナビゲーションタイムアウト(ms)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
REQUEST_DELAY_MIN = 5                     # リクエスト間の最小待機時間(秒)
REQUEST_DELAY_MAX = 10                    # リクエスト間の最大待機時間(秒)
MAX_ITEMS = 30                            # 取得する最大商品数
SCROLL_COUNT = 2                          # スクロール回数（ページ数の制限）
# ────────────────────────────────────────────────

def run_git_command(command):
    """Gitコマンドを実行する"""
    try:
        result = subprocess.run(command, shell=True, check=True, 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                              text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Git command failed: {e}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return None

def setup_git():
    """Git設定を行う"""
    # Gitユーザー設定
    run_git_command('git config --local user.name "github-actions[bot]"')
    run_git_command('git config --local user.email "41898282+github-actions[bot]@users.noreply.github.com"')
    print("[INFO] Git user configured")

def commit_files(date):
    """ファイルをGitリポジトリにコミットする"""
    # ファイルをステージングに追加
    print("[INFO] Adding files to Git staging area...")
    run_git_command(f'git add {CSV_FILE}')
    
    # 日別サマリーファイルが存在する場合は追加
    summary_file = Path(f"summary_{date}.csv")
    if summary_file.exists():
        run_git_command(f'git add {summary_file}')
    
    # コミットする
    print("[INFO] Committing changes...")
    commit_message = f"data: メルカリ価格データ更新 ({date})"
    run_git_command(f'git commit -m "{commit_message}"')
    
    # 変更をプッシュ
    print("[INFO] Pushing changes to remote repository...")
    push_result = run_git_command('git push')
    
    if push_result is not None:
        print("[INFO] Successfully pushed changes to Git repository")
    else:
        print("[ERROR] Failed to push changes to Git repository")

def load_state():
    """進捗状態を読み込む。存在しない場合は新規作成"""
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 状態ファイル読み込みエラー: {e}")
    
    # 初期状態
    return {
        "last_update": "",
        "completed": [],
        "results": {}
    }

def save_state(state):
    """進捗状態を保存"""
    try:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] 状態ファイル保存エラー: {e}")

def fetch_prices(keyword: str, retry_count=0) -> list[int]:
    """指定したキーワードでメルカリを検索し、販売中商品の価格リストを返す（ページ数制限あり）"""
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
        "&price_min=5000"     # 最低価格5,000円以上を指定
    )
    
    print(f"[INFO] 検索URL: {url}")
    
    prices = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_navigation_timeout(NAV_TIMEOUT)
        
        try:
            page.goto(url, wait_until="domcontentloaded")
            print(f"[INFO] ページ読み込み完了: {keyword}")
            
            # 初期表示の待機時間
            print("[INFO] 初期ページ表示待機中...")
            page.wait_for_timeout(5000)
            
            # 複数のセレクタを試す
            selectors = [
                '[data-testid="item-cell"]',
                '.merItemThumbnail',
                'mer-item-thumbnail',
                '[data-location="search"] [data-testid="thumbnail"]',
                ".merItem"
            ]
            
            # いずれかのセレクタが見つかるまで待機
            found_selector = None
            for selector in selectors:
                try:
                    print(f"[INFO] Trying selector: {selector}")
                    page.wait_for_selector(selector, timeout=15000)
                    print(f"[INFO] Found items with selector: {selector}")
                    found_selector = selector
                    break
                except PWTimeout:
                    print(f"[INFO] Selector not found: {selector}")
            
            # 制限されたスクロール回数で価格を収集
            print(f"[INFO] {SCROLL_COUNT}ページ分の商品データを収集します")
            for step in range(1, SCROLL_COUNT + 1):
                print(f"[INFO] Scroll step {step}/{SCROLL_COUNT}")
                page.mouse.wheel(0, 1000)
                time.sleep(2)  # スクロール後の待機
            
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
                    elements = page.locator(price_selector).all()
                    if elements:
                        texts = [elem.text_content() for elem in elements if elem.is_visible()]
                        
                        if texts:
                            print(f"[INFO] Found {len(texts)} prices with selector: {price_selector}")
                            
                            # 取得する最大商品数に制限
                            if len(texts) > MAX_ITEMS:
                                print(f"[INFO] 商品数を{MAX_ITEMS}に制限します")
                                texts = texts[:MAX_ITEMS]
                            
                            # 価格テキストから数字だけを抽出
                            for t in texts:
                                if t and re.search(r"\d", t):
                                    match = re.search(r'[¥￥]([0-9,]+)', t)
                                    if match:
                                        try:
                                            price_str = match.group(1).replace(',', '')
                                            price = int(price_str)
                                            dom_prices.append(price)
                                        except ValueError:
                                            pass
                            
                            if dom_prices:
                                print(f"[DEBUG] DOM price count = {len(dom_prices)}")
                                break
                except Exception as e:
                    print(f"[WARN] Error with price selector {price_selector}: {e}")
            
            # 価格が見つからない場合は正規表現で直接検索
            if not dom_prices:
                html = page.content()
                price_pattern = r'[¥￥]([0-9,]+)'
                direct_prices = re.findall(price_pattern, html)
                if direct_prices:
                    print(f"[INFO] Found {len(direct_prices)} prices with direct regex")
                    # 取得する最大商品数に制限
                    if len(direct_prices) > MAX_ITEMS:
                        direct_prices = direct_prices[:MAX_ITEMS]
                        
                    for p in direct_prices:
                        if re.search(r"\d", p):
                            try:
                                price = int(re.sub(r"[^\d]", "", p))
                                if 1000 <= price <= 100000:  # 妥当な価格範囲のみ
                                    dom_prices.append(price)
                            except ValueError:
                                pass
            
            prices = dom_prices
            
            # 十分なデータが集まったか確認
            if len(prices) >= 5:
                print(f"[INFO] {len(prices)}件の価格データを収集しました（十分なサンプル数）")
            elif prices:
                print(f"[WARN] 収集した価格データが少なめです（{len(prices)}件）")
            else:
                print(f"[ERROR] 価格データを収集できませんでした")
                
        except Exception as e:
            print(f"[ERROR] Navigation/scraping error: {e}")
            # リトライ処理
            if retry_count < MAX_RETRIES:
                retry_wait = (2 ** retry_count) * 5  # 指数バックオフ (5秒, 10秒, 20秒...)
                print(f"[INFO] {retry_wait}秒後にリトライします (試行 {retry_count+1}/{MAX_RETRIES})")
                time.sleep(retry_wait)
                return fetch_prices(keyword, retry_count + 1)
        
        finally:
            browser.close()
    
    # 価格リストを処理
    if prices:
        prices.sort()
        print(f"[DEBUG] 価格一覧（上位5件）: {prices[:5]}...")
        
        # 外れ値 10 % カット
        if len(prices) >= 10:
            k = len(prices) // 10
            prices = prices[k : len(prices) - k]
    
    return prices

def process_batch(products, state):
    """商品バッチを処理"""
    results = []
    
    for product in products:
        # 既に完了している商品はスキップ
        if product["name"] in state["completed"]:
            print(f"[INFO] スキップ: 「{product['name']}」は既に完了しています")
            price = state["results"].get(product["name"])
            if price is not None:
                results.append((product["name"], price))
            continue
        
        print(f"\n[INFO] 「{product['name']}」の価格を取得中...")
        
        try:
            prices = fetch_prices(product["keyword"])
            
            if prices:
                med = round(median(prices))
                results.append((product["name"], med))
                print(f"[INFO] 「{product['name']}」の中央値: {med}円（{len(prices)}件）")
                
                # 状態を更新
                state["completed"].append(product["name"])
                state["results"][product["name"]] = med
                save_state(state)
            else:
                print(f"[WARN] 「{product['name']}」の価格データがありません")
                results.append((product["name"], None))
                # 結果なしでも完了としてマーク
                state["completed"].append(product["name"])
                state["results"][product["name"]] = None
                save_state(state)
        
        except Exception as e:
            print(f"[ERROR] 「{product['name']}」の処理中にエラー: {e}")
        
        # 次の商品へ進む前に待機
        delay = random.randint(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        print(f"[INFO] {delay}秒間待機中...")
        time.sleep(delay)
    
    return results

def append_csv(date, results):
    """
    見やすい形式でCSVに結果を追記
    各商品が別の行に記録され、どの商品がどの価格かが明確にわかる形式
    """
    need_header = not CSV_FILE.exists()
    
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        
        if need_header:
            w.writerow(["日付", "商品名", "中央値価格(円)", "データ件数"])
        
        # 各商品を別々の行として追加
        for product_name, price in results:
            row = [date, product_name, price if price is not None else "NA", ""]
            w.writerow(row)
    
    print(f"[INFO] CSV出力完了: {CSV_FILE}")

def generate_daily_summary(date, results):
    """日別サマリーCSVを生成"""
    summary_file = Path(f"summary_{date}.csv")
    
    with summary_file.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        
        # ヘッダー
        w.writerow(["収集日", date])
        w.writerow([])  # 空行
        w.writerow(["商品名", "中央値価格(円)"])
        
        # 商品の結果
        for product_name, price in sorted(results, key=lambda x: x[0]):
            w.writerow([product_name, price if price is not None else "データなし"])
    
    print(f"[INFO] 日別サマリー出力完了: {summary_file}")

def main():
    """メイン処理：バッチ処理で商品情報を取得、結果をGitにコミット"""
    # Git設定
    setup_git()
    
    today = dt.date.today().isoformat()
    
    # 状態を読み込み
    state = load_state()
    
    # 今日既に完了している場合はスキップ
    if state["last_update"] == today and len(state["completed"]) == len(PRODUCTS):
        print(f"[INFO] 本日 ({today}) の処理は既に完了しています")
        return
    
    # 日付が変わった場合は状態をリセット
    if state["last_update"] != today:
        print(f"[INFO] 新しい日付 ({today}) で処理を開始します")
        state = {
            "last_update": today,
            "completed": [],
            "results": {}
        }
        save_state(state)
    
    all_results = []
    
    try:
        # 未処理の商品を抽出
        pending_products = [p for p in PRODUCTS if p["name"] not in state["completed"]]
        
        # バッチに分割して処理
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            batch_num = i//BATCH_SIZE + 1
            total_batches = (len(pending_products) + BATCH_SIZE - 1)//BATCH_SIZE
            print(f"\n[INFO] バッチ処理開始: {batch_num}/{total_batches}")
            
            batch_results = process_batch(batch, state)
            all_results.extend(batch_results)
            
            # 既に完了している商品の結果も追加
            for product in PRODUCTS:
                if product["name"] in state["completed"] and product["name"] not in [name for name, _ in all_results]:
                    price = state["results"].get(product["name"])
                    if price is not None:
                        all_results.append((product["name"], price))
            
            # バッチ間の待機時間
            if i + BATCH_SIZE < len(pending_products):
                delay = random.randint(10, 20)  # バッチ間は長めに待機
                print(f"[INFO] 次のバッチまで {delay}秒間待機中...")
                time.sleep(delay)
        
        # 全ての商品が処理された場合
        if len(state["completed"]) == len(PRODUCTS):
            print("\n[INFO] 全商品の処理が完了しました")
            
            # 結果をCSVに追記
            append_csv(today, all_results)
            
            # 日別サマリーを生成
            generate_daily_summary(today, all_results)
            
            # ファイルをGitにコミットしてプッシュ
            commit_files(today)
            
            state["last_update"] = today
            save_state(state)
        
    except KeyboardInterrupt:
        print("\n[INFO] ユーザーによる中断を検出しました。進捗は保存されています。")
    except Exception as e:
        print(f"\n[ERROR] 処理中にエラーが発生しました: {e}")
        print("[INFO] これまでの進捗は保存されています。")

if __name__ == "__main__":
    main()
