import threading
import logging
from datetime import datetime, timedelta
import tweepy  # 追加
from db_manager import get_message
from account_manager import clients

INTERVAL_IN_SECONDS = 3600  # 1時間（秒単位）
CHECK_INTERVAL = 60         # 1分（秒単位）
MINIMUM_POST_INTERVAL_MINUTES = 1  # 重複回避のための最小投稿間隔（分単位）を1分に変更
DEFAULT_INTERVAL_HOURS = 3  # デフォルトの投稿間隔（時間単位）

post_lock = threading.Lock()  # 投稿用のロック
post_disable_until = {}  # アカウントごとの投稿停止時間
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
def job(account_id, stop_event, account_settings):
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
def update_auto_post_schedule(account_id, account_settings):
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
    thread = threading.Thread(target=job, args=(account_id, stop_event, account_settings))
    thread.start()
    auto_post_threads[account_id] = {'thread': thread, 'event': stop_event}
    logging.debug(f"新しいスレッドを開始しました: アカウント {account_id}")
