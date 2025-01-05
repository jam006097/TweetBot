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
                li.dataset.id = message[0];
                li.innerHTML = `
                    <span class="message-text">${message[1]}${message[2] ? ' (投稿済み)' : ''}</span>
                    <button class="btn btn-sm btn-warning edit-btn" onclick="editMessage('${message[0]}')">編集</button>
                    <button class="btn btn-sm btn-danger delete-btn" onclick="deleteMessage('${message[0]}')">削除</button>
                    <form action="/edit/${message[0]}" method="post" class="edit-form d-inline" id="editForm-${message[0]}" style="display:none;">
                        <input type="text" name="new_message" class="form-control d-inline w-75" value="${message[1]}" placeholder="新しいメッセージ">
                        <button type="submit" class="btn btn-sm btn-primary">更新</button>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="cancelEdit('${message[0]}')">キャンセル</button>
                    </form>
                `;
                if (message[2]) {
                    li.classList.add('deleted');
                }
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

function editMessage(id) {
    //isEditing = true;
    const li = document.querySelector(`li[data-id='${id}']`);
    li.querySelector('.message-text').style.display = 'none';
    li.querySelector('.edit-btn').style.display = 'none';
    li.querySelector('.delete-btn').style.display = 'none';

    const form = li.querySelector('.edit-form');
    form.style.display = 'block';  // フォーム全体を表示

    form.querySelector('input[name="new_message"]').style.display = 'inline-block';  // 入力欄を表示
    form.querySelector('button[type="submit"]').style.display = 'inline-block';  // 更新ボタンを表示
    form.querySelector('button[type="button"]').style.display = 'inline-block';  // キャンセルボタンを表示
}

function cancelEdit(id) {
    //isEditing = false;
    const li = document.querySelector(`li[data-id='${id}']`);
    li.querySelector('.message-text').style.display = 'inline';
    li.querySelector('.edit-btn').style.display = 'inline';
    li.querySelector('.delete-btn').style.display = 'inline';

    const form = li.querySelector('.edit-form');
    form.style.display = 'none';
}


function deleteMessage(id) {
    fetch(`/delete/${id}`, { method: 'POST' })
        .then(() => fetchMessages());  // メッセージを削除した後、メッセージ一覧を更新
}

function toggleIntervalType() {
    const intervalType = document.getElementById('interval-type').value;
    const intervalInput = document.getElementById('interval-input');
    const specificInput = document.getElementById('specific-input');
    
    if (intervalType === 'interval') {
        intervalInput.classList.remove('hidden');
        specificInput.classList.add('hidden');
    } else {
        intervalInput.classList.add('hidden');
        specificInput.classList.remove('hidden');
    }
}

function removeSpecificTime(time) {
    fetch(`/remove_specific_time?time=${time}`, { method: 'POST' })
        .then(() => location.reload());
}

setInterval(fetchMessages, 3600000); // 1時間おきにメッセージを取得
setInterval(checkResetStatus, 3600000); // 1時間おきにリセットフラグをチェック
