<?php
// Webhook endpoint for the Index.01 ring (help.repebble.com article 15724406).
//
// The ring POSTs multipart/form-data:
//   transcription  speech-to-text of what was said   (text transmission on)
//   audio          the raw M4A                       (audio transmission on)
//   recordedAt     ms since epoch, always present
//   client         always 'ring'
// plus whatever custom headers are configured — we require an auth token there.
//
// The transcription is handed to the same agent the chat box uses
// (src/agent/chat_handler.py), so the tool surface is identical. The ring has no
// screen, so the reply is pushed to the phone via Pushover; it is also returned
// in the HTTP body for anything that does read it.
//
// PHP 7.4 compatible. Test with:
//   curl -X POST http://localhost:8181/webhook.php \
//     -H 'Authorization: Bearer <token>' \
//     -F 'transcription=what is on my calendar today' \
//     -F "recordedAt=$(date +%s)000" -F 'client=ring'

set_time_limit(300);
// Finish the agent turn and the Pushover reply even if the ring hangs up first —
// its timeout is undocumented and a half-run turn is worse than a slow one.
ignore_user_abort(true);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$BASE = dirname(__FILE__) . '/..';
require_once dirname(__FILE__) . '/paths.php';
require_once dirname(__FILE__) . '/agent_client.php';

$DEFAULT_CLIENT_CONTEXT =
    "This message arrived from Jon's Index.01 ring: a screen-less device he talks to. "
    . "The text you receive is a speech-to-text transcription, so expect missing "
    . "punctuation, homophones, and mangled proper nouns — read it for intent rather "
    . "than literally. Jon cannot read anything on the ring; your reply reaches him as "
    . "a short push notification on his phone. So answer in at most two or three short "
    . "plain-text sentences: no markdown, no bullet lists, no headings, no preamble. If "
    . "he asked you to do something, do it and confirm in one line.\n\n"
    . "When in doubt, capture rather than guess. If the transcription is too garbled "
    . "or too ambiguous to act on confidently — the words don't parse, or you cannot "
    . "tell which person, date, or action he meant — do NOT guess at it and do NOT "
    . "just ask a question back. Call add_todo with your best literal reading of what "
    . "he said and append ' [via ring]' to the title, then reply in one line saying "
    . "you saved it to his todos because you weren't sure. He is talking to a ring "
    . "with no screen and may not read the push for hours, so a captured note he can "
    . "correct later beats a wrong action or a question left hanging.\n"
    . "This is for genuine ambiguity only. Ordinary transcription noise you can "
    . "confidently read through is not doubt — answer or act normally. A question you "
    . "can answer from the briefing data is not doubt either. Never turn a request you "
    . "understood into a todo just because it was phrased loosely.";

/**
 * Comparison key for "is this the same thing he just said".
 * Speech-to-text is not byte-stable across takes, so normalise away the parts
 * that carry no meaning: case, punctuation, and whitespace runs.
 */
function wh_text_key($text)
{
    $t = strtolower(trim($text));
    $t = preg_replace('/[^a-z0-9 ]+/', ' ', $t);
    $t = preg_replace('/\s+/', ' ', $t);
    return sha1(trim($t));
}

function wh_log($base, $line)
{
    $path = db_data_path('webhook.log');
    @file_put_contents(
        $path,
        date('Y-m-d H:i:s') . ' ' . $line . "\n",
        FILE_APPEND | LOCK_EX
    );
}

function wh_fail($base, $code, $error, $extra = array())
{
    wh_log($base, 'ERROR ' . $code . ' ' . $error);
    http_response_code($code);
    echo json_encode(array_merge(array('ok' => false, 'error' => $error), $extra));
    exit;
}

function wh_auth_token()
{
    $candidates = array();
    foreach (array('HTTP_AUTHORIZATION', 'REDIRECT_HTTP_AUTHORIZATION', 'HTTP_X_WEBHOOK_TOKEN') as $k) {
        if (!empty($_SERVER[$k])) {
            $candidates[] = (string)$_SERVER[$k];
        }
    }
    if (!$candidates && function_exists('apache_request_headers')) {
        $headers = apache_request_headers();
        foreach ($headers as $name => $value) {
            $lower = strtolower($name);
            if ($lower === 'authorization' || $lower === 'x-webhook-token') {
                $candidates[] = (string)$value;
            }
        }
    }
    if (!$candidates) {
        return '';
    }
    $raw = trim($candidates[0]);
    // Accept "Bearer xxx", "Token xxx", or a bare token.
    if (preg_match('/^(?:Bearer|Token)\s+(.*)$/i', $raw, $m)) {
        return trim($m[1]);
    }
    return $raw;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    wh_fail($BASE, 405, 'POST only');
}

$config_path = $BASE . '/config/config.json';
if (!file_exists($config_path)) {
    wh_fail($BASE, 500, 'config missing');
}
$config = json_decode(file_get_contents($config_path), true);
if (!$config) {
    wh_fail($BASE, 500, 'config unreadable');
}

$wh = isset($config['webhook']) ? $config['webhook'] : array();
if (empty($wh['enabled'])) {
    wh_fail($BASE, 503, 'webhook disabled');
}

$chat_cfg = isset($config['chat_agent']) ? $config['chat_agent'] : array();
if (empty($chat_cfg['enabled'])) {
    wh_fail($BASE, 503, 'chat agent disabled');
}

// --- auth ---------------------------------------------------------------
$expected = isset($wh['token']) ? (string)$wh['token'] : '';
if ($expected === '') {
    // Unlike the chat box (whose reachability is the page's own), this endpoint
    // is meant to be exposed to the internet. Refuse to run wide open.
    wh_fail($BASE, 500, 'webhook.token not configured');
}
if (!hash_equals($expected, wh_auth_token())) {
    wh_fail($BASE, 401, 'invalid token');
}

// --- read the request ---------------------------------------------------
$transcription = '';
$recorded_at = '';
$client = '';

if (!empty($_POST)) {
    $transcription = isset($_POST['transcription']) ? (string)$_POST['transcription'] : '';
    $recorded_at   = isset($_POST['recordedAt']) ? (string)$_POST['recordedAt'] : '';
    $client        = isset($_POST['client']) ? (string)$_POST['client'] : '';
} else {
    // JSON body — not what the ring sends, but makes the endpoint testable.
    $body = json_decode(file_get_contents('php://input'), true);
    if (is_array($body)) {
        foreach (array('transcription', 'text', 'user_message') as $k) {
            if (!empty($body[$k])) { $transcription = (string)$body[$k]; break; }
        }
        $recorded_at = isset($body['recordedAt']) ? (string)$body['recordedAt'] : '';
        $client      = isset($body['client']) ? (string)$body['client'] : '';
    }
}

$transcription = trim($transcription);
$client = $client !== '' ? $client : 'unknown';
$has_audio = !empty($_FILES['audio']['tmp_name']) && is_uploaded_file($_FILES['audio']['tmp_name']);

if (!empty($wh['save_audio']) && $has_audio) {
    $audio_dir = db_data_path('webhook_audio');
    if (!is_dir($audio_dir)) { @mkdir($audio_dir, 0755, true); }
    $stamp = preg_replace('/[^0-9]/', '', $recorded_at);
    if ($stamp === '') { $stamp = (string)time(); }
    @move_uploaded_file($_FILES['audio']['tmp_name'], $audio_dir . '/' . $stamp . '.m4a');
}

if ($transcription === '') {
    $why = $has_audio
        ? 'transcription empty (audio received — enable text transmission in the Index app)'
        : 'transcription required';
    wh_fail($BASE, 400, $why);
}
if (strlen($transcription) > 4000) {
    wh_fail($BASE, 413, 'transcription too long');
}

// --- one turn at a time, and never twice for one recording ---------------
// The ring's retry behaviour is undocumented; a retry after a slow turn must
// not run the agent (and its tools) a second time.
$dedupe_seconds = isset($wh['dedupe_seconds']) ? (int)$wh['dedupe_seconds'] : 600;
$state_path = db_data_path('webhook_state.json');
$lock_path = db_data_path('.webhook.lock');
$lock = @fopen($lock_path, 'c');
if ($lock) {
    flock($lock, LOCK_EX);
    if ($dedupe_seconds > 0 && file_exists($state_path)) {
        $prev = json_decode(@file_get_contents($state_path), true);
        $fresh = is_array($prev) && isset($prev['at'])
                 && (time() - (int)$prev['at']) < $dedupe_seconds;

        $why = '';
        if ($fresh) {
            // Same recording re-delivered (a retry of one press).
            if ($recorded_at !== '' && isset($prev['recorded_at'])
                && (string)$prev['recorded_at'] === $recorded_at) {
                $why = 'recordedAt=' . $recorded_at;
            // Same words twice in a row — a double press, or the ring
            // re-sending under a fresh recordedAt. Different recording, but
            // acting on it again would repeat whatever the first one did.
            } elseif (isset($prev['text_key'])
                      && (string)$prev['text_key'] === wh_text_key($transcription)) {
                $why = 'same transcription';
            }
        }

        if ($why !== '') {
            wh_log($BASE, 'DUPLICATE (' . $why . ') — replayed cached reply, agent not run');
            flock($lock, LOCK_UN);
            fclose($lock);
            $reply = isset($prev['reply']) ? (string)$prev['reply'] : '';
            echo json_encode(array(
                'ok'        => true,
                'duplicate' => true,
                'reply'     => $reply,
                'text'      => $reply,
            ));
            exit;
        }
    }
}

wh_log($BASE, 'IN client=' . $client . ' recordedAt=' . $recorded_at
    . ' audio=' . ($has_audio ? 'yes' : 'no') . ' text=' . json_encode($transcription));

// --- run the agent ------------------------------------------------------
$session_id = isset($wh['session_id']) ? (string)$wh['session_id'] : 'index01-ring';
if (!preg_match('/^[A-Za-z0-9_-]{8,64}$/', $session_id)) {
    $session_id = 'index01-ring';
}

$client_context = $DEFAULT_CLIENT_CONTEXT;
if (!empty($wh['system_prompt_extra'])) {
    $client_context .= ' ' . (string)$wh['system_prompt_extra'];
}

$result = db_run_agent($BASE, array(
    'session_id'     => $session_id,
    'user_message'   => $transcription,
    'shared_secret'  => isset($chat_cfg['shared_secret']) ? (string)$chat_cfg['shared_secret'] : '',
    'client_context' => $client_context,
));

$http = isset($result['http']) ? (int)$result['http'] : 0;
unset($result['http']);

if (empty($result['ok'])) {
    $error = isset($result['error']) ? (string)$result['error'] : 'agent error';
    if (!empty($wh['reply_via_pushover'])) {
        db_pushover($config, 'Index webhook failed', $error, 1);
    }
    if ($lock) { flock($lock, LOCK_UN); fclose($lock); }
    wh_fail($BASE, $http ?: 500, $error, $result);
}

$reply = isset($result['reply']) ? trim((string)$result['reply']) : '';
$max_chars = isset($wh['max_reply_chars']) ? (int)$wh['max_reply_chars'] : 900;
$push_body = $reply;
if ($max_chars > 0 && strlen($push_body) > $max_chars) {
    $push_body = substr($push_body, 0, $max_chars - 1) . '…';
}

$tool_names = array();
foreach ((isset($result['tool_events']) ? $result['tool_events'] : array()) as $ev) {
    if (!empty($ev['name'])) { $tool_names[] = $ev['name'] . (empty($ev['ok']) ? ' (failed)' : ''); }
}

wh_log($BASE, 'OUT tools=[' . implode(', ', $tool_names) . '] reply=' . json_encode($reply));

// Remember this recording so a retry replays instead of re-running.
if ($lock) {
    @file_put_contents($state_path, json_encode(array(
        'recorded_at' => $recorded_at,
        'text_key'    => wh_text_key($transcription),
        'at'          => time(),
        'reply'       => $reply,
    )));
    flock($lock, LOCK_UN);
    fclose($lock);
}

$pushed = false;
if (!empty($wh['reply_via_pushover']) && $push_body !== '') {
    $title = !empty($wh['pushover_title']) ? (string)$wh['pushover_title'] : 'Index';
    $priority = isset($wh['pushover_priority']) ? (int)$wh['pushover_priority'] : 0;
    // A ring reply is conversational, not an alert — give it its own tone
    // rather than config.agent.pushover_sound, which is the alert sound.
    $sound = isset($wh['pushover_sound']) ? (string)$wh['pushover_sound'] : null;
    $push_err = null;
    $pushed = db_pushover($config, $title, $push_body, $priority, $sound, $push_err);
    if (!$pushed) {
        wh_log($BASE, 'WARN pushover delivery failed: ' . ($push_err ? $push_err : 'unknown'));
    }
}

echo json_encode(array(
    'ok'          => true,
    'reply'       => $reply,
    'text'        => $reply,
    'pushed'      => $pushed,
    'tool_events' => isset($result['tool_events']) ? $result['tool_events'] : array(),
));
