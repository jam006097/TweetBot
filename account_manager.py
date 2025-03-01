import logging
import tweepy
from db_manager import get_account, insert_account, update_account, get_db_connection

clients = {}

def load_account(account_id):
    account = get_account(account_id)
    logging.debug(f"アカウントを読み込みました: {account}")

    if account:
        try:
            client = tweepy.Client(
                bearer_token=account['bearer_token'],
                consumer_key=account['consumer_api_key'],
                consumer_secret=account['consumer_api_secret'],
                access_token=account['access_token'],
                access_token_secret=account['access_token_secret']
            )
            clients[account_id] = client
            logging.debug(f"Twitterクライアントの初期化に成功しました: アカウント {account_id}")
        except Exception as e:
            logging.error(f"Twitterクライアントの初期化中にエラーが発生しました: アカウント {account_id}: {e}")
    else:
        logging.error(f"アカウントが見つかりません: アカウントID {account_id}")

def register_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret):
    insert_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret)

def edit_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, account_id):
    update_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, account_id)

# データベースから全アカウントIDを取得する関数
def get_all_account_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM accounts')
    account_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()
    return account_ids
