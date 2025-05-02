#!/usr/bin/env python3
"""
完全な日本円表示対応メルカリ価格収集ボット
強化されたロケール設定とUSD検出機能を兼ね備えた最終版
"""

import json, re, csv, sys, time, datetime as dt, os, random, subprocess
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── 検索対象商品リスト ─────────────────────────────
PRODUCTS = [
    {"name": "ロケット団の栄光 BOX", "keyword": "ロケット団の栄光 BOX シュリンク付"},
    {"name": "熱風のアリーナ BOX", "keyword": "熱風のアリーナ BOX シュリンク付"},
    {"name": "バトルパートナーズ BOX", "keyword": "バトルパートナーズ BOX シュリンク付"},
    {"name": "テラスタルフェスティバル BOX", "keyword": "テラスタルフェスティバル BOX シュリンク付"},
    {"name": "超電ブレイカー BOX", "keyword": "超電ブレイカー BOX シュリンク付"},
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
DEBUG_MODE = True                         # デバッグモード（スクリーンショットなど詳細情報を出力）
USD_TO_JPY = 152                          # USD→JPYの換算レート (2025年5月現在)
# ────────────────────────────────────────────────

def run_git_command(command):
    """Gitコマンドを実行する"""
    try:
        print(f"[DEBUG] Executing git command: {command}")
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
    
    # CSVファイルを追加
    csv_add_result = run_git_command(f'git add {CSV_FILE}')
    print(f"[DEBUG] CSV add result: {csv_add_result}")
    
    # 進捗状態ファイルを追加
    state_add_result = run_git_command(f'git add {STATE_FILE}')
    print(f"[DEBUG] State file add result: {state_add_result}")
    
    # 日別サマリーファイルが存在する場合は追加
    summary_file = Path(f"summary_{date}.csv")
    if summary_file.exists():
        summary_add_result = run_git_command(f'git add {summary_file}')
        print(f"[DEBUG] Summary file add result: {summary_add_result}")
    
    # デバッグスクリーンショットがあれば追加
    debug_dir = Path("debug_screenshots")
    if debug_dir.exists() and DEBUG_MODE:
        debug_add_result = run_git_command(f'git add {debug_dir}/*')
        print(f"[DEBUG] Debug screenshots add result: {debug_add_result}")
    
    # Gitの状態を確認（デバッグ用）
    status = run_git_command('git status')
    print(f"[DEBUG] Git status before commit:\n{status}")
    
    # コミットする
    print("[INFO] Committing changes...")
    commit_message = f"data: メルカリ価格データ更新 ({date})"
    commit_result = run_git_command(f'git commit -m "{commit_message}"')
    
    if commit_result:
        print(f"[INFO] Commit result: {commit_result}")
    else:
        print("[WARN] Nothing to commit or commit failed")
        return False
    
    # 変更をプッシュ
    print("[INFO] Pushing changes to remote repository...")
    push_result = run_git_command('git push')
    
    if push_result is not None:
        print("[INFO] Successfully pushed changes to Git repository")
        return True
    else:
        print("[ERROR] Failed to push changes to Git repository")
        return False

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
        print(f"[INFO] 進捗状態を保存しました: {STATE_FILE}")
    except Exception as e:
        print(f"[ERROR] 状態ファイル保存エラー: {e}")

def fetch_prices(keyword: str, retry_count=0) -> list[int]:
    """指定したキーワードでメルカリを検索し、販売中商品の価格リストを返す（ページ数制限あり）"""
    # 検索URL
    url = (
        "https://jp.mercari.com/search"
        f"?keyword={quote_plus(keyword)}"
        "&sort=score&order=desc&item_status=on_sale"
    )
    
    print(f"[INFO] 検索URL: {url}")
    
    # デバッグディレクトリを作成
    if DEBUG_MODE:
        debug_dir = Path("debug_screenshots")
        debug_dir.mkdir(exist_ok=True)
        
        # 商品名に使えない文字をアンダースコアに置換
        safe_keyword = re.sub(r'[\\/*?:"<>|]', "_", keyword)
    
    prices = []
    with sync_playwright() as p:
        # 強化されたロケール設定でブラウザを起動
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
            # 明示的な国表示用のHTTPヘッダー
            extra_http_headers={
                "Accept-Language": "ja-JP,ja;q=0.9",
                "X-Forwarded-For": "133.218.88.158"  # 日本のIPアドレス
            }
        )
        page = context.new_page()
        page.set_default_navigation_timeout(NAV_TIMEOUT)

        # 日本ロケールのCookie設定
        page.context.add_cookies([
            {
                "name": "country", 
                "value": "jp",
                "domain": "jp.mercari.com",
                "path": "/"
            }, 
            {
                "name": "lang", 
                "value": "ja",
                "domain": "jp.mercari.com", 
                "path": "/"
            },
            {
                "name": "locale",
                "value": "ja-JP",
                "domain": "jp.mercari.com", 
                "path": "/"
            },
            {
                "name": "currency",
                "value": "JPY",
                "domain": "jp.mercari.com", 
                "path": "/"
            }
        ])

        # ページロード前にJavaScriptを注入して地域設定を上書き
        page.add_init_script("""
            Object.defineProperty(navigator, 'language', {
                get: function() { return 'ja-JP'; }
            });
            Object.defineProperty(navigator, 'languages', {
                get: function() { return ['ja-JP', 'ja']; }
            });
            Object.defineProperty(navigator, 'geolocation', {
                get: function() { 
                    return {
                        getCurrentPosition: function(success) {
                            success({
                                coords: {
                                    latitude: 35.6895,
                                    longitude: 139.6917,
                                    accuracy: 10
                                }
                            });
                        }
                    }; 
                }
            });
        """)

        try:
            # ページロード後に明示的に通貨をJPYに設定するスクリプトを実行
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(3)  # 短い待機
            
            # 明示的な通貨設定を試行
            page.evaluate("""() => {
                try {
                    if (window.localStorage) {
                        window.localStorage.setItem('currency', 'JPY');
                    }
                    if (window.sessionStorage) {
                        window.sessionStorage.setItem('currency', 'JPY');
                    }
                    // Cookie も JavaScript から設定
                    document.cookie = "currency=JPY; path=/; domain=jp.mercari.com";
                } catch (e) {
                    console.error("Could not set currency", e);
                }
            }""")
            print(f"[INFO] 通貨設定を JPY に変更しました")
            
            # 初期表示の待機時間（長めに設定）
            print("[INFO] 初期ページ表示待機中...")
            page.wait_for_timeout(8000)  # 8秒待機
            
            # デバッグスクリーンショット（初期表示）
            if DEBUG_MODE:
                screenshot_path = debug_dir / f"{safe_keyword}_initial.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] 初期表示スクリーンショット: {screenshot_path}")
            
            # 通貨切替ボタンを探す試み
            try:
                currency_selector = '[data-testid="currency-button"]'
                if page.locator(currency_selector).count() > 0:
                    print("[INFO] 通貨切替ボタンを検出しました。日本円表示に変更します。")
                    page.click(currency_selector)
                    time.sleep(2)
                    page.click('text="JPY"')  # 日本円を選択
                    time.sleep(3)
            except Exception as e:
                print(f"[INFO] 通貨切替を試みましたが失敗しました: {e}")
            
            # 以前成功したセレクタを優先的に試す
            selectors = [
                '.merPrice',              # 以前成功したセレクタ
                '[data-testid="item-price"]',
                '.merItemThumbnail__price',
                '.merItem__price',
                '[data-location="search"] [data-testid="price"]',
                '.item-price',            # 汎用的なセレクタも追加
                '[class*="price"]',       # "price"を含むクラス
                '.mer-item-price'         # ケバブケース形式
            ]
            
            # まずアイテムセルセレクタを探す（存在確認）
            item_selectors = [
                '[data-testid="item-cell"]',
                '.merItemThumbnail',
                'mer-item-thumbnail',
                '.merItem',
                '.item-card',
                '.product-item' 
            ]
            
            item_selector_found = False
            for selector in item_selectors:
                try:
                    count = page.locator(selector).count()
                    if count > 0:
                        print(f"[INFO] Found {count} items with selector: {selector}")
                        item_selector_found = True
                        break
                except Exception as e:
                    print(f"[WARN] Error checking item selector {selector}: {e}")
            
            if not item_selector_found:
                print(f"[WARN] No item selectors found for {keyword}, but continuing anyway")
            
            # ゆっくりスクロール（成功したパターンを再現）
            for step in range(1, 5):  # 4回スクロール
                print(f"[INFO] Scroll step {step}/4")
                page.mouse.wheel(0, 1000)
                time.sleep(3)  # 各スクロール後に3秒待機
                
                # スクロール後のスクリーンショット
                if DEBUG_MODE:
                    screenshot_path = debug_dir / f"{safe_keyword}_scroll_{step}.png"
                    page.screenshot(path=str(screenshot_path))
                    print(f"[DEBUG] スクロール{step}後のスクリーンショット: {screenshot_path}")
            
            # DOM から価格を取得する試み（USD/JPY両対応）
            dom_prices = []
            for price_selector in selectors:
                try:
                    print(f"[INFO] Trying price selector: {price_selector}")
                    
                    # セレクタの要素を取得
                    elements = page.locator(price_selector).all()
                    if elements:
                        texts = [elem.text_content() for elem in elements if elem.is_visible()]
                        
                        if texts:
                            print(f"[INFO] Found {len(texts)} prices with selector: {price_selector}")
                            
                            # テキスト内容のデバッグログ
                            if len(texts) > 0:
                                print(f"[DEBUG] サンプルテキスト: {texts[:3]}")
                            
                            # 制限を適用
                            if len(texts) > MAX_ITEMS:
                                print(f"[INFO] 商品数を{MAX_ITEMS}に制限します")
                                texts = texts[:MAX_ITEMS]
                            
                            # 価格テキストから数字だけを抽出（JPYとUSD両方対応）
                            for t in texts:
                                if t and re.search(r"\d", t):
                                    # JPY（日本円）の検索
                                    jpy_match = re.search(r'[¥￥]([0-9,]+)', t)
                                    if jpy_match:
                                        try:
                                            price_str = jpy_match.group(1).replace(',', '')
                                            price = int(price_str)
                                            # 妥当な価格範囲（例：5,000円〜200,000円）
                                            if 1000 <= price <= 200000:
                                                print(f"[DEBUG] 円価格検出: ¥{price}")
                                                dom_prices.append(price)
                                                continue
                                        except ValueError:
                                            pass
                                    
                                    # USD（米ドル）の検索
                                    usd_match = re.search(r'\$([0-9,.]+)', t)
                                    if usd_match:
                                        try:
                                            price_str = usd_match.group(1).replace(',', '')
                                            # 小数点以下を処理
                                            if '.' in price_str:
                                                price_parts = price_str.split('.')
                                                price_dollars = int(price_parts[0])
                                            else:
                                                price_dollars = int(price_str)
                                            
                                            # USDをJPYに変換
                                            price_jpy = int(price_dollars * USD_TO_JPY)
                                            if 1000 <= price_jpy <= 200000:
                                                print(f"[DEBUG] ドル価格検出: ${price_dollars} -> ¥{price_jpy}")
                                                dom_prices.append(price_jpy)
                                        except ValueError:
                                            pass
                            
                            if dom_prices:
                                print(f"[DEBUG] DOM price count = {len(dom_prices)}")
                                break
                except Exception as e:
                    print(f"[WARN] Error with price selector {price_selector}: {e}")
            
            # JavaScript評価による直接抽出も試みる（成功したパターン）
            if not dom_prices:
                try:
                    for price_selector in selectors:
                        print(f"[INFO] Trying JS evaluation with selector: {price_selector}")
                        
                        try:
                            # JavaScript を使って要素のテキストを取得
                            texts = page.eval_on_selector_all(
                                price_selector,
                                'els => els.map(e => e.textContent)'
                            )
                            
                            if texts:
                                print(f"[INFO] Found {len(texts)} prices with JS eval: {price_selector}")
                                print(f"[DEBUG] Sample JS texts: {texts[:3]}")
                                
                                # 価格テキストから数字だけを抽出（JPYとUSD両方対応）
                                js_prices = []
                                for t in texts:
                                    if t and re.search(r"\d", t):
                                        # JPY（日本円）の検索
                                        jpy_match = re.search(r'[¥￥]([0-9,]+)', t)
                                        if jpy_match:
                                            try:
                                                price_str = jpy_match.group(1).replace(',', '')
                                                price = int(price_str)
                                                if 1000 <= price <= 200000:
                                                    js_prices.append(price)
                                                    continue
                                            except ValueError:
                                                pass
                                        
                                        # USD（米ドル）の検索
                                        usd_match = re.search(r'\$([0-9,.]+)', t)
                                        if usd_match:
                                            try:
                                                price_str = usd_match.group(1).replace(',', '')
                                                # 小数点以下を処理
                                                if '.' in price_str:
                                                    price_parts = price_str.split('.')
                                                    price_dollars = int(price_parts[0])
                                                else:
                                                    price_dollars = int(price_str)
                                                    
                                                # USDをJPYに変換
                                                price_jpy = int(price_dollars * USD_TO_JPY)
                                                if 1000 <= price_jpy <= 200000:
                                                    print(f"[DEBUG] USD ${price_dollars} -> JPY ¥{price_jpy}")
                                                    js_prices.append(price_jpy)
                                            except ValueError:
                                                pass
                                
                                if js_prices:
                                    print(f"[DEBUG] JS eval price count = {len(js_prices)}")
                                    dom_prices = js_prices
                                    break
                        except Exception as e:
                            print(f"[WARN] JS eval error with {price_selector}: {e}")
                except Exception as e:
                    print(f"[WARN] JS evaluation error: {e}")
            
            # 価格が見つからない場合は正規表現で直接検索
            if not dom_prices:
                print("[INFO] No prices found with selectors, checking page content")
                html = page.content()
                
                # HTMLソースを保存（デバッグ用）
                if DEBUG_MODE:
                    html_path = debug_dir / f"{safe_keyword}_source.html"
                    with html_path.open("w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"[DEBUG] HTMLソース保存: {html_path}")
                
                # 日本円価格パターンを直接検索
                jpy_prices = []
                jpy_pattern = r'[¥￥]([0-9,]+)'
                jpy_matches = re.findall(jpy_pattern, html)
                if jpy_matches:
                    print(f"[INFO] Found {len(jpy_matches)} JPY prices in HTML")
                    for p in jpy_matches:
                        try:
                            price = int(re.sub(r"[^\d]", "", p))
                            if 1000 <= price <= 200000:
                                jpy_prices.append(price)
                        except ValueError:
                            pass
                
                # 米ドル価格パターンを直接検索
                usd_prices = []
                usd_pattern = r'\$([0-9,.]+)'
                usd_matches = re.findall(usd_pattern, html)
                if usd_matches:
                    print(f"[INFO] Found {len(usd_matches)} USD prices in HTML")
                    for p in usd_matches:
                        try:
                            p = p.replace(',', '')
                            if '.' in p:
                                price_parts = p.split('.')
                                price_dollars = int(price_parts[0])
                                price_jpy = int(price_dollars * USD_TO_JPY)
                            else:
                                price_dollars = int(p)
                                price_jpy = int(price_dollars * USD_TO_JPY)
                                
                            if 1000 <= price_jpy <= 200000:
                                print(f"[DEBUG] USD ${price_dollars} -> JPY ¥{price_jpy}")
                                usd_prices.append(price_jpy)
                        except ValueError:
                            pass
                
                # JPYとUSDの価格を組み合わせる
                regex_prices = jpy_prices + usd_prices
                if regex_prices:
                    print(f"[DEBUG] Combined regex price count = {len(regex_prices)}")
                    dom_prices = regex_prices
            
            # 最終スクリーンショット
            if DEBUG_MODE:
                screenshot_path = debug_dir / f"{safe_keyword}_final.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] 最終スクリーンショット: {screenshot_path}")
            
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
        print(f"[DEBUG] 価格一覧（上位10件）: {prices[:10]}...")
        
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
    try:
        # Git設定
        setup_git()
        
        today = dt.date.today().isoformat()
        
        # 古いステートを削除して新規作成（強制的に再実行）
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print("[INFO] 既存の進捗状態ファイルを削除しました")
        
        # 状態を新規作成
        state = {
            "last_update": today,
            "completed": [],
            "results": {}
        }
        save_state(state)
        
        all_results = []
        
        # 全商品を処理
        pending_products = PRODUCTS
        
        # バッチに分割して処理
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            batch_num = i//BATCH_SIZE + 1
            total_batches = (len(pending_products) + BATCH_SIZE - 1)//BATCH_SIZE
            print(f"\n[INFO] バッチ処理開始: {batch_num}/{total_batches}")
            
            batch_results = process_batch(batch, state)
            all_results.extend(batch_results)
            
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
            
            # 状態を更新
            state["last_update"] = today
            save_state(state)
            
            # ファイルをGitにコミットしてプッシュ
            commit_success = commit_files(today)
            if commit_success:
                print("[INFO] データが正常にGitリポジトリに更新されました")
            else:
                print("[WARN] Gitリポジトリの更新に問題がありました")
        
    except KeyboardInterrupt:
        print("\n[INFO] ユーザーによる中断を検出しました。進捗は保存されています。")
    except Exception as e:
        print(f"\n[ERROR] 処理中にエラーが発生しました: {e}")
        print(f"[DEBUG] エラーの詳細: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        print("[INFO] これまでの進捗は保存されています。")

if __name__ == "__main__":
    main()
