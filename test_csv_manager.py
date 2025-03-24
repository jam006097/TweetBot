import unittest
from unittest.mock import patch, mock_open, MagicMock
from csv_manager import upload_csv, insert_messages_from_csv

class TestCSVManager(unittest.TestCase):

    @patch('csv_manager.get_db_connection')
    @patch('builtins.open', new_callable=mock_open, read_data='message1\nmessage2\n')
    @patch('csv_manager.csv.reader')
    def test_insert_messages_from_csv(self, mock_csv_reader, mock_open, mock_get_db_connection):
        mock_csv_reader.return_value = [['message1'], ['message2']]
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        failed_messages = insert_messages_from_csv('dummy.csv', 1)

        self.assertEqual(failed_messages, ['message2'])
        mock_cursor.execute.assert_any_call("SELECT COUNT(*) FROM tweets WHERE message = ? AND account_id = ?", ('message1', 1))
        mock_cursor.execute.assert_any_call("SELECT COUNT(*) FROM tweets WHERE message = ? AND account_id = ?", ('message2', 1))
        mock_cursor.execute.assert_any_call("INSERT INTO tweets (message, account_id) VALUES (?, ?)", ('message1', 1))
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch('csv_manager.flash')
    @patch('csv_manager.redirect')
    @patch('csv_manager.url_for')
    @patch('csv_manager.secure_filename')
    @patch('csv_manager.insert_messages_from_csv')
    @patch('csv_manager.logging')
    def test_upload_csv(self, mock_logging, mock_insert_messages_from_csv, mock_secure_filename, mock_url_for, mock_redirect, mock_flash):
        mock_file = MagicMock()
        mock_file.filename = 'test.csv'
        mock_secure_filename.return_value = 'test.csv'
        mock_insert_messages_from_csv.return_value = []

        response = upload_csv(mock_file, 1)

        mock_file.save.assert_called_once_with('test.csv')
        mock_insert_messages_from_csv.assert_called_once_with('test.csv', 1)
        mock_flash.assert_called_once_with('CSVファイルのメッセージが追加されました')
        mock_redirect.assert_called_once_with(mock_url_for('index'))

        # Test case for empty filename
        mock_file.filename = ''
        response = upload_csv(mock_file, 1)
        mock_flash.assert_called_with('ファイルが選択されていません')
        mock_redirect.assert_called_with(mock_url_for('index'))

        # Test case for invalid file type
        mock_file.filename = 'test.txt'
        response = upload_csv(mock_file, 1)
        mock_flash.assert_called_with('無効なファイル形式です。CSVファイルをアップロードしてください')
        mock_redirect.assert_called_with(mock_url_for('index'))

        # Test case for exception handling
        mock_file.filename = 'test.csv'
        mock_file.save.side_effect = Exception('Test Exception')
        response = upload_csv(mock_file, 1)
        mock_logging.error.assert_called_with('CSVファイルのアップロード中にエラーが発生しました: Test Exception')
        mock_flash.assert_called_with('CSVファイルのアップロード中にエラーが発生しました')
        mock_redirect.assert_called_with(mock_url_for('index'))

if __name__ == '__main__':
    unittest.main()
