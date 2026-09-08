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
    . "EVERY message you receive here is deliberate. Jon must press and hold a "
    . "button, speak into the ring, and release it — there is no accidental or "
    . "background capture, and nothing reaches you that he did not choose to say. "
    . "So never treat input as stray, unintended, misdirected, or out of "
    . "character, and NEVER decline an action on those grounds. Whether a message "
    . "seems odd, blunt, affectionate, trivial, or oddly worded is not your "
    . "concern and not your call. If he told you to send something, send it "
    . "exactly as he said it — do not soften it, second-guess whether he really "
    . "meant it, or withhold it for his own good.\n"
    . "Doing nothing is never an available option. Every message ends in exactly "
    . "one of: you performed the action, you answered from the briefing data, or "
    . "you captured it with add_todo. \"I'll let it go\" is a failure.\n"
    . "Read each message against the one before it. A transcription that looks "
    . "like a fragment is usually the continuation of the exchange in progress — "
    . "if your last turn was about texting someone, a bare phrase is the message "
    . "he wants sent, not a stray remark.\n\n"
    . "THE TWO RULES OF THIS CHANNEL, above everything else:\n"
    . "1. IF IN DOUBT, PUT IT ON THE TODO LIST. Any uncertainty at all — garbled "
    . "words, unclear intent, missing details — resolves to add_todo with your "
    . "best literal reading plus ' [via ring]'. Never drop it, never defer it, "
    . "never ask about it.\n"
    . "2. OTHERWISE, JUST DO WHAT HE SAID. No follow-up questions, no "
    . "negotiating, no suggesting a better approach, no explaining why you would "
    . "have done it differently. He is not able to reply, so anything other than "
    . "doing it or filing it is a dead end.\n"
    . "Do not argue with him, correct him, or push back on an instruction. If you "
    . "think he is wrong, you are still not able to discuss it on this channel — "
    . "do the thing, or file it. These two rules are enforced downstream: a reply "
    . "that asks a question with no action behind it gets his words filed as a "
    . "todo automatically and your question discarded. So asking accomplishes "
    . "nothing except making the result worse.\n\n"
    . "NEVER ask a clarifying question. You cannot have a conversation over this "
    . "channel — Jon is talking to a ring with no screen and may not read the push "
    . "for hours, so a question just strands the request. If you are not confident "
    . "enough to act, CAPTURE INSTEAD: call add_todo with your best literal reading "
    . "of what he said, append ' [via ring]' to the title, and reply in one line "
    . "saying you saved it because you weren't sure. Capturing is always available "
    . "and is never the wrong answer; asking always is.\n"
    . "This covers every kind of doubt, not just bad audio. The words may transcribe "
    . "cleanly and still leave you unsure WHAT HE WANTS DONE — \"make a lunch\" could "
    . "be a todo, a calendar event, or a reminder. That is exactly the case to "
    . "capture: file it as a todo verbatim and let him sort it out later. Do not "
    . "weigh which interpretation is likeliest and act on it, and do not ask which "
    . "he meant.\n"
    . "A question you can answer from the briefing data is not doubt — answer it, "
    . "do not file it.\n"
    . "The ' [via ring]' marker means YOU chose to file this because you were not "
    . "sure, so Jon knows which items need a second look. Leave it off only when "
    . "the action was unmistakable — \"order replacement blind\" is plainly a todo, "
    . "or he said \"add a todo\" outright. WHEN THE CALL IS CLOSE, MARK IT. A stray "
    . "marker costs him nothing; a missing one hides that you guessed.";

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

/**
 * Ring rule 1, enforced rather than requested: if in doubt, it goes on the
 * todo list.
 *
 * The ring cannot display or answer a question, so a question-shaped reply with
 * no action behind it is a silently dropped request. The client context has
 * banned clarifying questions since day one and the agent still asks them, so
 * compliance is not something to keep hoping for. When it happens we file the
 * transcription ourselves, with no model in the loop.
 */
function wh_force_capture($base, $text)
{
    $python = $base . '/.venv/bin/python3';
    $script = $base . '/src/capture_todo.py';
    if (!is_executable($python) || !file_exists($script)) { return false; }
    $title = trim($text);
    if ($title === '') { return false; }
    if (strpos($title, '[via ring]') === false) { $title .= ' [via ring]'; }
    $cmd = escapeshellarg($python) . ' ' . escapeshellarg($script) . ' '
         . escapeshellarg($title) . ' 2>&1';
    $out = array(); $rc = 0;
    @exec($cmd, $out, $rc);
    return $rc === 0;
}

/**
 * Is this reply asking Jon something rather than telling him something?
 * A trailing '?' is the reliable signal — answers to his questions do not end
 * that way, and the agent's clarifying questions always do.
 */
function wh_is_question($reply)
{
    $t = rtrim(trim($reply), " \t\n\r\0\x0B\"'”’)");
    return $t !== '' && substr($t, -1) === '?';
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

// The ring's speech-to-text mishears the same command openings repeatedly —
// "text Nicole" comes through as "technically" often enough to be worth a
// lookup table rather than hoping the agent guesses. config.webhook
// .transcription_fixes maps misheard -> intended.
//
// Anchored at the START of the message on purpose. These are command openings,
// and an unanchored rewrite would corrupt ordinary speech: "that's technically
// true" must not become "that's text Nicole true". A false match is still
// possible ("Technically the server is down"), so the substitution is logged
// and shown in the push — a wrong rewrite must be visible, not silent.
$transcription_original = $transcription;
$applied_fix = null;
$fixes = isset($wh['transcription_fixes']) && is_array($wh['transcription_fixes'])
    ? $wh['transcription_fixes'] : array();
foreach ($fixes as $wrong => $right) {
    $wrong = trim((string)$wrong);
    if ($wrong === '') { continue; }
    $pattern = '/^\s*' . preg_quote($wrong, '/') . '\b[\s,]*/i';
    if (preg_match($pattern, $transcription)) {
        $transcription = preg_replace($pattern, (string)$right . ' ', $transcription, 1);
        $transcription = trim($transcription);
        $applied_fix = $wrong . ' -> ' . $right;
        break;
    }
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
    . ' audio=' . ($has_audio ? 'yes' : 'no') . ' text=' . json_encode($transcription_original)
    . ($applied_fix ? ' fix=[' . $applied_fix . '] read_as=' . json_encode($transcription) : ''));

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

$events = isset($result['tool_events']) ? $result['tool_events'] : array();

// ENFORCE the two ring rules. The client context states both; the agent has
// repeatedly ignored them, and a rule the device cannot survive being broken
// has to hold mechanically, not by persuasion.
//
// A reply that asks a question with no action behind it is a dropped request:
// Jon cannot answer it, and may not read the push for hours. So file the
// transcription and replace the reply with the truth about what happened.
$did_something = false;
foreach ($events as $ev) { if (!empty($ev['ok'])) { $did_something = true; break; } }

$forced_capture = false;
if (!$did_something && wh_is_question($reply)) {
    $forced_capture = wh_force_capture($BASE, $transcription);
    wh_log($BASE, 'ENFORCE agent asked a question with no action; '
        . ($forced_capture ? 'captured to todo list' : 'CAPTURE FAILED'));
    if ($forced_capture) {
        $events[] = array(
            'name' => 'add_todo',
            'ok' => true,
            'summary' => 'Added todo: ' . trim($transcription) . ' [via ring]',
        );
        $reply = "I wasn't sure, so I put it on your todo list.";
    }
}

$tool_names = array();
foreach ($events as $ev) {
    if (!empty($ev['name'])) { $tool_names[] = $ev['name'] . (empty($ev['ok']) ? ' (failed)' : ''); }
}

// The push reports what ACTUALLY happened, not what the agent said it did.
//
// The reply is the agent's narration and can be wrong: it once claimed "added
// to your todo list" on turns where no tool ran at all, and the push confirmed
// that lie for two days. Tool results come from the effect itself, so they
// cannot claim a write that did not occur. Same principle the scheduled-send
// sweeper uses — confirm on effect, never on intent.
//
// Turns that ran no tools (questions) still push the reply: nothing was
// claimed to change, so there is nothing to verify. The visible consequence is
// that an action-shaped request with no "✓" line did not happen.
$confirm_lines = array();
$any_failed = false;
foreach ($events as $ev) {
    $name = !empty($ev['name']) ? (string)$ev['name'] : 'tool';
    $summary = isset($ev['summary']) ? trim((string)$ev['summary']) : '';
    if (empty($ev['ok'])) {
        $any_failed = true;
        $confirm_lines[] = '✗ ' . $name . ' FAILED' . ($summary !== '' ? ': ' . $summary : '');
    } else {
        $confirm_lines[] = '✓ ' . ($summary !== '' ? $summary : $name);
    }
}

if ($confirm_lines) {
    $push_body = implode("\n", $confirm_lines);
    if ($reply !== '') { $push_body .= "\n\n" . $reply; }
} else {
    $push_body = $reply;
}
// If we rewrote what he said, say so — a bad substitution has to be caught by
// eye, and the only place he sees anything is this push.
if ($applied_fix !== null) {
    $push_body .= "\n\n(heard \"" . $transcription_original . "\")";
}
if ($max_chars > 0 && strlen($push_body) > $max_chars) {
    $push_body = substr($push_body, 0, $max_chars - 1) . '…';
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
    // A write that failed is not conversational — make sure it is noticed.
    if ($any_failed) {
        $title = $title . ' — action failed';
        if ($priority < 1) { $priority = 1; }
    }
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
    'tool_events' => $events,   // includes a forced capture, if one happened
));
