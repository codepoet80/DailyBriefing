<?php
// Heartbeat sink for machines that can reach this box but can't be polled from
// it — the locked-down Windows laptop in the basement being the reason this
// exists. It POSTs "I'm alive and Outlook is up" on a timer; the briefing build
// alarms on the ABSENCE of that, which is what catches a shutdown, a dead
// network, or the reporting script itself dying. A "tell me when it breaks"
// design cannot report its own death.
//
// POST (JSON body or form fields). Authorization: Bearer <heartbeats.token> is
// only required when heartbeats.token is non-empty; leave it empty for no auth.
//   name     required  short id for the machine, e.g. "work-laptop"
//   ok       optional  "1"/"true"/"0"/"false" — overall health, default true
//   status   optional  short machine-readable state, e.g. "outlook_relaunched"
//   detail   optional  free text for the briefing/alert
//   extra    optional  JSON object of anything else worth keeping
//
// Writes data/heartbeats/<name>.json. LAN only — do not expose this through the
// public nginx proxy the way webhook.php is.
//
// PHP 7.4 compatible.

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

require_once dirname(__FILE__) . '/paths.php';

$BASE = dirname(__FILE__) . '/..';

function hb_fail($code, $error)
{
    http_response_code($code);
    echo json_encode(array('ok' => false, 'error' => $error));
    exit;
}

function hb_token()
{
    foreach (array('HTTP_AUTHORIZATION', 'REDIRECT_HTTP_AUTHORIZATION', 'HTTP_X_HEARTBEAT_TOKEN') as $k) {
        if (!empty($_SERVER[$k])) {
            $raw = trim((string)$_SERVER[$k]);
            if (preg_match('/^(?:Bearer|Token)\s+(.*)$/i', $raw, $m)) { return trim($m[1]); }
            return $raw;
        }
    }
    return '';
}

function hb_bool($v, $default = true)
{
    if ($v === null || $v === '') { return $default; }
    if (is_bool($v)) { return $v; }
    $s = strtolower(trim((string)$v));
    return !in_array($s, array('0', 'false', 'no', 'off', 'down'), true);
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    hb_fail(405, 'POST only');
}

$config_path = $BASE . '/config/config.json';
$config = file_exists($config_path) ? json_decode(file_get_contents($config_path), true) : null;
if (!$config) { hb_fail(500, 'config unreadable'); }

$hb = isset($config['heartbeats']) ? $config['heartbeats'] : array();
if (empty($hb['enabled'])) { hb_fail(503, 'heartbeats disabled'); }

// Token is OPTIONAL. Leave heartbeats.token empty and the endpoint accepts any
// LAN request — which is the real protection anyway: nginx's $is_internal guard
// already refuses anything off the local network, and this path is never
// published through the public proxy. Set a token only if you want a second
// factor on top of that.
$expected = isset($hb['token']) ? (string)$hb['token'] : '';
if ($expected !== '' && !hash_equals($expected, hb_token())) {
    hb_fail(401, 'unauthorized');
}

// Accept either a JSON body or ordinary form fields, so the Windows side can
// use whatever is least painful.
$body = array();
$raw = file_get_contents('php://input');
if ($raw !== '' && $raw[0] === '{') {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) { $body = $decoded; }
}
$field = function ($k, $default = null) use ($body) {
    if (isset($_POST[$k])) { return $_POST[$k]; }
    if (isset($body[$k])) { return $body[$k]; }
    return $default;
};

$name = trim((string)$field('name', ''));
if ($name === '' || !preg_match('/^[A-Za-z0-9._-]{1,64}$/', $name)) {
    hb_fail(400, 'name required (letters, digits, . _ - only)');
}

$record = array(
    'name'        => $name,
    'ok'          => hb_bool($field('ok'), true),
    'status'      => substr(trim((string)$field('status', '')), 0, 120),
    'detail'      => substr(trim((string)$field('detail', '')), 0, 500),
    'received_at' => gmdate('c'),
);
$extra = $field('extra');
if (is_array($extra)) { $record['extra'] = $extra; }
elseif (is_string($extra) && $extra !== '') {
    $d = json_decode($extra, true);
    if (is_array($d)) { $record['extra'] = $d; }
}

$dir = db_data_path('heartbeats');
if (!is_dir($dir)) { @mkdir($dir, 0755, true); }
$path = $dir . '/' . $name . '.json';

// Write-then-rename so a build reading this file never sees a half-written one.
$tmp = $path . '.tmp';
if (@file_put_contents($tmp, json_encode($record)) === false || !@rename($tmp, $path)) {
    @unlink($tmp);
    hb_fail(500, 'could not store heartbeat');
}

echo json_encode(array('ok' => true, 'name' => $name, 'received_at' => $record['received_at']));
