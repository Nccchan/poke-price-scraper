#!/usr/bin/env python3
"""
シンプル化されたメルカリ価格取得スクリプト
- ブロック回避のための対策強化
- ヘッドレスモードとブラウザプロファイルの活用
- より堅牢な価格抽出方法
"""

import json, re, csv, time, datetime as dt, os, random, logging
from statistics import median
from urllib.parse import quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("mercari_scraper")

# 検索対象商品リスト
PRODUCTS = [
    {"name": "ロケット団の栄光 BOX", "keyword": "ロケット団の栄光 BOX"},
    {"name": "熱風のアリーナ BOX", "keyword": "熱風のアリーナ BOX"},
    {"name": "バトルパートナーズ BOX", "keyword": "バトルパートナーズ BOX"},
    {"name": "テラスタルフェスティバル BOX", "keyword": "テラスタルフェスティバル BOX"},
    {"name": "超電ブレイカー BOX", "keyword": "超電ブレイカー BOX"},
]

# 設定パラメータ
CSV_FILE = Path("mercari_prices.csv")
RESULTS_DIR = Path("results")
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
]
REQUEST_DELAY_MIN = 10  # より長い待機時間（秒）
REQUEST_DELAY_MAX = 20
MAX_RETRIES = 3
STEALTH_MODE = True  # ブロック回避のためのステルスモード

def ensure_dirs():
    """必要なディレクトリを作成"""
    RESULTS_DIR.mkdir(exist_ok=True)
    
    # 日付別ディレクトリ
    today = dt.date.today().isoformat()
    day_dir = RESULTS_DIR / today
    day_dir.mkdir(exist_ok=True)
    
    return day_dir

def extract_prices_from_html(html):
    """HTMLから価格を抽出する改良版メソッド"""
    prices = []
    
    # 価格パターン（シンプル化）
    patterns = [
        r'[¥￥]\s*([0-9,]+)',              # ¥12,345
        r'([0-9,]+)円',                    # 12,345円
        r'class="[^"]*price[^"]*"[^>]*>\s*[¥￥]?\s*([0-9,]+)', # 各種価格要素
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html)
        if matches:
            logger.info(f"パターン '{pattern}' で {len(matches)} 件の価格を検出")
            
            for match in matches:
                try:
                    # コンマと空白を除去
                    price_str = match.replace(',', '').replace(' ', '')
                    price = int(price_str)
                    
                    # 妥当な価格範囲かチェック (ポケモンカードBOXとしては5,000円～50,000円が一般的)
                    if 5000 <= price <= 50000:
                        prices.append(price)
                except ValueError:
                    pass  # 数値変換エラーは無視
    
    return prices

def setup_browser_context(playwright):
    """ブラウザ検出回避のためのコンテキスト設定"""
    # ランダムなユーザーエージェント
    user_agent = random.choice(USER_AGENTS)
    logger.info(f"使用するUA: {user_agent}")
    
    # ブラウザを起動
    if STEALTH_MODE:
        # ステルスモード設定（検出回避）
        browser = playwright.firefox.launch(
            headless=False,  # Firefoxはヘッドレスモードの検出が困難
            slow_mo=50,      # 人間らしい動きの再現
        )
        context = browser.new_context(
            user_agent=user_agent,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1366 + random.randint(-50, 50), "height": 768 + random.randint(-30, 30)},
            color_scheme="light",
        )
    else:
        # 通常モード
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=user_agent,
            locale="ja-JP",
            viewport={"width": 1280, "height": 800}
        )
    
    # 人間らしいブラウザフィンガープリントを設定
    context.add_init_script("""
    // WebGL, Canvas, AudioContext fingerprinting randomization
    const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        // Randomize certain WebGL parameters
        if (parameter === 37445) {
            return 'Intel Inc.';
        }
        if (parameter === 37446) {
            return 'Intel Iris Graphics';
        }
        return originalGetParameter.call(this, parameter);
    };
    """)
    
    # 言語設定のCookie
    context.add_cookies([
        {"name": "country", "value": "jp", "domain": "jp.mercari.com", "path": "/"},
        {"name": "lang", "value": "ja", "domain": "jp.mercari.com", "path": "/"}
    ])
    
    return browser, context

def fetch_mercari_prices(keyword, day_dir, retry_count=0):
    """メルカリから商品価格を取得"""
    # 検索URL（シンプル化）
    encoded_keyword = quote_plus(keyword)
    url = f"https://jp.mercari.com/search?keyword={encoded_keyword}&status=on_sale"
    
    logger.info(f"検索URL: {url}")
    safe_keyword = re.sub(r'[\\/*?:"<>|]', "_", keyword)
    
    prices = []
    with sync_playwright() as p:
        try:
            browser, context = setup_browser_context(p)
            page = context.new_page()
            page.set_default_navigation_timeout(60000)  # 60秒タイムアウト
            
            # ブロック回避の待機
            wait_time = random.randint(1, 3)
            logger.info(f"ブラウザ準備完了、{wait_time}秒待機...")
            time.sleep(wait_time)
            
            # ページアクセス
            logger.info(f"ページアクセス開始: {url}")
            page.goto(url, wait_until="domcontentloaded")
            
            # 初期読み込み待機
            logger.info("ページコンテンツ読み込み待機中...")
            
            # コンテンツが読み込まれるまでの待機（最大30秒）
            try:
                page.wait_for_selector("body", timeout=30000)
                time.sleep(5)  # 追加待機
            except Exception as e:
                logger.warning(f"セレクタ待機エラー: {e}")
            
            # スクロール（人間らしい動きで）
            logger.info("ページをスクロールして商品読み込み...")
            for i in range(1, 5):
                # ランダムな距離でスクロール
                scroll_amount = random.randint(600, 800)
                page.mouse.wheel(0, scroll_amount)
                
                # 自然な間隔で待機
                wait_ms = random.randint(1000, 3000)
                page.wait_for_timeout(wait_ms)
                
                # たまにマウス移動（より人間らしく）
                if random.random() > 0.7:
                    page.mouse.move(
                        random.randint(100, 1000),
                        random.randint(100, 600)
                    )
            
            # 十分な待機後にHTMLを取得
            time.sleep(3)
            html = page.content()
            
            # HTMLをファイルに保存（デバッグ用）
            html_path = day_dir / f"{safe_keyword}_source.html"
            with html_path.open("w", encoding="utf-8") as f:
                f.write(html)
            
            # スクリーンショット保存
            screenshot_path = day_dir / f"{safe_keyword}_screenshot.png"
            page.screenshot(path=str(screenshot_path))
            logger.info(f"スクリーンショット保存: {screenshot_path}")
            
            # HTMLから価格を抽出
            prices = extract_prices_from_html(html)
            logger.info(f"抽出した価格データ: {len(prices)}件")
            
            if not prices and retry_count < MAX_RETRIES:
                logger.warning(f"価格データなし。リトライします ({retry_count+1}/{MAX_RETRIES})")
                browser.close()
                time.sleep(random.randint(15, 30))  # 長めの待機
                return fetch_mercari_prices(keyword, day_dir, retry_count + 1)
            
        except Exception as e:
            logger.error(f"エラーが発生しました: {e}")
            if retry_count < MAX_RETRIES:
                logger.info(f"リトライします ({retry_count+1}/{MAX_RETRIES})")
                time.sleep((2 ** retry_count) * 10)  # 指数バックオフ
                return fetch_mercari_prices(keyword, day_dir, retry_count + 1)
        finally:
            try:
                browser.close()
            except:
                pass
    
    # 価格の後処理
    if prices:
        prices.sort()
        logger.info(f"取得価格（上位10件）: {prices[:10]}")
        
        # 極端な値を除外（上下10%）
        if len(prices) >= 10:
            k = max(1, len(prices) // 10)
            prices = prices[k:len(prices) - k]
            logger.info(f"外れ値除外後: {len(prices)}件")
    
    return prices

def save_results(all_results, day_dir):
    """結果をCSVに保存"""
    today = dt.date.today().isoformat()
    
    # メインCSVに追記
    need_header = not CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        if need_header:
            writer.writerow(["日付", "商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
        
        for name, result in all_results:
            if result and "prices" in result and result["prices"]:
                writer.writerow([
                    today,
                    name,
                    result["median"],
                    result["min"],
                    result["max"],
                    result["count"]
                ])
            else:
                writer.writerow([today, name, "N/A", "N/A", "N/A", 0])
    
    logger.info(f"メインCSV出力完了: {CSV_FILE}")
    
    # 日別サマリーCSV
    summary_file = day_dir / f"summary_{today}.csv"
    with summary_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        writer.writerow(["収集日", today])
        writer.writerow([])
        writer.writerow(["商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
        
        for name, result in sorted(all_results, key=lambda x: x[0]):
            if result and "prices" in result and result["prices"]:
                writer.writerow([
                    name,
                    result["median"],
                    result["min"],
                    result["max"],
                    result["count"]
                ])
            else:
                writer.writerow([name, "データなし", "N/A", "N/A", 0])
    
    logger.info(f"日別サマリー出力完了: {summary_file}")

def main():
    """メイン処理"""
    try:
        logger.info("メルカリ価格取得を開始します")
        
        # ディレクトリ準備
        day_dir = ensure_dirs()
        all_results = []
        
        for product in PRODUCTS:
            name = product["name"]
            keyword = product["keyword"]
            
            logger.info(f"\n===== 「{name}」の処理開始 =====")
            
            prices = fetch_mercari_prices(keyword, day_dir)
            
            result = {}
            if prices:
                result = {
                    "prices": prices,
                    "count": len(prices),
                    "median": round(median(prices)),
                    "min": min(prices),
                    "max": max(prices)
                }
                logger.info(f"「{name}」の結果: 中央値={result['median']}円, "
                           f"最安値={result['min']}円, 最高値={result['max']}円, "
                           f"{result['count']}件")
            else:
                logger.warning(f"「{name}」の価格データがありません")
            
            all_results.append((name, result))
            
            # 次の商品の前に待機
            if product != PRODUCTS[-1]:
                delay = random.randint(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                logger.info(f"{delay}秒間待機中...")
                time.sleep(delay)
        
        # 結果の保存
        save_results(all_results, day_dir)
        logger.info("全商品の処理が完了しました")
        
    except KeyboardInterrupt:
        logger.info("ユーザーによる中断を検出しました")
    except Exception as e:
        logger.error(f"処理中にエラーが発生しました: {e}", exc_info=True)

if __name__ == "__main__":
    main()
