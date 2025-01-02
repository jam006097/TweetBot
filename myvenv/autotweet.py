import os
import tweepy
import schedule
import time
import sqlite3
from datetime import datetime

consumer_api_key = 's8IRd8glsLKdL5RIrHjwtBRe8'
consumer_api_secret = "HM16HLqBID4raQnIt93fj6ufPHh8rzJYwSzuh67th07oIU7qi8"
bearer_token = "AAAAAAAAAAAAAAAAAAAAAK1dxwEAAAAAuEa%2BFBEfpkS9WwrD%2FYKgUVr%2BE5I%3DYB78GMqRAbclRd2InuviuVCO4mOJnItfevDzIBPfjqJGuCllzj"
access_token = "1874014622359142400-080y70SvY0zZKaF9UgFWbnzq80cvRG"
access_token_secret = "xOFXEQThzirVFbr8H1seUCerNNtX4MYRVr8JxwJxmVWpo"

client = tweepy.Client(
    bearer_token=bearer_token,
    consumer_key=consumer_api_key,
    consumer_secret=consumer_api_secret,
    access_token=access_token,
    access_token_secret=access_token_secret
)

print("Twitter認証完了")

conn = sqlite3.connect('tweets.db')
cursor = conn.cursor()

def get_message_from_db():
    cursor.execute("SELECT message FROM tweets WHERE is_deleted = 0 ORDER BY RANDOM() LIMIT 1")
    result = cursor.fetchone()
    if result:
        # メッセージを取得後、論理削除フラグを設定する
        cursor.execute("UPDATE tweets SET is_deleted = 1 WHERE message = ?", (result[0],))
        conn.commit()
        return result[0]
    return None

def post_message():
    global post_count
    message = get_message_from_db()
    if message:
        try:
            response = client.create_tweet(text=message)
            print(f"投稿完了: {message} at {datetime.now()}")
            print(f"Tweet ID: {response.data['id']}")
        except Exception as e:
            print(f"エラーが発生しました: {e}")
    else:
        print("メッセージが見つかりませんでした")

def job():
    post_message()

# 5分おきに自動投稿を設定
schedule.every(5).minutes.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)

conn.close()
client.close()
