#!/usr/bin/env python3
"""
エラーハンドリングを強化したメルカリ価格取得スクリプト
- 個別の商品処理失敗時も継続処理
- より詳細なエラーログ
- リトライメカニズム実装
- スクロール回数を最適化
"""

import subprocess, time, random, re, csv, json, traceback
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus
from statistics import median, StatisticsError
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 商品リスト
PRODUCTS = [
    {"name": "ロケット団の栄光 BOX", "keyword": "ロケット団の栄光 BOX シュリンク付"},
    {"name": "熱風のアリーナ BOX", "keyword": "熱風のアリーナ BOX　シュリンク付"},
    {"name": "バトルパートナーズ BOX", "keyword": "バトルパートナーズ BOX　シュリンク付"},
    {"name": "テラスタルフェス BOX", "keyword": "テラスタルフェス BOX　シュリンク付"},
    {"name": "超電ブレイカー BOX", "keyword": "超電ブレイカー BOX　シュリンク付"},
]

# 設定
CSV_FILE = "mercari_prices.csv"
SUMMARY_DIR = "summaries"
ERROR_LOG = "error_log.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
MAX_RETRIES = 2  # 失敗時のリトライ回数
SCROLL_COUNT = 1  # 効率化のためスクロール回数を削減
MIN_WAIT = 5      # 商品間の最小待機時間
MAX_WAIT = 8      # 商品間の最大待機時間

# プリントラッパー
def log_message(message, level="INFO", log_to_file=False):
    """ログメッセージを出力（コンソールとオプションでファイル）"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level}] {message}"
    print(formatted_msg)
    
    if log_to_file and level in ["ERROR", "WARN"]:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{formatted_msg}\n")
            
            # エラーの場合はスタックトレースも出力
            if level == "ERROR" and sys.exc_info()[0] is not None:
                f.write(traceback.format_exc())
                f.write("\n" + "-"*50 + "\n")

# Git処理関連
def setup_git_environment():
    """GitHub Actions環境でのGit環境セットアップ"""
    try:
        # 最初にgitignoreを作成して不要なファイルを除外
        gitignore_content = """
# 自動生成ファイル
*.log
error_log.txt
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
*.egg-info/
.installed.cfg
*.egg

# スクレイピング一時ファイル
debug_screenshots/
*.html
"""
        
        with open(".gitignore", "w") as f:
            f.write(gitignore_content)
        
        # 実行コマンドをリストに保持
        commands = [
            "git config --local user.name 'github-actions[bot]'",
            "git config --local user.email '41898282+github-actions[bot]@users.noreply.github.com'",
            "git add .gitignore",
            "git commit -m 'chore: Add gitignore file'"
        ]
        
        # 未コミットの変更をリセット
        subprocess.run("git reset --hard", shell=True, check=False)
        log_message("Git変更をリセットしました")
        
        # 未追跡ファイルを削除
        subprocess.run("git clean -fd", shell=True, check=False)
        log_message("未追跡ファイルをクリーンアップしました")

        # コマンドを実行
        for cmd in commands:
            try:
                subprocess.run(cmd, shell=True, check=False)
                log_message(f"実行: {cmd}")
            except Exception as e:
                log_message(f"コマンド実行エラー: {cmd} - {e}", "WARN", True)
        
        # サマリーディレクトリを作成
        Path(SUMMARY_DIR).mkdir(exist_ok=True)
        
        return True
    except Exception as e:
        log_message(f"Git環境のセットアップに失敗: {e}", "ERROR", True)
        # 重大なエラーではないので処理は続行
        return False

def fetch_mercari_prices(keyword, retry=0):
    """メルカリから価格を取得（リトライメカニズム組み込み）"""
    try:
        log_message(f"「{keyword}」の価格を取得中... (試行: {retry+1}/{MAX_RETRIES+1})")
        
        # 検索URL
        encoded_keyword = quote_plus(keyword)
        url = f"https://jp.mercari.com/search?keyword={encoded_keyword}&status=on_sale"
        
        prices = []
        browser = None
        
        with sync_playwright() as p:
            try:
                # ブラウザ起動（エラーハンドリングを強化）
                try:
                    browser = p.firefox.launch(headless=True)
                except Exception as e:
                    log_message(f"Firefoxブラウザの起動に失敗: {e}", "ERROR", True)
                    # Chromeで再試行
                    browser = p.chromium.launch(headless=True)
                    log_message("Chromeブラウザで代替起動しました", "WARN")
                
                # ブラウザコンテキスト設定
                try:
                    context = browser.new_context(
                        user_agent=USER_AGENT,
                        locale="ja-JP",
                        viewport={"width": 1366, "height": 768}
                    )
                    page = context.new_page()
                except Exception as e:
                    log_message(f"ブラウザコンテキスト作成エラー: {e}", "ERROR", True)
                    raise
                
                # ページ移動（タイムアウト対策）
                try:
                    page.set_default_timeout(30000)  # 30秒タイムアウト
                    page.goto(url, wait_until="domcontentloaded")
                    log_message("ページ読み込み完了")
                except PlaywrightTimeoutError:
                    log_message("ページ読み込みタイムアウト - 部分的に続行します", "WARN", True)
                except Exception as e:
                    log_message(f"ページ読み込みエラー: {e}", "ERROR", True)
                    raise
                
                # コンテンツ待機（エラー時も続行）
                try:
                    page.wait_for_selector("body", timeout=5000)
                except Exception as e:
                    log_message(f"セレクタ待機エラー: {e}", "WARN")
                
                # 少し待機
                time.sleep(2)
                
                # スクロール（効率化のため回数削減）
                try:
                    for i in range(SCROLL_COUNT):
                        page.mouse.wheel(0, 700)  # より長くスクロール
                        time.sleep(1)
                except Exception as e:
                    log_message(f"スクロールエラー: {e}", "WARN")
                
                # HTML取得（エラーハンドリング）
                try:
                    html = page.content()
                    log_message(f"HTMLコンテンツ取得完了 ({len(html)} バイト)")
                except Exception as e:
                    log_message(f"HTML取得エラー: {e}", "ERROR", True)
                    raise
                
                # 価格抽出
                try:
                    patterns = [
                        r'[¥￥]\s*([0-9,]+)',  # ¥12,345
                        r'([0-9,]+)円',        # 12,345円
                        r'class="[^"]*price[^"]*"[^>]*>(?:¥|￥)?\s*([0-9,]+)'  # クラス属性内の価格
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, html)
                        for match in matches:
                            try:
                                # コンマと空白を除去
                                price_str = match.replace(',', '').replace(' ', '')
                                price = int(price_str)
                                
                                # 妥当な価格範囲チェック
                                if 5000 <= price <= 50000:
                                    prices.append(price)
                            except ValueError:
                                pass  # 数値変換エラーは無視
                    
                    log_message(f"価格抽出結果: {len(prices)}件")
                except Exception as e:
                    log_message(f"価格抽出エラー: {e}", "ERROR", True)
                    # 部分的に抽出できた可能性があるので続行
                
            except Exception as e:
                log_message(f"予期せぬエラー: {e}", "ERROR", True)
                # リトライする
                if retry < MAX_RETRIES:
                    # 指数バックオフで待機
                    wait_time = (2 ** retry) * 5
                    log_message(f"{wait_time}秒後にリトライします", "WARN")
                    time.sleep(wait_time)
                    return fetch_mercari_prices(keyword, retry + 1)
                raise
            finally:
                # ブラウザを確実に閉じる
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
        
        # 価格の後処理
        if prices:
            # 外れ値の除外
            prices.sort()
            if len(prices) >= 10:
                k = max(1, len(prices) // 10)
                filtered_prices = prices[k:len(prices) - k]
                log_message(f"外れ値除外: {len(prices)}件 → {len(filtered_prices)}件")
                prices = filtered_prices
        else:
            # データがない場合、リトライを試みる
            if retry < MAX_RETRIES:
                wait_time = (2 ** retry) * 5
                log_message(f"価格データがありません。{wait_time}秒後にリトライします", "WARN")
                time.sleep(wait_time)
                return fetch_mercari_prices(keyword, retry + 1)
        
        return prices
        
    except Exception as e:
        log_message(f"「{keyword}」の価格取得に失敗: {e}", "ERROR", True)
        # 最大リトライ回数に達した場合は空リストを返す
        return []

def calculate_stats(prices):
    """価格の統計情報を計算（エラーハンドリング付き）"""
    stats = {"count": len(prices)}
    
    if not prices:
        stats["median"] = None
        stats["min"] = None
        stats["max"] = None
        return stats
    
    try:
        stats["median"] = round(median(prices))
    except StatisticsError:
        stats["median"] = None
    
    try:
        stats["min"] = min(prices)
    except ValueError:
        stats["min"] = None
    
    try:
        stats["max"] = max(prices)
    except ValueError:
        stats["max"] = None
    
    return stats

def save_results(results):
    """結果をCSVに保存（エラーハンドリング強化）"""
    try:
        today = date.today().isoformat()
        
        # メインCSVファイル
        csv_path = Path(CSV_FILE)
        need_header = not csv_path.exists()
        
        try:
            with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                
                if need_header:
                    writer.writerow(["日付", "商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
                
                for name, stats in results:
                    if stats["count"] > 0:
                        writer.writerow([
                            today,
                            name,
                            stats["median"],
                            stats["min"],
                            stats["max"],
                            stats["count"]
                        ])
                    else:
                        writer.writerow([today, name, "N/A", "N/A", "N/A", 0])
            
            log_message(f"メインCSV出力完了: {CSV_FILE}")
        except Exception as e:
            log_message(f"メインCSV出力エラー: {e}", "ERROR", True)
            # 続行して日別サマリーの保存を試みる
        
        # サマリーディレクトリ確認
        summary_dir = Path(SUMMARY_DIR)
        if not summary_dir.exists():
            summary_dir.mkdir()
        
        # 日別サマリー
        summary_file = f"{SUMMARY_DIR}/summary_{today}.csv"
        try:
            with open(summary_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                
                writer.writerow(["収集日", today])
                writer.writerow([])
                writer.writerow(["商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
                
                for name, stats in sorted(results, key=lambda x: x[0]):
                    if stats["count"] > 0:
                        writer.writerow([
                            name,
                            stats["median"],
                            stats["min"],
                            stats["max"],
                            stats["count"]
                        ])
                    else:
                        writer.writerow([name, "データなし", "N/A", "N/A", 0])
            
            log_message(f"日別サマリー出力完了: {summary_file}")
        except Exception as e:
            log_message(f"日別サマリー出力エラー: {e}", "ERROR", True)
        
        return CSV_FILE, summary_file
    except Exception as e:
        log_message(f"結果保存中の予期せぬエラー: {e}", "ERROR", True)
        return CSV_FILE, None

def commit_changes(files):
    """変更をGitにコミット（エラーハンドリング強化）"""
    try:
        today = date.today().isoformat()
        files_committed = []
        
        # 各ファイルを個別にステージング
        for file in files:
            if file and Path(file).exists():
                try:
                    cmd = f"git add {file}"
                    result = subprocess.run(cmd, shell=True, check=False, 
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True)
                    
                    if result.returncode == 0:
                        log_message(f"ファイルをステージング追加: {file}")
                        files_committed.append(file)
                    else:
                        log_message(f"ファイルのステージングに失敗: {file}", "WARN", True)
                        log_message(f"エラー出力: {result.stderr}", "WARN", True)
                except Exception as e:
                    log_message(f"ファイル {file} のステージング中にエラー: {e}", "ERROR", True)
        
        if not files_committed:
            log_message("コミット対象のファイルがありません", "WARN")
            return False
        
        # コミット処理
        try:
            commit_msg = f"data: メルカリ価格データ更新 ({today})"
            result = subprocess.run(f'git commit -m "{commit_msg}"', shell=True, check=False,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
            
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                log_message("コミットするものがありません", "WARN")
                return False
                
            if result.returncode != 0:
                log_message(f"コミットエラー: {result.stderr}", "ERROR", True)
                return False
                
            log_message("変更をコミットしました")
        except Exception as e:
            log_message(f"コミット中にエラー: {e}", "ERROR", True)
            return False
        
        # プッシュ処理
        try:
            result = subprocess.run("git push", shell=True, check=False,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
            
            if result.returncode != 0:
                log_message(f"プッシュエラー: {result.stderr}", "ERROR", True)
                return False
                
            log_message("変更をリモートリポジトリにプッシュしました")
            return True
        except Exception as e:
            log_message(f"プッシュ中にエラー: {e}", "ERROR", True)
            return False
            
    except Exception as e:
        log_message(f"Git処理中の予期せぬエラー: {e}", "ERROR", True)
        return False

def main():
    """メイン処理（包括的なエラーハンドリング）"""
    import sys
    
    log_message("メルカリ価格取得スクリプトを開始")
    
    try:
        # Git環境を準備
        setup_git_environment()
        
        # 処理結果を保存するリスト
        all_results = []
        successful_count = 0
        failed_count = 0
        
        # 各商品を個別に処理し、エラーがあっても続行
        for product in PRODUCTS:
            try:
                name = product["name"]
                keyword = product["keyword"]
                
                log_message(f"===== 「{name}」の処理開始 =====")
                
                # 価格取得（リトライメカニズム内蔵）
                prices = fetch_mercari_prices(keyword)
                
                # 統計情報の計算
                stats = calculate_stats(prices)
                
                if stats["count"] > 0:
                    log_message(f"「{name}」の結果: 中央値={stats['median']}円, "
                              f"最安値={stats['min']}円, 最高値={stats['max']}円, "
                              f"{stats['count']}件")
                    successful_count += 1
                else:
                    log_message(f"「{name}」: 価格データなし", "WARN")
                    failed_count += 1
                
                # 結果をリストに追加
                all_results.append((name, stats))
                
            except Exception as e:
                log_message(f"「{product['name']}」の処理中に重大なエラー: {e}", "ERROR", True)
                # エラーが発生しても空のデータを追加して続行
                all_results.append((product["name"], {"count": 0, "median": None, "min": None, "max": None}))
                failed_count += 1
            
            # 次の商品の前に待機（最後の商品以外）
            if product != PRODUCTS[-1]:
                wait_time = random.randint(MIN_WAIT, MAX_WAIT)
                log_message(f"{wait_time}秒待機中...")
                time.sleep(wait_time)
        
        # 処理結果のサマリー
        total = len(PRODUCTS)
        log_message(f"処理完了: 全{total}商品中 {successful_count}個成功, {failed_count}個失敗")
        
        if all_results:
            # 結果を保存
            main_csv, summary_csv = save_results(all_results)
            
            # Gitコミット（ファイルが存在する場合のみ）
            files_to_commit = [f for f in [main_csv, summary_csv] if f and Path(f).exists()]
            if files_to_commit:
                commit_success = commit_changes(files_to_commit)
                if commit_success:
                    log_message("Gitリポジトリの更新が完了しました")
                else:
                    log_message("Gitリポジトリの更新が一部失敗しました", "WARN")
            else:
                log_message("コミットするファイルがありません", "WARN")
        else:
            log_message("処理結果がないためCSV出力をスキップします", "WARN")
        
        log_message("スクリプトの実行が完了しました")
        
        # エラーがあっても正常終了コードを返す
        return 0
        
    except Exception as e:
        log_message(f"実行中の予期せぬ重大エラー: {e}", "ERROR", True)
        log_message(traceback.format_exc(), "ERROR", True)
        return 1
    
if __name__ == "__main__":
    import sys
    sys.exit(main())
