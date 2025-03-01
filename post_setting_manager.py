from db_manager import get_settings, get_auto_post_status, set_interval, update_auto_post_status
from flask import request, flash, redirect, url_for
import logging
from account_manager import load_account, get_all_account_ids
from post_manager import update_auto_post_schedule

DEFAULT_INTERVAL_HOURS = 3  # デフォルトの投稿間隔（時間単位）

# 設定の読み込み
def load_settings(account_id, account_settings):
    settings = get_settings(account_id)
    if settings:
        interval_type = settings[0]['interval_type']
        if interval_type == 'interval':
            interval = settings[0]['interval']
            specific_times = []
        else:
            specific_times = [setting['specific_time'] for setting in settings if setting['specific_time']]
            interval = None
    else:
        interval_type = 'interval'
        interval = DEFAULT_INTERVAL_HOURS  # デフォルトの間隔時間を使用
        specific_times = []

    account_settings[account_id] = {
        'interval_type': interval_type,
        'interval': interval,
        'specific_times': specific_times
    }

# 自動投稿状態の取得
def load_auto_post_status(account_id, is_auto_posting):
    status_row = get_auto_post_status(account_id)
    is_auto_posting[account_id] = bool(status_row['status']) if status_row else False

def set_interval_route(current_account_id, account_settings, is_auto_posting, update_auto_post_schedule):
    try:
        interval_type = request.form['interval_type']

        if interval_type == 'interval':
            interval = int(request.form['interval'])
            specific_times = []
            flash(f"投稿間隔が{interval}時間に設定されました")
        else:
            specific_times = [time for time in request.form.getlist('specific_times') if time]
            interval = None
            flash(f"投稿時間が{', '.join(specific_times)}に設定されました")

        set_interval(interval_type, interval, specific_times, current_account_id)

        # アカウント設定を更新
        load_settings(current_account_id, account_settings)

        # 自動投稿スケジュールを更新
        update_auto_post_schedule(current_account_id, account_settings)
    except Exception as e:
        logging.error(f"投稿間隔の設定中にエラーが発生しました: {e}")
        flash("投稿間隔の設定中にエラーが発生しました")
    return redirect(url_for('index'))

def start_auto_post(current_account_id, is_auto_posting, update_auto_post_schedule, account_settings):
    try:
        is_auto_posting[current_account_id] = True

        # 自動投稿スケジュールの更新
        update_auto_post_schedule(current_account_id, account_settings)

        # auto_post_statusテーブルにデータを保存
        update_auto_post_status(current_account_id, True)

        flash("自動投稿実行中")
    except Exception as e:
        logging.error(f"自動投稿の開始中にエラーが発生しました: {e}")
        flash("自動投稿の開始中にエラーが発生しました")
    return redirect(url_for('index'))

def stop_auto_post(current_account_id, auto_post_threads, is_auto_posting):
    try:
        is_auto_posting[current_account_id] = False

        # スレッドを停止
        if current_account_id in auto_post_threads:
            stop_event = auto_post_threads[current_account_id]['event']
            stop_event.set()
            thread = auto_post_threads[current_account_id]['thread']
            thread.join()
            logging.debug(f"スレッドを停止しました: アカウント {current_account_id}")
            del auto_post_threads[current_account_id]

        # auto_post_statusテーブルにデータを保存
        update_auto_post_status(current_account_id, False)

        flash("自動投稿を停止しました")
    except Exception as e:
        logging.error(f"自動投稿の停止中にエラーが発生しました: {e}")
        flash("自動投稿の停止中にエラーが発生しました")
    return redirect(url_for('index'))

def check_and_start_auto_post(account_settings, is_auto_posting):
    account_ids = get_all_account_ids()
    for account_id in account_ids:
        load_account(account_id)
        load_settings(account_id, account_settings)
        load_auto_post_status(account_id, is_auto_posting)
        if is_auto_posting.get(account_id, False):
            update_auto_post_schedule(account_id, account_settings)
