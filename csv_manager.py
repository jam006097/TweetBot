import csv
from db_manager import get_db_connection

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
