/* ES5-only — runs on the 2011 webOS TouchPad browser. No fetch, no arrow fns,
 * no const/let. XHR + var only. */
(function () {
    var SECRET_KEY = 'db_chat_secret';

    function el(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        if (s === null || s === undefined) { return ''; }
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function nl2br(s) {
        return escapeHtml(s).replace(/\n/g, '<br>');
    }

    function getStoredSecret() {
        try { return window.localStorage.getItem(SECRET_KEY) || ''; }
        catch (e) { return ''; }
    }

    function setStoredSecret(v) {
        try { window.localStorage.setItem(SECRET_KEY, v); }
        catch (e) { /* legacy browser without storage; fall through */ }
    }

    function appendTurn(role, text) {
        var log = el('chat-log');
        var div = document.createElement('div');
        div.className = 'chat-turn chat-turn-' + role;
        var label = role === 'user' ? 'You' : 'Agent';
        div.innerHTML = '<span class="chat-role">' + label + ':</span> ' + nl2br(text);
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    }

    function appendToolEvents(events) {
        if (!events || !events.length) { return; }
        var log = el('chat-log');
        var div = document.createElement('div');
        div.className = 'chat-tools';
        var lines = [];
        for (var i = 0; i < events.length; i++) {
            var e = events[i];
            var mark = e.ok ? '✓' : '✗';
            lines.push(mark + ' ' + escapeHtml(e.name) + ': ' + escapeHtml(e.summary || ''));
        }
        div.innerHTML = lines.join('<br>');
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    }

    function setStatus(msg, isError) {
        var s = el('chat-status');
        s.className = 'chat-status' + (isError ? ' chat-status-error' : '');
        s.innerHTML = escapeHtml(msg || '');
    }

    function setBusy(busy) {
        el('chat-send').disabled = !!busy;
        el('chat-input').disabled = !!busy;
    }

    var CHAT_SESSION_ID = '';

    function sendMessage(text) {
        var secret = '';
        if (window.CHAT_NEEDS_SECRET) {
            secret = getStoredSecret();
            if (!secret) {
                secret = window.prompt('Enter chat passphrase:') || '';
                if (!secret) { return; }
                setStoredSecret(secret);
            }
        }

        appendTurn('user', text);
        setStatus('Thinking…');
        setBusy(true);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', 'chat.php', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) { return; }
            setBusy(false);
            var data = null;
            try { data = JSON.parse(xhr.responseText); }
            catch (e) {
                setStatus('Server error (non-JSON response)', true);
                return;
            }
            if (xhr.status === 401) {
                setStoredSecret('');
                setStatus('Wrong passphrase. Try again.', true);
                return;
            }
            if (!data || !data.ok) {
                var msg = (data && data.error) ? data.error : ('HTTP ' + xhr.status);
                setStatus('Error: ' + msg, true);
                return;
            }
            if (data.session_id) { CHAT_SESSION_ID = data.session_id; }
            appendToolEvents(data.tool_events);
            appendTurn('agent', data.reply || '(no reply)');
            var statusMsg = '';
            if (data.active_dialectic_id) {
                statusMsg = 'Active dialectic: ' + data.active_dialectic_id;
            }
            setStatus(statusMsg);
        };
        xhr.send(JSON.stringify({
            session_id: CHAT_SESSION_ID,
            user_message: text,
            shared_secret: secret
        }));
    }

    window.chatSubmit = function (evt) {
        if (evt && evt.preventDefault) { evt.preventDefault(); }
        var input = el('chat-input');
        var text = (input.value || '').replace(/^\s+|\s+$/g, '');
        if (!text) { return false; }
        input.value = '';
        sendMessage(text);
        return false;
    };
})();
