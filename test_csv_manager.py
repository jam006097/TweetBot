import unittest
from unittest.mock import patch, MagicMock
from csv_manager import insert_messages_from_csv

class TestCSVManager(unittest.TestCase):

    @patch('csv_manager.get_db_connection')
    def test_insert_messages_from_csv(self, mock_get_db_connection):
        # モックの設定
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # テストデータ
        account_id = 1
        filename = 'test.csv'
        csv_data = [
            ['Hello'],
            ['Hello'],  # 重複データ
        ]

        # データベースの状態をシミュレート
        messages_in_db = set()

        # モックの動作設定
        def mock_execute(query, params):
            if "SELECT COUNT(*) FROM tweets" in query:
                message = params[0]
                if message in messages_in_db:
                    mock_cursor.fetchone.return_value = [1]  # メッセージは既に存在
                else:
                    mock_cursor.fetchone.return_value = [0]  # メッセージは存在しない
            elif "INSERT INTO tweets" in query:
                message = params[0]
                messages_in_db.add(message)

        mock_cursor.execute.side_effect = mock_execute

        # CSVファイルのモック
        csv_content = '\n'.join([','.join(row) for row in csv_data])
        with patch('builtins.open', unittest.mock.mock_open(read_data=csv_content)):
            failed_messages = insert_messages_from_csv(filename, account_id)

        # アサーション
        self.assertEqual(len(failed_messages), 1)
        self.assertIn('Hello', failed_messages)
        self.assertEqual(mock_cursor.execute.call_count, 3)  # 2回のSELECTと1回のINSERT

if __name__ == '__main__':
    unittest.main()
