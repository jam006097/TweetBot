import sqlite3

# データベースに接続（存在しない場合は新規作成）
conn = sqlite3.connect('tweets.db')

# カーソルオブジェクトを作成
cursor = conn.cursor()

# tweetsテーブルを作成（存在しない場合は新規作成）
cursor.execute('''
CREATE TABLE IF NOT EXISTS tweets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
)
''')

# settingsテーブルを作成（存在しない場合は新規作成）
cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interval_type TEXT,
    interval INTEGER,
    specific_time TEXT
)
''')

# 変更を保存
conn.commit()
conn.close()

print("データベースとテーブルが作成されました")
