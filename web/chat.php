<?php
// Chat endpoint. POSTs from web/chat.js. Spawns src/agent/chat_handler.py and
// returns its JSON reply.

set_time_limit(300);
ignore_user_abort(false);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(array('ok' => false, 'error' => 'POST only'));
    exit;
}

$BASE = dirname(__FILE__) . '/..';
$config_path = $BASE . '/config/config.json';
if (!file_exists($config_path)) {
    http_response_code(500);
    echo json_encode(array('ok' => false, 'error' => 'config missing'));
    exit;
}
$config = json_decode(file_get_contents($config_path), true);
if (!$config) {
    http_response_code(500);
    echo json_encode(array('ok' => false, 'error' => 'config unreadable'));
    exit;
}

$chat_cfg = isset($config['chat_agent']) ? $config['chat_agent'] : array();
if (empty($chat_cfg['enabled'])) {
    http_response_code(503);
    echo json_encode(array('ok' => false, 'error' => 'chat agent disabled'));
    exit;
}

$body_raw = file_get_contents('php://input');
$body = json_decode($body_raw, true);
if (!is_array($body)) {
    http_response_code(400);
    echo json_encode(array('ok' => false, 'error' => 'invalid JSON body'));
    exit;
}

$user_message = isset($body['user_message']) ? trim((string)$body['user_message']) : '';
if ($user_message === '') {
    http_response_code(400);
    echo json_encode(array('ok' => false, 'error' => 'user_message required'));
    exit;
}
if (strlen($user_message) > 4000) {
    http_response_code(413);
    echo json_encode(array('ok' => false, 'error' => 'message too long'));
    exit;
}

$shared_secret = isset($chat_cfg['shared_secret']) ? (string)$chat_cfg['shared_secret'] : '';
if ($shared_secret !== '') {
    $supplied = isset($body['shared_secret']) ? (string)$body['shared_secret'] : '';
    if (!hash_equals($shared_secret, $supplied)) {
        http_response_code(401);
        echo json_encode(array('ok' => false, 'error' => 'invalid shared secret'));
        exit;
    }
}

$session_id = '';
if (!empty($body['session_id']) && is_string($body['session_id'])) {
    if (preg_match('/^[A-Za-z0-9_-]{8,64}$/', $body['session_id'])) {
        $session_id = $body['session_id'];
    }
}
if ($session_id === '' && !empty($_COOKIE['db_chat_sid'])) {
    if (preg_match('/^[A-Za-z0-9_-]{8,64}$/', $_COOKIE['db_chat_sid'])) {
        $session_id = $_COOKIE['db_chat_sid'];
    }
}

$payload = array(
    'session_id'    => $session_id,
    'user_message'  => $user_message,
    'shared_secret' => isset($body['shared_secret']) ? (string)$body['shared_secret'] : '',
);
$payload_json = json_encode($payload);

$python = $BASE . '/.venv/bin/python3';
$script = $BASE . '/src/agent/chat_handler.py';
if (!is_executable($python) || !file_exists($script)) {
    http_response_code(500);
    echo json_encode(array('ok' => false, 'error' => 'agent runtime missing'));
    exit;
}

$descriptors = array(
    0 => array('pipe', 'r'),
    1 => array('pipe', 'w'),
    2 => array('pipe', 'w'),
);
$cwd = $BASE;
$env = null;

$cmd = escapeshellarg($python) . ' ' . escapeshellarg($script);
$proc = proc_open($cmd, $descriptors, $pipes, $cwd, $env);
if (!is_resource($proc)) {
    http_response_code(500);
    echo json_encode(array('ok' => false, 'error' => 'failed to spawn agent'));
    exit;
}

fwrite($pipes[0], $payload_json);
fclose($pipes[0]);

$stdout = stream_get_contents($pipes[1]);
$stderr = stream_get_contents($pipes[2]);
fclose($pipes[1]);
fclose($pipes[2]);
$status = proc_close($proc);

if ($status !== 0 || $stdout === false || trim($stdout) === '') {
    http_response_code(500);
    $err = trim($stderr);
    if (strlen($err) > 500) { $err = substr($err, 0, 500) . '…'; }
    echo json_encode(array(
        'ok' => false,
        'error' => 'agent failed (exit ' . (int)$status . ')',
        'stderr' => $err,
    ));
    exit;
}

$result = json_decode($stdout, true);
if (!is_array($result)) {
    http_response_code(500);
    echo json_encode(array('ok' => false, 'error' => 'agent returned non-JSON', 'raw' => $stdout));
    exit;
}

if (!empty($result['session_id'])) {
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
    setcookie('db_chat_sid', $result['session_id'], array(
        'expires'  => time() + 86400 * 30,
        'path'     => '/',
        'secure'   => $secure,
        'httponly' => true,
        'samesite' => 'Lax',
    ));
}

echo json_encode($result);
