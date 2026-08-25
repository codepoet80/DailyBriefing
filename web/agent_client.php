<?php
// Shared helpers for the endpoints that talk to the chat agent
// (web/chat.php and web/webhook.php). PHP 7.4 compatible.

/**
 * Spawn src/agent/chat_handler.py with $payload on stdin and decode its JSON.
 *
 * Returns the handler's own result array on success. On any failure to run it,
 * returns array('ok' => false, 'error' => ..., 'http' => <status to send>).
 */
function db_run_agent($base, array $payload)
{
    $python = $base . '/.venv/bin/python3';
    $script = $base . '/src/agent/chat_handler.py';
    if (!is_executable($python) || !file_exists($script)) {
        return array('ok' => false, 'error' => 'agent runtime missing', 'http' => 500);
    }

    $descriptors = array(
        0 => array('pipe', 'r'),
        1 => array('pipe', 'w'),
        2 => array('pipe', 'w'),
    );
    // Pass DB_DATA_DIR down to the handler. Without this the PHP side could be
    // pointed at a temp directory while the Python side still wrote to the real
    // one — a half-applied override is worse than none, because it looks like
    // the test is isolated when it isn't.
    $env = null;
    $data_dir = getenv('DB_DATA_DIR');
    if ($data_dir === false || trim($data_dir) === '') {
        $data_dir = isset($_SERVER['DB_DATA_DIR']) ? $_SERVER['DB_DATA_DIR'] : '';
    }
    if (trim((string)$data_dir) !== '') {
        $env = array();
        foreach ($_SERVER as $k => $v) {
            if (is_string($v) && preg_match('/^[A-Z_][A-Z0-9_]*$/', $k)) { $env[$k] = $v; }
        }
        foreach (array('PATH', 'HOME', 'LANG', 'USER') as $k) {
            $val = getenv($k);
            if ($val !== false && !isset($env[$k])) { $env[$k] = $val; }
        }
        $env['DB_DATA_DIR'] = trim((string)$data_dir);
    }

    $cmd = escapeshellarg($python) . ' ' . escapeshellarg($script);
    $proc = proc_open($cmd, $descriptors, $pipes, $base, $env);
    if (!is_resource($proc)) {
        return array('ok' => false, 'error' => 'failed to spawn agent', 'http' => 500);
    }

    fwrite($pipes[0], json_encode($payload));
    fclose($pipes[0]);

    $stdout = stream_get_contents($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    $status = proc_close($proc);

    if ($status !== 0 || $stdout === false || trim($stdout) === '') {
        $err = trim($stderr);
        if (strlen($err) > 500) { $err = substr($err, 0, 500) . '…'; }
        return array(
            'ok'     => false,
            'error'  => 'agent failed (exit ' . (int)$status . ')',
            'stderr' => $err,
            'http'   => 500,
        );
    }

    $result = json_decode($stdout, true);
    if (!is_array($result)) {
        return array(
            'ok'    => false,
            'error' => 'agent returned non-JSON',
            'raw'   => $stdout,
            'http'  => 500,
        );
    }
    return $result;
}

/**
 * Push a message via Pushover using the credentials in config.agent.
 * Mirrors send_pushover() in src/run_agent.py. Returns true on HTTP 200.
 *
 * $sound overrides config.agent.pushover_sound for this one push (null keeps
 * the global sound). An unrecognised sound name is NOT an error — Pushover
 * returns 200 and delivers with the account default (verified against a
 * deliberately bogus name), so a typo costs you the tone, not the notification.
 * List valid names with:
 *     curl -s "https://api.pushover.net/1/sounds.json?token=<app_token>"
 *
 * $err_out carries the API's reason back for the failures that are real —
 * bad token, rate limit, message too long.
 */
function db_pushover(array $config, $title, $message, $priority = 0, $sound = null, &$err_out = null)
{
    $agent = isset($config['agent']) ? $config['agent'] : array();
    $token = isset($agent['pushover_app_token']) ? (string)$agent['pushover_app_token'] : '';
    $user  = isset($agent['pushover_user_key']) ? (string)$agent['pushover_user_key'] : '';
    if ($token === '' || $user === '') {
        return false;
    }

    $fields = array(
        'token'    => $token,
        'user'     => $user,
        'title'    => $title,
        'message'  => $message,
        'priority' => (int)$priority,
    );
    if (!empty($agent['pushover_device'])) {
        $fields['device'] = (string)$agent['pushover_device'];
    }
    if ($sound !== null && $sound !== '') {
        $fields['sound'] = (string)$sound;
    } elseif (!empty($agent['pushover_sound'])) {
        $fields['sound'] = (string)$agent['pushover_sound'];
    }
    if ((int)$priority >= 2) {
        $fields['retry'] = 60;
        $fields['expire'] = 3600;
    }

    $url = 'https://api.pushover.net/1/messages.json';
    $body = '';
    $code = 0;
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($fields));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        $body = (string)curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
    } else {
        $ctx = stream_context_create(array('http' => array(
            'method'        => 'POST',
            'header'        => "Content-Type: application/x-www-form-urlencoded\r\n",
            'content'       => http_build_query($fields),
            'timeout'       => 10,
            'ignore_errors' => true,
        )));
        $resp = @file_get_contents($url, false, $ctx);
        $body = $resp === false ? '' : (string)$resp;
        $code = 0;
        if (isset($http_response_header[0])
            && preg_match('#\s(\d{3})\s#', $http_response_header[0], $m)) {
            $code = (int)$m[1];
        }
    }

    if ($code === 200) {
        return true;
    }
    // Pushover puts the reason in {"errors":["sound is invalid"]}.
    $err_out = 'HTTP ' . $code;
    $decoded = json_decode($body, true);
    if (is_array($decoded) && !empty($decoded['errors'])) {
        $err_out .= ': ' . implode('; ', (array)$decoded['errors']);
    }
    return false;
}
