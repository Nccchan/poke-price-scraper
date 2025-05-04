#!/usr/bin/env python3
"""
GitHub Actions向けメルカリ価格収集スクリプト
- Gitエラー回避に特化
- スクレイピング機能を単純化
"""

import subprocess, time, random, re, csv, json
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus
from statistics import median
from playwright.sync_api import sync_playwright

# 商品リスト
PRODUCTS = [
    {"name": "ロケット団の栄光 BOX", "keyword": "ロケット団の栄光 BOX"},
    {"name": "熱風のアリーナ BOX", "keyword": "熱風のアリーナ BOX"},
    {"name": "バトルパートナーズ BOX", "keyword": "バトルパートナーズ BOX"},
    {"name": "テラスタルフェス BOX", "keyword": "テラスタルフェス BOX"},
    {"name": "超電ブレイカー BOX", "keyword": "超電ブレイカー BOX"},
]

# 設定
CSV_FILE = "mercari_prices.csv"
SUMMARY_DIR = "summaries"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

# プリントラッパー
def print_log(message):
    print(f"[INFO] {message}")

# Git処理を最初に実行
def setup_git_environment():
    """GitHub Actions環境でのGit環境セットアップ"""
    # 最初にgitignoreを作成して不要なファイルを除外
    gitignore_content = """
# 自動生成ファイル
*.log
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
    
    # 一度全ての未追跡・変更ファイルをリセット
    print_log("Git環境を初期化中...")
    
    # 未コミットの変更をリセット
    try:
        subprocess.run("git reset --hard", shell=True, check=False)
        print_log("Git変更をリセットしました")
    except Exception as e:
        print(f"[WARN] Git resetエラー: {e}")
    
    # 未追跡ファイルを削除
    try:
        subprocess.run("git clean -fd", shell=True, check=False)
        print_log("未追跡ファイルをクリーンアップしました")
    except Exception as e:
        print(f"[WARN] Git cleanエラー: {e}")

    # コマンドを実行
    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, check=False)
            print_log(f"実行: {cmd}")
        except Exception as e:
            print(f"[WARN] コマンド実行エラー: {cmd} - {e}")
    
    print_log("Git環境の準備完了")
    
    # サマリーディレクトリを作成
    Path(SUMMARY_DIR).mkdir(exist_ok=True)

# 価格取得機能
def get_mercari_prices(keyword):
    """メルカリから価格を取得"""
    print_log(f"「{keyword}」の価格を取得中...")
    
    # 検索URL
    encoded_keyword = quote_plus(keyword)
    url = f"https://jp.mercari.com/search?keyword={encoded_keyword}&status=on_sale"
    
    prices = []
    
    with sync_playwright() as p:
        try:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ja-JP",
                viewport={"width": 1366, "height": 768}
            )
            
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            
            # 待機してコンテンツ読み込み
            time.sleep(5)
            
            # スクロール
            for _ in range(3):
                page.mouse.wheel(0, 500)
                time.sleep(1)
            
            # HTML取得
            html = page.content()
            
            # 価格抽出
            price_patterns = [
                r'[¥￥]\s*([0-9,]+)',  # ¥12,345
                r'([0-9,]+)円',        # 12,345円
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    try:
                        price_str = match.replace(',', '').replace(' ', '')
                        price = int(price_str)
                        
                        # 妥当な価格範囲
                        if 5000 <= price <= 50000:
                            prices.append(price)
                    except ValueError:
                        pass
            
            browser.close()
            
        except Exception as e:
            print(f"[ERROR] スクレイピングエラー: {e}")
    
    # 外れ値を除外
    if len(prices) >= 10:
        prices.sort()
        cut = len(prices) // 10
        prices = prices[cut:-cut]
    
    print_log(f"「{keyword}」の価格データ: {len(prices)}件")
    return prices

# 結果保存
def save_results(results):
    """結果をCSVに保存"""
    today = date.today().isoformat()
    
    # メインCSVファイル
    need_header = not Path(CSV_FILE).exists()
    
    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        if need_header:
            writer.writerow(["日付", "商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
        
        for name, prices in results:
            if prices:
                writer.writerow([
                    today,
                    name,
                    round(median(prices)),
                    min(prices),
                    max(prices),
                    len(prices)
                ])
            else:
                writer.writerow([today, name, "N/A", "N/A", "N/A", 0])
    
    # サマリーファイル
    summary_file = f"{SUMMARY_DIR}/summary_{today}.csv"
    with open(summary_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        
        writer.writerow(["収集日", today])
        writer.writerow([])
        writer.writerow(["商品名", "中央値価格(円)", "最安値", "最高値", "データ件数"])
        
        for name, prices in sorted(results, key=lambda x: x[0]):
            if prices:
                writer.writerow([
                    name,
                    round(median(prices)),
                    min(prices),
                    max(prices),
                    len(prices)
                ])
            else:
                writer.writerow([name, "データなし", "N/A", "N/A", 0])
    
    print_log(f"結果をCSVに保存: {CSV_FILE} および {summary_file}")
    return CSV_FILE, summary_file

# Gitコミット
def commit_changes(files):
    """変更をGitにコミット"""
    today = date.today().isoformat()
    
    try:
        # 変更をステージング
        for file in files:
            cmd = f"git add {file}"
            subprocess.run(cmd, shell=True, check=False)
            print_log(f"ファイルをステージング追加: {file}")
        
        # コミット
        commit_msg = f"data: メルカリ価格データ更新 ({today})"
        subprocess.run(f'git commit -m "{commit_msg}"', shell=True, check=False)
        print_log("変更をコミット")
        
        # プッシュ
        subprocess.run("git push", shell=True, check=False)
        print_log("変更をリモートリポジトリにプッシュ")
        
        return True
    except Exception as e:
        print(f"[ERROR] Gitコミットエラー: {e}")
        return False

# メイン処理
def main():
    print_log("メルカリ価格取得スクリプトを開始")
    
    # Git環境を準備
    setup_git_environment()
    
    # 全商品の価格を取得
    results = []
    for product in PRODUCTS:
        name = product["name"]
        keyword = product["keyword"]
        
        prices = get_mercari_prices(keyword)
        results.append((name, prices))
        
        # 次の商品の前に待機
        if product != PRODUCTS[-1]:
            wait_time = random.randint(5, 10)
            print_log(f"{wait_time}秒待機中...")
            time.sleep(wait_time)
    
    # 結果を保存
    main_csv, summary_csv = save_results(results)
    
    # 変更をコミット
    commit_changes([main_csv, summary_csv])
    
    print_log("スクリプトの実行が完了しました")

if __name__ == "__main__":
    main()
