from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import logging
from dotenv import load_dotenv
from db_manager import (
    get_db_connection, get_all_account_ids, get_settings, get_auto_post_status, get_message,
    reset_messages, insert_message, set_interval, update_auto_post_status,
    get_messages, delete_message, update_message, delete_all_messages
)
from csv_manager import insert_messages_from_csv, upload_csv
from account_manager import load_account, register_account, edit_account, clients, get_all_account_ids
from post_setting_manager import load_settings, load_auto_post_status, set_interval_route, start_auto_post, stop_auto_post
from post_manager import update_auto_post_schedule, post_message, auto_post_threads

# 環境変数の読み込み
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')

# ログ設定
LOG_FILENAME = 'app.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

# グローバル変数の初期化
reset_flag = False
current_account_id = None

# アカウントごとのデータを管理する辞書
account_settings = {}   # アカウントごとの設定
is_auto_posting = {}    # アカウントごとの自動投稿状態

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
            update_auto_post_schedule(account_id, account_settings)

check_and_start_auto_post()

if __name__ == '__main__':
    app.run(debug=True)

