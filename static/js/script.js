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
                    <form action="/edit/${message[0]}" method="post" class="edit-form " id="editForm-${message[0]}" style="display:none;">
                        <input type="text" name="new_message" class="form-control d-inline w-75" value="${message[1]}" placeholder="新しいメッセージ" style="display:none;">
                        <button type="submit" class="btn btn-sm btn-primary" style="display:none;">更新</button>
                        <button type="button" class="btn btn-sm btn-secondary" style="display:none;" onclick="cancelEdit('${message[0]}')">キャンセル</button>
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
    isEditing = true;
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
    isEditing = false;
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

function setIntervalSettings() {
    const intervalType = document.getElementById('interval-type').value;
    const interval = document.querySelector('input[name="interval"]').value;
    const specificTimes = Array.from(document.querySelectorAll('input[name="specific_times"]')).map(input => input.value);

    fetch('/set_interval', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            interval_type: intervalType,
            interval: interval,
            specific_times: specificTimes,
        }),
    }).then(response => response.json())
      .then(data => {
          if (data.success) {
              alert('設定が更新されました');
              fetchMessages();  // 更新が成功したらメッセージ一覧を再取得
          } else {
              alert('設定の更新に失敗しました: ' + data.error);
          }
      });
}

document.getElementById('interval-type').addEventListener('change', setIntervalSettings);
document.querySelector('input[name="interval"]').addEventListener('change', setIntervalSettings);
document.querySelectorAll('input[name="specific_times"]').forEach(input => {
    input.addEventListener('change', setIntervalSettings);
});

