from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import tweepy
import time
import threading
import logging
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from db_manager import (
    get_db_connection, get_all_account_ids, get_settings, get_auto_post_status, get_message,
    reset_messages, insert_message, set_interval, update_auto_post_status,
    get_messages, delete_message, update_message, delete_all_messages
)
from csv_manager import insert_messages_from_csv, upload_csv
from account_manager import load_account, register_account, edit_account, clients, get_all_account_ids
from post_setting_manager import load_settings, load_auto_post_status, set_interval_route, start_auto_post, stop_auto_post

# 環境変数の読み込み
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')

# ログ設定
LOG_FILENAME = 'app.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

# 定数の定義
INTERVAL_IN_SECONDS = 3600  # 1時間（秒単位）
CHECK_INTERVAL = 60         # 1分（秒単位）
MINIMUM_POST_INTERVAL_MINUTES = 10  # 重複回避のための最小投稿間隔（分単位）を10分に変更
DEFAULT_INTERVAL_HOURS = 3  # デフォルトの投稿間隔（時間単位）

# グローバル変数の初期化
reset_flag = False
current_account_id = None
post_lock = threading.Lock()  # 追加: 投稿用のロック
post_disable_until = {}  # 追加: アカウントごとの投稿停止時間

# アカウントごとのデータを管理する辞書
account_settings = {}   # アカウントごとの設定
is_auto_posting = {}    # アカウントごとの自動投稿状態
auto_post_threads = {}  # アカウントごとのスレッド（スレッドと停止用のイベントを格納）
last_post_time = {}     # アカウントごとの最後の投稿時間

# 次の投稿時間の計算
def get_seconds_until_next_post(specific_times):
    now = datetime.now().time()
    future_times = [datetime.strptime(t, "%H:%M").time() for t in specific_times if datetime.strptime(t, "%H:%M").time() > now]
    if future_times:
        next_time = min(future_times)
    else:
        next_time = min([datetime.strptime(t, "%H:%M").time() for t in specific_times])
    next_post_time = datetime.combine(datetime.today(), next_time)
    if next_post_time < datetime.now():
        next_post_time += timedelta(days=1)
    return (next_post_time - datetime.now()).total_seconds()

# 自動投稿の実行関数
def job(account_id, stop_event):
    try:
        logging.debug(f"ジョブ関数が開始されました: アカウント {account_id}")
        while not stop_event.is_set():
            settings = account_settings.get(account_id, {})
            interval_type = settings.get('interval_type', 'interval')
            interval = settings.get('interval', DEFAULT_INTERVAL_HOURS)
            specific_times = settings.get('specific_times', [])

            current_time = datetime.now()
            if account_id in last_post_time:
                time_since_last_post = current_time - last_post_time[account_id]
                if time_since_last_post < timedelta(minutes=MINIMUM_POST_INTERVAL_MINUTES):
                    logging.debug(f"最近の活動のためジョブをスキップします: アカウント {account_id}")
                    if stop_event.wait(CHECK_INTERVAL):
                        break
                    continue

            if interval_type == 'interval':
                logging.debug(f"インターバルモードでメッセージを投稿します: アカウント {account_id}")
                post_message(account_id)
                if stop_event.wait(interval * INTERVAL_IN_SECONDS):
                    break
            else:
                current_time_str = current_time.strftime("%H:%M")
                if current_time_str in specific_times:
                    logging.debug(f"指定時間にメッセージを投稿します: {current_time_str} アカウント {account_id}")
                    post_message(account_id)
                if stop_event.wait(CHECK_INTERVAL):
                    break
    except Exception as e:
        logging.error(f"ジョブでエラーが発生しました: アカウント {account_id}: {e}")

# メッセージの投稿関数
def post_message(account_id, message=None):
    try:
        if not post_lock.acquire(blocking=False):
            logging.debug(f"ロックのため投稿をスキップします: アカウント {account_id}")
            return

        current_time = datetime.now()
        if account_id in post_disable_until and current_time < post_disable_until[account_id]:
            logging.debug(f"一時的な停止のため投稿をスキップします: アカウント {account_id}")
            return

        logging.debug(f"メッセージを投稿しようとしています: アカウント {account_id}")

        # 前回の投稿時間を確認
        if account_id in last_post_time:
            time_since_last_post = current_time - last_post_time[account_id]
            if time_since_last_post < timedelta(minutes=MINIMUM_POST_INTERVAL_MINUTES):
                logging.debug(f"最近の活動のため投稿をスキップします: アカウント {account_id}")
                return

        if not message:
            message = get_message(account_id)

        if message:
            logging.debug(f"投稿するメッセージ: アカウント {account_id}: {message}")
            client = clients.get(account_id)
            if client:
                response = client.create_tweet(text=message)
                # logging.debug(f"ツイートのレスポンス: アカウント {account_id}: {response}")
                print(f"投稿完了: {message} \nアカウント {account_id} at {datetime.now()}")
                # print(f"ツイートID: アカウント {account_id}: {response.data['id']}")
                last_post_time[account_id] = current_time
                post_disable_until[account_id] = current_time + timedelta(minutes=MINIMUM_POST_INTERVAL_MINUTES)  # 10分間投稿停止
            else:
                logging.error(f"Twitterクライアントが利用できません: アカウント {account_id}")
        else:
            logging.debug(f"投稿するメッセージがありません: アカウント {account_id}")
    except tweepy.TweepyException as e:
        logging.error(f"メッセージの投稿でエラーが発生しました: アカウント {account_id}: {e}")
        print(f"エラーが発生しました: {e}")
        if "duplicate" in str(e):
            print(f"重複投稿エラーが発生しました。次のメッセージを試します。 アカウント {account_id}")
            next_message = get_message(account_id)
            if next_message:
                post_message(account_id, message=next_message)
    except Exception as e:
        logging.error(f"メッセージの投稿で予期しないエラーが発生しました: アカウント {account_id}: {e}")
    finally:
        if post_lock.locked():
            post_lock.release()

# 自動投稿スケジュールの更新
def update_auto_post_schedule(account_id):
    global auto_post_threads

    logging.debug(f"自動投稿スケジュールを更新しています: アカウント {account_id}")

    # 現在のスレッドが存在し、動作中であれば停止
    if account_id in auto_post_threads:
        stop_event = auto_post_threads[account_id]['event']
        stop_event.set()  # スレッドを停止させる
        thread = auto_post_threads[account_id]['thread']
        thread.join()     # スレッドが終了するのを待つ
        logging.debug(f"既存のスレッドを停止しました: アカウント {account_id}")

    # 新しいスレッドを開始
    stop_event = threading.Event()
    thread = threading.Thread(target=job, args=(account_id, stop_event))
    thread.start()
    auto_post_threads[account_id] = {'thread': thread, 'event': stop_event}
    logging.debug(f"新しいスレッドを開始しました: アカウント {account_id}")

# Flaskルート（省略せずに記載します）

@app.route('/')
def index():
    global current_account_id, reset_flag
    conn = get_db_connection()
    cursor = conn.cursor()

    # アカウント一覧を取得
    cursor.execute("SELECT id, name FROM accounts")
    accounts = cursor.fetchall()

    if current_account_id:
        load_settings(current_account_id, account_settings)
        load_auto_post_status(current_account_id, is_auto_posting)
        is_posting = is_auto_posting.get(current_account_id, False)
        settings = account_settings.get(current_account_id, {})
        interval = settings.get('interval')
        specific_times = settings.get('specific_times')
        interval_type = settings.get('interval_type')
    else:
        # 最初のアカウントをデフォルトとして選択
        if accounts:
            current_account_id = accounts[0]['id']
            load_account(current_account_id)
            load_settings(current_account_id, account_settings)
            load_auto_post_status(current_account_id, is_auto_posting)
            is_posting = is_auto_posting.get(current_account_id, False)
            settings = account_settings.get(current_account_id, {})
            interval = settings.get('interval')
            specific_times = settings.get('specific_times')
            interval_type = settings.get('interval_type')
        else:
            is_posting = False
            interval = None
            specific_times = []
            interval_type = 'interval'

    # 現在のアカウント情報を取得
    cursor.execute("SELECT * FROM accounts WHERE id = ?", (current_account_id,))
    current_account = cursor.fetchone()

    # 全ての is_deleted フラグが1になった場合、全てのフラグを0にリセット
    cursor.execute("SELECT COUNT(*) FROM tweets WHERE is_deleted = 0 AND account_id = ?", (current_account_id,))
    count_not_deleted = cursor.fetchone()[0]
    if count_not_deleted == 0:
        reset_messages(current_account_id)
        flash("メッセージリストがリセットされました")
        reset_flag = True  # リセットフラグを立てる

    cursor.execute("SELECT id, message, is_deleted FROM tweets WHERE account_id = ?", (current_account_id,))
    messages = cursor.fetchall()
    conn.close()

    current_setting = f"時間間隔: {interval}時間" if interval_type == 'interval' else f"時間指定: {', '.join(specific_times)}"

    return render_template(
        'index.html',
        accounts=accounts,
        current_account_id=current_account_id,
        current_account=current_account,
        messages=messages,
        interval=interval,
        specific_times=specific_times,
        is_auto_posting=is_posting,
        current_setting=current_setting,
        interval_type=interval_type
    )

@app.route('/select_account', methods=['POST'])
def select_account():
    global current_account_id
    account_id = int(request.form['account_id'])
    current_account_id = account_id

    load_account(account_id)
    load_settings(account_id, account_settings)
    load_auto_post_status(account_id, is_auto_posting)

    return redirect(url_for('index'))

@app.route('/register_account', methods=['POST'])
def register_account_route():
    try:
        name = request.form['name']
        consumer_api_key = request.form['consumer_api_key']
        consumer_api_secret = request.form['consumer_api_secret']
        bearer_token = request.form['bearer_token']
        access_token = request.form['access_token']
        access_token_secret = request.form['access_token_secret']

        register_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret)
        flash("新しいアカウントが登録されました")
    except Exception as e:
        logging.error(f"アカウント登録中にエラーが発生しました: {e}")
        flash("アカウント登録中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/edit_account', methods=['POST'])
def edit_account_route():
    try:
        name = request.form['name']
        consumer_api_key = request.form['consumer_api_key']
        consumer_api_secret = request.form['consumer_api_secret']
        bearer_token = request.form['bearer_token']
        access_token = request.form['access_token']
        access_token_secret = request.form['access_token_secret']

        logging.debug(f"アカウント編集 - 名前: {name}, Consumer API Key: {consumer_api_key}, Consumer API Secret: {consumer_api_secret}, Bearer Token: {bearer_token}, Access Token: {access_token}, Access Token Secret: {access_token_secret}")

        edit_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, current_account_id)
        logging.debug(f"SQL更新クエリを実行しました: アカウントID {current_account_id}")

        flash("アカウント情報が更新されました")

        # 最新のアカウント情報を再読み込み
        load_account(current_account_id)
    except Exception as e:
        logging.error(f"アカウント情報の更新中にエラーが発生しました: {e}")
        flash("アカウント情報の更新中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/reset_status')
def reset_status():
    global reset_flag
    status = reset_flag
    reset_flag = False  # フラグをリセット
    return jsonify({"reset": status})

@app.route('/post', methods=['POST'])
def post():
    try:
        message = request.form['message']
        insert_message(message, current_account_id)
        flash("メッセージが追加されました")
    except Exception as e:
        logging.error(f"メッセージ追加中にエラーが発生しました: {e}")
        flash("メッセージ追加中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/set_interval', methods=['POST'])
def set_interval_route_handler():
    return set_interval_route(current_account_id, account_settings, is_auto_posting, update_auto_post_schedule)

@app.route('/start_auto_post')
def start_auto_post_handler():
    return start_auto_post(current_account_id, is_auto_posting, update_auto_post_schedule)

@app.route('/stop_auto_post')
def stop_auto_post_handler():
    return stop_auto_post(current_account_id, auto_post_threads, is_auto_posting)

@app.route('/messages')
def get_messages_route():
    try:
        messages = get_messages(current_account_id)
        return jsonify([dict(msg) for msg in messages])
    except Exception as e:
        logging.error(f"メッセージの取得中にエラーが発生しました: {e}")
        return jsonify([])

@app.route('/delete/<int:id>', methods=['POST'])
def delete_message_route(id):
    try:
        delete_message(id, current_account_id)
        flash("メッセージが削除されました")
    except Exception as e:
        logging.error(f"メッセージの削除中にエラーが発生しました: {e}")
        flash("メッセージの削除中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_message_route(id):
    try:
        new_message = request.form['new_message']
        logging.debug(f"メッセージ編集 - ID: {id}, 新しいメッセージ: {new_message}")
        update_message(new_message, id, current_account_id)
        flash("メッセージが編集されました")
    except Exception as e:
        logging.error(f"メッセージの編集中にエラーが発生しました: {e}")
        flash("メッセージの編集中にエラーが発生しました")
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('ファイルがありません')
        return redirect(url_for('index'))

    file = request.files['file']
    return upload_csv(file, current_account_id)

@app.route('/delete_all_messages', methods=['POST'])
def delete_all_messages_route():
    try:
        delete_all_messages(current_account_id)
        flash("すべてのメッセージが削除されました")
    except Exception as e:
        logging.error(f"すべてのメッセージの削除中にエラーが発生しました: {e}")
        flash("すべてのメッセージの削除中にエラーが発生しました")
    return redirect(url_for('index'))

# アプリケーション起動時に全てのアカウントの自動投稿状態をチェック
def check_and_start_auto_post():
    account_ids = get_all_account_ids()
    for account_id in account_ids:
        load_account(account_id)
        load_settings(account_id, account_settings)
        load_auto_post_status(account_id, is_auto_posting)
        if is_auto_posting.get(account_id, False):
            update_auto_post_schedule(account_id)

check_and_start_auto_post()

if __name__ == '__main__':
    app.run(debug=True)

