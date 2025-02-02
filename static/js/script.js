let isEditing = false;

function fetchMessages() {
    if (isEditing) return;  // 編集中の場合は更新を止める
    fetch('/messages')
        .then(response => response.json())
        .then(data => {
            const messageList = document.getElementById('message-list');
            messageList.innerHTML = '';
            data.forEach(message => {
                const li = document.createElement('li');
                li.classList.add('list-group-item');
                if (message.is_deleted) {
                    li.classList.add('deleted');
                }
                li.dataset.id = message.id;
                li.innerHTML = `
                    <span class="message-text">${message.message}${message.is_deleted ? ' (投稿済み)' : ''}</span>
                    <button
                        class="btn btn-sm btn-warning edit-btn"
                        data-id="${message.id}"
                        data-message="${message.message}"
                        onclick="editMessage(this)">編集</button>
                    <form action="/delete/${message.id}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-sm btn-danger delete-btn">削除</button>
                    </form>
                    <form action="/edit/${message.id}" method="post" class="edit-form" id="editForm-${message.id}" style="display:none;">
                        <input type="text" name="new_message" class="form-control d-inline w-75" value="${message.message}" placeholder="新しいメッセージ" style="display: none;">
                        <button type="submit" class="btn btn-sm btn-primary" style="display: none;">更新</button>
                        <button
                            type="button"
                            class="btn btn-sm btn-secondary"
                            style="display: none;"
                            data-id="${message.id}"
                            onclick="cancelEdit(this)">キャンセル</button>
                    </form>
                `;
                messageList.appendChild(li);
            });
        });
}

function checkResetStatus() {
    if (isEditing) return;  // 編集中の場合はリセットチェックを止める
    fetch('/reset_status')
        .then(response => response.json())
        .then(data => {
            if (data.reset) {
                fetchMessages();  // リセットされた場合にメッセージ一覧を更新
            }
        });
}

function editMessage(button) {
    const id = button.getAttribute('data-id');
    const messageText = button.getAttribute('data-message');

    isEditing = true;
    const li = document.querySelector(`li[data-id='${id}']`);
    li.querySelector('.message-text').style.display = 'none';
    li.querySelector('.edit-btn').style.display = 'none';
    li.querySelector('.delete-btn').style.display = 'none';

    const form = li.querySelector('.edit-form');
    form.style.display = 'block';

    const newMessageInput = form.querySelector('input[name="new_message"]');
    newMessageInput.style.display = 'inline-block';
    newMessageInput.value = messageText;

    form.querySelector('button[type="submit"]').style.display = 'inline-block';
    form.querySelector('button[type="button"]').style.display = 'inline-block';
}

function cancelEdit(button) {
    isEditing = false;
    const id = button.getAttribute('data-id');
    const li = document.querySelector(`li[data-id='${id}']`);
    li.querySelector('.message-text').style.display = 'inline';
    li.querySelector('.edit-btn').style.display = 'inline';
    li.querySelector('.delete-btn').style.display = 'inline';

    const form = li.querySelector('.edit-form');
    form.style.display = 'none';
}

function deleteMessage(id) {
    fetch(`/delete/${id}`, { method: 'POST' })
        .then(() => fetchMessages());  // メッセージを削除した後メッセージ一覧を更新
}

function deleteAllMessages() {
    if (confirm("本当にすべてのメッセージを削除しますか？")) {
        fetch('/delete_all_messages', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                // メッセージリストをクリア
                document.getElementById('message-list').innerHTML = '';
            } else {
                alert(data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
        });
    }
}

function toggleIntervalType() {
    var intervalType = document.getElementById('interval-type').value;
    if (intervalType === 'interval') {
        document.getElementById('interval-input').classList.remove('d-none');
        document.getElementById('specific-times-input').classList.add('d-none');
    } else {
        document.getElementById('interval-input').classList.add('d-none');
        document.getElementById('specific-times-input').classList.remove('d-none');
    }
}

function addSpecificTime() {
    var container = document.getElementById('specific-times-list');
    var div = document.createElement('div');
    div.className = 'input-group mb-2';
    div.innerHTML = `<input type="time" name="specific_times" class="form-control">
                    <div class="input-group-append">
                        <button type="button" class="btn btn-danger" onclick="removeSpecificTime(this)">削除</button>
                    </div>`;
    container.appendChild(div);
}

function removeSpecificTime(button) {
    button.parentElement.parentElement.remove();
}

// アクティブなタブを保存
$('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
    localStorage.setItem('activeTab', $(e.target).attr('href'));
});

// ページ読み込み時にアクティブなタブを復元
$(document).ready(function () {
    var activeTab = localStorage.getItem('activeTab');
    if (activeTab) {
        $('.nav-tabs a[href="' + activeTab + '"]').tab('show');
    } else {
        // デフォルトで最初のタブを表示
        $('.nav-tabs a:first').tab('show');
    }

    // 初期化処理
    toggleIntervalType();
    fetchMessages();
});

setInterval(fetchMessages, 3600000); // 1時間おきにメッセージを取得
setInterval(checkResetStatus, 3600000); // 1時間おきにリセットフラグをチェック
