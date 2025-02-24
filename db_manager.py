import sqlite3
import logging
import csv

def get_db_connection():
    conn = sqlite3.connect('tweets.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ...existing code...
    conn.commit()
    conn.close()

def get_all_account_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM accounts')
    account_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()
    return account_ids

def get_account(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    account = cursor.fetchone()
    conn.close()
    return account

def get_settings(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT interval_type, interval, specific_time FROM settings WHERE account_id = ?", (account_id,))
    settings = cursor.fetchall()
    conn.close()
    return settings

def get_auto_post_status(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM auto_post_status WHERE account_id = ?', (account_id,))
    status_row = cursor.fetchone()
    conn.close()
    return status_row

def get_message(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, message FROM tweets WHERE is_deleted = 0 AND account_id = ? ORDER BY RANDOM() LIMIT 1", (account_id,))
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE tweets SET is_deleted = 1 WHERE id = ?", (result['id'],))
        conn.commit()
    conn.close()
    return result['message'] if result else None

def reset_messages(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tweets SET is_deleted = 0 WHERE account_id = ?", (account_id,))
    conn.commit()
    conn.close()

def insert_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO accounts (name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret))
    conn.commit()
    conn.close()

def update_account(name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE accounts
    SET name = ?, consumer_api_key = ?, consumer_api_secret = ?, bearer_token = ?, access_token = ?, access_token_secret = ?
    WHERE id = ?
    """, (name, consumer_api_key, consumer_api_secret, bearer_token, access_token, access_token_secret, account_id))
    conn.commit()
    conn.close()

def insert_message(message, account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tweets (message, account_id) VALUES (?, ?)", (message, account_id))
    conn.commit()
    conn.close()

def set_interval(interval_type, interval, specific_times, account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM settings WHERE account_id = ?", (account_id,))
    if interval_type == 'interval':
        cursor.execute("INSERT INTO settings (interval_type, interval, account_id) VALUES (?, ?, ?)", (interval_type, interval, account_id))
    else:
        for time_value in specific_times:
            cursor.execute("INSERT INTO settings (interval_type, specific_time, account_id) VALUES (?, ?, ?)", (interval_type, time_value, account_id))
    conn.commit()
    conn.close()

def update_auto_post_status(account_id, status):
    conn = get_db_connection()
    conn.execute('INSERT OR REPLACE INTO auto_post_status (account_id, status) VALUES (?, ?)', (account_id, status))
    conn.commit()
    conn.close()

def get_messages(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, message, is_deleted FROM tweets WHERE account_id = ?", (account_id,))
    messages = cursor.fetchall()
    conn.close()
    return messages

def delete_message(id, account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tweets WHERE id = ? AND account_id = ?", (id, account_id))
    conn.commit()
    conn.close()

def update_message(new_message, id, account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tweets SET message = ? WHERE id = ? AND account_id = ?", (new_message, id, account_id))
    conn.commit()
    conn.close()

def insert_messages_from_csv(filename, account_id):
    failed_messages = []
    with open(filename, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        conn = get_db_connection()
        cursor = conn.cursor()
        for row in reader:
            if row:  # 空の行を無視
                cursor.execute("SELECT COUNT(*) FROM tweets WHERE message = ? AND account_id = ?", (row[0], account_id))
                count = cursor.fetchone()[0]
                if count == 0:
                    cursor.execute("INSERT INTO tweets (message, account_id) VALUES (?, ?)", (row[0], account_id))
                else:
                    failed_messages.append(row[0])
        conn.commit()
        conn.close()
    return failed_messages

def delete_all_messages(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tweets WHERE account_id = ?", (account_id,))
    conn.commit()
    conn.close()
