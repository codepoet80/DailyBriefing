<?php
$briefing_path = dirname(__FILE__) . '/../data/briefing.json';

if (!file_exists($briefing_path)) {
    echo '<html><body style="font-family:sans-serif;padding:20px">';
    echo '<h1>No briefing data yet.</h1>';
    echo '<p>Run <code>python3 src/build_briefing.py</code> to generate data.</p>';
    echo '</body></html>';
    exit;
}

$content = file_get_contents($briefing_path);
$briefing = json_decode($content, true);

if (!$briefing) {
    echo '<html><body style="font-family:sans-serif;padding:20px">';
    echo '<h1>Error reading briefing data.</h1>';
    echo '</body></html>';
    exit;
}

function h($str) {
    return htmlspecialchars((string)$str, ENT_QUOTES, 'UTF-8');
}

$greeting        = isset($briefing['greeting'])        ? $briefing['greeting']        : array();
$verse           = isset($briefing['verse'])           ? $briefing['verse']           : array();
$servers         = isset($briefing['servers'])         ? $briefing['servers']         : null;
$weather         = isset($briefing['weather'])         ? $briefing['weather']         : null;
$my_calendar     = isset($briefing['my_calendar'])     ? $briefing['my_calendar']     : array();
$todos           = isset($briefing['todos'])           ? $briefing['todos']           : array();
$family_calendar = isset($briefing['family_calendar']) ? $briefing['family_calendar'] : array();
$tomorrow        = isset($briefing['tomorrow_preview']) ? $briefing['tomorrow_preview'] : array();
$news_important  = isset($briefing['news_important'])  ? $briefing['news_important']  : array();
$news_regular    = isset($briefing['news_regular'])    ? $briefing['news_regular']    : array();
$hackernews      = isset($briefing['hackernews'])      ? $briefing['hackernews']      : array();
$xkcd            = isset($briefing['xkcd'])            ? $briefing['xkcd']            : null;
$generated_at    = isset($briefing['generated_at'])    ? $briefing['generated_at']    : '';
$run_type        = isset($briefing['run_type'])        ? $briefing['run_type']        : '';
$unifi           = isset($briefing['unifi'])           ? $briefing['unifi']           : null;
$imessage        = isset($briefing['imessage'])        ? $briefing['imessage']        : null;
$github          = isset($briefing['github'])          ? $briefing['github']          : array();
$reading         = isset($briefing['reading'])         ? $briefing['reading']         : null;
$health          = isset($briefing['health'])          ? $briefing['health']          : null;

$today_label   = date('l, F j, Y');
$tomorrow_label = date('l, F j', strtotime('+1 day'));
$regular_count = count($news_regular);
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3600">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Briefing &mdash; <?php echo h($today_label); ?></title>
<link rel="stylesheet" type="text/css" href="style.css">
<link rel="icon" type="image/x-icon" href="favicon.ico">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#1b3a5c">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Daily Briefing">
</head>
<body>

<?php if (!empty($greeting)): ?>
<div class="section section-greeting">
    <div class="greeting-text"><?php echo h($greeting['greeting']); ?></div>
    <?php if (!empty($greeting['quote'])): ?>
    <blockquote class="greeting-quote">
        &ldquo;<?php echo h($greeting['quote']); ?>&rdquo;
        <?php if (!empty($greeting['author'])): ?>
        <i>&mdash; <?php echo h($greeting['author']); ?></i>
        <?php endif; ?>
    </blockquote>
    <?php endif; ?>
</div>
<?php endif; ?>

<?php if (!empty($verse)): ?>
<div class="section verse-section">
    <div class="verse-label">Verse of the Day</div>
    <blockquote class="verse-text"><?php echo h($verse['text']); ?></blockquote>
    <div class="verse-ref">&mdash; <?php echo h($verse['reference']); ?>&nbsp;&nbsp;(<?php echo h($verse['translation']); ?>)</div>
</div>
<?php endif; ?>

<?php if ($servers): ?>
<div class="section section-servers <?php echo $servers['all_up'] ? 'servers-up' : 'servers-down'; ?>">
    <?php if ($servers['all_up']): ?>
    <span class="servers-icon">√ </span> All Servers Up
    <?php else: ?>
    <span class="servers-icon">! </span> Server Issues:
    <?php foreach ($servers['sites'] as $site): ?>
        <?php if (!$site['all_up']): ?>
        <span class="servers-site"><?php echo h($site['name']); ?>:</span>
        <?php echo h(implode(', ', $site['down'])); ?>
        <?php endif; ?>
    <?php endforeach; ?>
    <?php endif; ?>
</div>
<?php endif; ?>

<?php if ($unifi && $unifi['total_events'] > 0): ?>
<div class="section section-unifi">
    <div id="unifi-toggle" class="expander" onclick="toggleUnifi()">&#9658; Security &mdash; <?php echo (int)$unifi['total_events']; ?> event<?php echo $unifi['total_events'] !== 1 ? 's' : ''; ?> overnight (<?php echo h($unifi['window_label']); ?>)</div>
    <div id="unifi-detail" style="display:none">
        <?php if (!empty($unifi['smart'])): ?>
        <div class="unifi-summary">
            <?php foreach ($unifi['smart'] as $label => $count): ?>
            <span class="unifi-badge"><?php echo h($count); ?> <?php echo h($label); ?></span>
            <?php endforeach; ?>
            <?php if ($unifi['motion'] > 0): ?>
            <span class="unifi-badge unifi-badge-motion"><?php echo (int)$unifi['motion']; ?> motion</span>
            <?php endif; ?>
        </div>
        <?php endif; ?>
        <?php if (!empty($unifi['cameras'])): ?>
        <table class="unifi-cameras">
            <?php foreach ($unifi['cameras'] as $cam): ?>
            <tr>
                <td class="unifi-cam-name"><?php echo h($cam['name']); ?></td>
                <td class="unifi-cam-detail">
                    <?php foreach ($cam['smart'] as $label => $count): ?>
                    <span class="unifi-badge"><?php echo h($count); ?> <?php echo h($label); ?></span>
                    <?php endforeach; ?>
                    <?php if ($cam['motion'] > 0): ?>
                    <span class="unifi-badge unifi-badge-motion"><?php echo (int)$cam['motion']; ?> motion</span>
                    <?php endif; ?>
                </td>
            </tr>
            <?php endforeach; ?>
        </table>
        <?php endif; ?>
    </div>
</div>
<?php endif; ?>

<?php if ($imessage && $imessage['count'] > 0): ?>
<div class="section section-unifi">
    <div id="imessage-toggle" class="expander" onclick="toggleImessage()">&#9658; Messages &mdash; <?php echo (int)$imessage['count']; ?> message<?php echo $imessage['count'] !== 1 ? 's' : ''; ?> overnight (<?php echo h($imessage['window_label']); ?>)</div>
    <div id="imessage-detail" style="display:none">
        <table class="unifi-cameras">
            <?php foreach ($imessage['messages'] as $msg): ?>
            <tr>
                <td class="unifi-cam-name"><?php echo h($msg['name']); ?></td>
                <td class="unifi-cam-detail">
                    <span class="unifi-badge"><?php echo h($msg['time']); ?></span>
                    <?php echo h($msg['preview']); ?>
                </td>
            </tr>
            <?php endforeach; ?>
        </table>
    </div>
</div>
<?php endif; ?>

<?php if ($weather): ?>
<?php $today_wx = $weather['today']; ?>
<div class="section section-weather">
    <div id="wx-toggle" class="expander" onclick="toggleWeather()">&#9658; Weather &mdash; <?php echo h($today_wx['temp']); ?>, <?php echo h($today_wx['condition']); ?></div>
    <div id="wx-detail" style="display:none">
        <div class="wx-today">
            <span class="wx-temp"><?php echo h($today_wx['temp']); ?></span>
            <span class="wx-condition"><?php echo h($today_wx['condition']); ?></span>
            <span class="wx-meta">Feels like <?php echo h($today_wx['feels_like']); ?> &middot; High <?php echo h($today_wx['high']); ?> / Low <?php echo h($today_wx['low']); ?> &middot; Rain <?php echo h($today_wx['precip_chance']); ?> &middot; Wind <?php echo h($today_wx['wind']); ?> &middot; Humidity <?php echo h($today_wx['humidity']); ?></span>
        </div>
        <?php if (!empty($weather['forecast'])): ?>
        <table class="wx-forecast">
            <?php foreach ($weather['forecast'] as $day): ?>
            <tr>
                <td class="wx-day"><?php echo h($day['day']); ?></td>
                <td class="wx-fc-condition"><?php echo h($day['condition']); ?></td>
                <td class="wx-fc-temp"><?php echo h($day['high']); ?> / <?php echo h($day['low']); ?></td>
                <td class="wx-fc-precip">&#x1F4A7; <?php echo h($day['precip_chance']); ?></td>
            </tr>
            <?php endforeach; ?>
        </table>
        <?php endif; ?>
    </div>
</div>
<?php endif; ?>

<?php if ($run_type !== 'evening'): ?>
<div class="section">
    <h2>Today &mdash; <?php echo h($today_label); ?></h2>
    <?php if (empty($my_calendar)): ?>
    <p class="empty">No events scheduled.</p>
    <?php else: ?>
    <ol class="calendar-list">
        <?php foreach ($my_calendar as $event): ?>
        <?php if (!$event) continue; ?>
        <li>
            <span class="event-time"><?php echo h($event['time']); ?></span>
            <span class="event-title"><?php echo h($event['title']); ?></span>
            <?php if (!empty($event['location'])): ?>
            <span class="event-location"> &mdash; <?php echo h($event['location']); ?></span>
            <?php endif; ?>
            <span class="event-cal">(<?php echo h($event['calendar']); ?>)</span>
        </li>
        <?php endforeach; ?>
    </ol>
    <?php endif; ?>
</div>
<?php endif; ?>

<?php if (!empty($todos)): ?>
<div class="section section-todos">
    <h2>Check Mate</h2>
    <ol class="todo-list">
        <?php foreach ($todos as $todo): ?>
        <li><?php echo h($todo['title']); ?></li>
        <?php endforeach; ?>
    </ol>
</div>
<?php endif; ?>

<?php
function render_sparkline($spark, $baseline_zero = false) {
    if (!is_array($spark) || count($spark) === 0) { return ''; }
    $nums = array();
    foreach ($spark as $v) { if ($v !== null) { $nums[] = (float)$v; } }
    if (!$nums) {
        $maxv = 1.0; $minv = 0.0;
    } else {
        $maxv = max($nums); $minv = min($nums);
        if ($baseline_zero) { $minv = 0.0; }
        if ($maxv === $minv) { $maxv = $minv + 1.0; }
    }
    $out = '<div class="sparkline">';
    foreach ($spark as $v) {
        if ($v === null) {
            $out .= '<div class="bar bar-empty" title="no data"></div>';
        } else {
            $pct = max(2, (int) round((($v - $minv) / ($maxv - $minv)) * 100));
            $title = htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
            $out .= '<div class="bar" style="height:' . $pct . '%" title="' . $title . '"></div>';
        }
    }
    $out .= '</div>';
    return $out;
}

function trend_arrow($trend) {
    if ($trend === 'good') return '<span class="trend trend-good" title="trending in the right direction">&uarr;&darr;</span>';
    if ($trend === 'bad')  return '<span class="trend trend-bad" title="trending the wrong way">!</span>';
    return '<span class="trend trend-flat" title="flat">&ndash;</span>';
}
?>
<?php if ($health): ?>
<?php
    $hw = isset($health['weight'])   ? $health['weight']   : array();
    $ha = isset($health['alcohol'])  ? $health['alcohol']  : array();
    $he = isset($health['exercise']) ? $health['exercise'] : array();
?>
<div class="section section-health">
    <h2>Health</h2>

    <div class="health-row">
        <div class="health-label">
            Weight
            <?php if (empty($hw['today_logged'])): ?><span class="health-missing">log&hellip;</span><?php endif; ?>
        </div>
        <div class="health-value">
            <?php if ($hw['latest'] !== null): ?>
                <?php echo h(number_format((float)$hw['latest'], 1)); ?> <?php echo h($hw['unit']); ?>
                <span class="health-sub">on <?php echo h($hw['latest_date']); ?></span>
            <?php else: ?>
                <span class="health-sub">no logs yet</span>
            <?php endif; ?>
            <?php
                $trend = isset($hw['trend']) ? $hw['trend'] : 'flat';
                echo trend_arrow($trend);
            ?>
        </div>
        <?php echo render_sparkline(isset($hw['sparkline']) ? $hw['sparkline'] : array(), false); ?>
    </div>

    <div class="health-row">
        <div class="health-label">
            Alcohol
            <?php if (empty($ha['today_logged'])): ?><span class="health-sub">(no log today)</span><?php endif; ?>
        </div>
        <div class="health-value">
            <?php echo h((string)$ha['today_drinks']); ?> today &middot;
            <?php echo h((string)$ha['week_drinks']); ?> this week
            <?php if (!empty($ha['weekly_target'])): ?>
                <span class="health-sub">/ <?php echo h((string)$ha['weekly_target']); ?> target</span>
            <?php endif; ?>
            <?php echo trend_arrow(isset($ha['trend']) ? $ha['trend'] : 'flat'); ?>
        </div>
        <?php echo render_sparkline(isset($ha['sparkline']) ? $ha['sparkline'] : array(), true); ?>
    </div>

    <div class="health-row">
        <div class="health-label">
            Exercise
            <?php if (empty($he['today_logged'])): ?><span class="health-sub">(no log today)</span><?php endif; ?>
        </div>
        <div class="health-value">
            <?php echo (int)$he['today_minutes']; ?> min today &middot;
            <?php echo (int)$he['week_minutes']; ?> min this week
            <?php if (!empty($he['weekly_target'])): ?>
                <span class="health-sub">/ <?php echo (int)$he['weekly_target']; ?> target</span>
            <?php endif; ?>
            <?php echo trend_arrow(isset($he['trend']) ? $he['trend'] : 'flat'); ?>
        </div>
        <?php echo render_sparkline(isset($he['sparkline']) ? $he['sparkline'] : array(), true); ?>
    </div>
</div>
<?php endif; ?>

<?php if ($reading && !empty($reading['books'])): ?>
<div class="section section-reading">
    <h2>Currently Reading</h2>
    <ul class="reading-list">
    <?php foreach ($reading['books'] as $book): ?>
        <li<?php if ($book['stagnant']): ?> class="reading-stagnant"<?php endif; ?>>
            <span class="reading-title"><?php echo h($book['title']); ?></span>
            <span class="reading-author">by <?php echo h($book['author']); ?></span>
            <?php if (isset($book['percent']) && $book['percent'] > 0): ?>
            <span class="reading-percent"><?php echo (int)$book['percent']; ?>%</span>
            <?php endif; ?>
            <span class="reading-last-read"><?php echo h($book['last_read_label']); ?></span>
        </li>
    <?php endforeach; ?>
    </ul>
</div>
<?php endif; ?>

<?php if (!empty($github)): ?>
<div class="section section-github">
    <div id="github-toggle" class="expander expander-open" onclick="toggleGithub()">&#9660; GitHub (<?php echo count($github); ?>)</div>
    <div id="github-list">
        <ul class="news-list">
        <?php foreach ($github as $n): ?>
        <li>
            <span class="gh-type"><?php echo h($n['type']); ?></span>
            <a href="<?php echo h($n['url']); ?>" target="_blank"><?php echo h($n['title']); ?></a>
            <span class="source-tag"><?php echo h($n['repo']); ?></span>
            <span class="gh-reason"><?php echo h($n['reason']); ?></span>
        </li>
        <?php endforeach; ?>
        </ul>
    </div>
</div>
<?php endif; ?>

<?php if (!empty($news_important)): ?>
<div class="section">
    <div id="top-stories-toggle" class="expander expander-open" onclick="toggleTopStories()">&#9660; Top Stories (<?php echo count($news_important); ?>)</div>
    <div id="top-stories">
        <?php foreach ($news_important as $story): ?>
        <div class="story-card">
            <div class="story-title"><a href="<?php echo h($story['url']); ?>" target="_blank"><?php echo h($story['title']); ?></a></div>
            <?php if (!empty($story['summary'])): ?>
            <div class="story-summary"><?php echo h($story['summary']); ?></div>
            <?php endif; ?>
            <div class="story-sources">Reported by: <?php echo h(implode(', ', $story['sources'])); ?></div>
        </div>
        <?php endforeach; ?>
    </div>
</div>
<?php endif; ?>

<?php if (!empty($news_regular)): ?>
<div class="section">
    <div id="news-toggle" class="expander" onclick="toggleNews()">&#9658; More News (<?php echo $regular_count; ?> stories)</div>
    <div id="regular-news" style="display:none">
        <ul class="news-list">
            <?php foreach ($news_regular as $story): ?>
            <li>
                <a href="<?php echo h($story['url']); ?>" target="_blank"><?php echo h($story['title']); ?></a>
                <span class="source-tag"><?php echo h($story['source']); ?></span>
            </li>
            <?php endforeach; ?>
        </ul>
    </div>
</div>
<?php endif; ?>

<?php if (!empty($hackernews)): ?>
<div class="section section-hn">
    <div id="hn-toggle" class="expander" onclick="toggleHN()">&#9658; Geek News (<?php echo count($hackernews); ?>)</div>
    <div id="hn-list" style="display:none">
    <ol class="hn-list">
        <?php foreach ($hackernews as $item): ?>
        <li>
            <a href="<?php echo h($item['url']); ?>" target="_blank"><?php echo h($item['title']); ?></a>
            <?php if ($item['source'] === 'HN' && $item['score'] !== null): ?>
            <span class="hn-meta"><?php echo h($item['score']); ?> pts &middot; <a href="https://news.ycombinator.com/item?id=<?php echo h($item['id']); ?>" target="_blank"><?php echo h($item['comments']); ?> comments</a></span>
            <?php endif; ?>
            <span class="source-tag"><?php echo h($item['source']); ?></span>
        </li>
        <?php endforeach; ?>
    </ol>
    </div>
</div>
<?php endif; ?>

<?php if (!empty($family_calendar)): ?>
<div class="section section-family">
    <h2>Family This Week</h2>
    <?php
    $by_day = array();
    foreach ($family_calendar as $event) {
        if (!$event) continue;
        $d = isset($event['date_iso']) ? $event['date_iso'] : 'unknown';
        $by_day[$d][] = $event;
    }
    ksort($by_day);
    foreach ($by_day as $date_iso => $day_events):
        $label = isset($day_events[0]['date_label']) ? $day_events[0]['date_label'] : $date_iso;
        $is_today = ($date_iso === date('Y-m-d'));
    ?>
    <div class="family-day">
        <div class="family-day-label"><?php echo h($label); ?><?php if ($is_today): ?> <span class="today-badge">today</span><?php endif; ?></div>
        <ul class="calendar-list">
            <?php foreach ($day_events as $event): ?>
            <li<?php if (!empty($event['color'])): ?> style="color:<?php echo h($event['color']); ?>"<?php endif; ?>>
                <span class="event-who"><?php echo h($event['calendar']); ?></span>
                <span class="event-time"><?php echo h($event['time']); ?></span>
                <span class="event-title"><?php echo h($event['title']); ?></span>
                <?php if (!empty($event['location'])): ?>
                <span class="event-location"> &mdash; <?php echo h($event['location']); ?></span>
                <?php endif; ?>
            </li>
            <?php endforeach; ?>
        </ul>
    </div>
    <?php endforeach; ?>
</div>
<?php endif; ?>

<?php if (!empty($tomorrow)): ?>
<div class="section section-tomorrow">
    <h2>Tomorrow &mdash; <?php echo h($tomorrow_label); ?></h2>
    <ol class="calendar-list">
        <?php foreach ($tomorrow as $event): ?>
        <?php if (!$event) continue; ?>
        <li>
            <span class="event-time"><?php echo h($event['time']); ?></span>
            <span class="event-title"><?php echo h($event['title']); ?></span>
            <?php if (!empty($event['location'])): ?>
            <span class="event-location"> &mdash; <?php echo h($event['location']); ?></span>
            <?php endif; ?>
        </li>
        <?php endforeach; ?>
    </ol>
</div>
<?php endif; ?>

<?php if ($xkcd && !empty($xkcd['is_new'])): ?>
<div class="section section-xkcd">
    <h2>XKCD #<?php echo h($xkcd['num']); ?>: <?php echo h($xkcd['title']); ?></h2>
    <img src="<?php echo h($xkcd['img_url']); ?>" alt="<?php echo h($xkcd['title']); ?>" title="<?php echo h($xkcd['alt']); ?>" class="xkcd-img">
    <p class="xkcd-alt">&ldquo;<?php echo h($xkcd['alt']); ?>&rdquo;</p>
</div>
<?php endif; ?>

<?php
$chat_cfg     = isset($briefing['chat_agent_ui']) ? $briefing['chat_agent_ui'] : array();
$chat_enabled = false;
$chat_needs_secret = false;
$_cfg_path = dirname(__FILE__) . '/../config/config.json';
if (file_exists($_cfg_path)) {
    $_cfg = json_decode(file_get_contents($_cfg_path), true);
    if (is_array($_cfg) && !empty($_cfg['chat_agent']['enabled'])) {
        $chat_enabled = true;
        $chat_needs_secret = !empty($_cfg['chat_agent']['shared_secret']);
    }
}
?>
<?php if ($chat_enabled): ?>
<div class="section section-chat" id="chat">
    <h2>Chat</h2>
    <div id="chat-log" class="chat-log" aria-live="polite"></div>
    <form id="chat-form" class="chat-form" onsubmit="return chatSubmit(event);">
        <input type="text" id="chat-input" class="chat-input" autocomplete="off"
               placeholder="Ask, save a dialectic, add a todo&hellip;">
        <button type="submit" id="chat-send" class="chat-send">Send</button>
    </form>
    <div id="chat-status" class="chat-status">
        <img id="chat-spinner" src="spinner.gif" alt="" width="16" height="16"
             style="display:none;vertical-align:middle;margin-right:6px">
        <span id="chat-status-text"></span>
    </div>
</div>
<script type="text/javascript">
var CHAT_NEEDS_SECRET = <?php echo $chat_needs_secret ? 'true' : 'false'; ?>;
</script>
<script type="text/javascript" src="chat.js"></script>
<?php endif; ?>

<p class="footer">Generated <?php echo h($generated_at); ?> &middot; <?php echo h($run_type); ?> run</p>

<script type="text/javascript">
var regularCount = <?php echo (int)$regular_count; ?>;
var importantCount = <?php echo (int)count($news_important); ?>;

function toggleNews() {
    var el = document.getElementById('regular-news');
    var btn = document.getElementById('news-toggle');
    if (el.style.display === 'none' || el.style.display === '') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Collapse News';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; More News (' + regularCount + ' stories)';
    }
}

function toggleWeather() {
    var el  = document.getElementById('wx-detail');
    var btn = document.getElementById('wx-toggle');
    var summary = 'Weather \u2014 <?php echo isset($today_wx) ? h($today_wx['temp'] . ', ' . $today_wx['condition']) : ''; ?>';
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Weather';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; ' + summary;
        btn.className = 'expander';
    }
}

function toggleHN() {
    var el = document.getElementById('hn-list');
    var btn = document.getElementById('hn-toggle');
    var count = <?php echo (int)count($hackernews); ?>;
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Geek News (' + count + ')';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; Geek News (' + count + ')';
        btn.className = 'expander';
    }
}

function toggleUnifi() {
    var el  = document.getElementById('unifi-detail');
    var btn = document.getElementById('unifi-toggle');
    var total = <?php echo $unifi ? (int)$unifi['total_events'] : 0; ?>;
    var window_label = '<?php echo $unifi ? h($unifi['window_label']) : ''; ?>';
    var label = 'Security \u2014 ' + total + ' event' + (total !== 1 ? 's' : '') + ' overnight (' + window_label + ')';
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Security';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; ' + label;
        btn.className = 'expander';
    }
}

function toggleImessage() {
    var el  = document.getElementById('imessage-detail');
    var btn = document.getElementById('imessage-toggle');
    var count = <?php echo $imessage ? (int)$imessage['count'] : 0; ?>;
    var window_label = '<?php echo $imessage ? h($imessage['window_label']) : ''; ?>';
    var label = 'Messages \u2014 ' + count + ' message' + (count !== 1 ? 's' : '') + ' overnight (' + window_label + ')';
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Messages';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; ' + label;
        btn.className = 'expander';
    }
}

function toggleGithub() {
    var el  = document.getElementById('github-list');
    var btn = document.getElementById('github-toggle');
    var count = <?php echo (int)count($github); ?>;
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; GitHub (' + count + ')';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; GitHub (' + count + ')';
        btn.className = 'expander';
    }
}

function toggleTopStories() {
    var el = document.getElementById('top-stories');
    var btn = document.getElementById('top-stories-toggle');
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.innerHTML = '&#9660; Top Stories (' + importantCount + ')';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; Top Stories (' + importantCount + ')';
        btn.className = 'expander';
    }
}
</script>
</body>
</html>
