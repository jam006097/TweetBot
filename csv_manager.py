import csv
from db_manager import get_db_connection
from flask import flash, redirect, url_for
from werkzeug.utils import secure_filename
import logging
from db_manager import insert_messages_from_csv

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

def upload_csv(file, current_account_id):
    try:
        if file.filename == '':
            flash('ファイルが選択されていません')
            return redirect(url_for('index'))

        if file and file.filename.endswith('.csv'):
            filename = secure_filename(file.filename)
            file.save(filename)
            failed_messages = insert_messages_from_csv(filename, current_account_id)
            flash('CSVファイルのメッセージが追加されました')
            if failed_messages:
                # Limit the size of the flash message
                failed_message_preview = ', '.join(failed_messages[:5])
                flash(f"重複のため保存できなかったメッセージ: {failed_message_preview} 他 {len(failed_messages) - 5} 件" if len(failed_messages) > 5 else f"重複のため保存できなかったメッセージ: {failed_message_preview}")
        else:
            flash('無効なファイル形式です。CSVファイルをアップロードしてください')
    except Exception as e:
        logging.error(f"CSVファイルのアップロード中にエラーが発生しました: {e}")
        flash("CSVファイルのアップロード中にエラーが発生しました")
    return redirect(url_for('index'))
