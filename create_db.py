import sqlite3

# データベースに接続（存在しない場合は新規作成）
conn = sqlite3.connect('tweets.db')

# カーソルオブジェクトを作成
cursor = conn.cursor()

# テーブルを作成（存在しない場合は新規作成）
cursor.execute('''
CREATE TABLE IF NOT EXISTS tweets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
)
''')

# テストメッセージを追加
test_messages = [
    "テストメッセージ1です",
    "テストメッセージ2です",
    "テストメッセージ3です"
]

for message in test_messages:
    cursor.execute("INSERT INTO tweets (message) VALUES (?)", (message,))

# 変更を保存
conn.commit()
conn.close()

print("データベースとテーブルが作成され、テストメッセージが追加されました")
