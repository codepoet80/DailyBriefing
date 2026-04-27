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

$verse           = isset($briefing['verse'])           ? $briefing['verse']           : array();
$servers         = isset($briefing['servers'])         ? $briefing['servers']         : null;
$weather         = isset($briefing['weather'])         ? $briefing['weather']         : null;
$podcast         = isset($briefing['podcast'])         ? $briefing['podcast']         : null;
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

$today_label   = date('l, F j, Y');
$tomorrow_label = date('l, F j', strtotime('+1 day'));
$regular_count = count($news_regular);
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
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
    <span class="servers-icon">&#10003;</span> All Servers Up
    <?php else: ?>
    <span class="servers-icon">&#9888;</span> Server Issues:
    <?php foreach ($servers['sites'] as $site): ?>
        <?php if (!$site['all_up']): ?>
        <span class="servers-site"><?php echo h($site['name']); ?>:</span>
        <?php echo h(implode(', ', $site['down'])); ?>
        <?php endif; ?>
    <?php endforeach; ?>
    <?php endif; ?>
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
    <div id="hn-toggle" class="expander expander-open" onclick="toggleHN()">&#9660; Hacker News (<?php echo count($hackernews); ?>)</div>
    <div id="hn-list">
    <ol class="hn-list">
        <?php foreach ($hackernews as $item): ?>
        <li>
            <a href="<?php echo h($item['url']); ?>" target="_blank"><?php echo h($item['title']); ?></a>
            <span class="hn-meta"><?php echo h($item['score']); ?> pts &middot; <?php echo h($item['comments']); ?> comments</span>
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


<?php if ($podcast): ?>
<div class="section section-podcast">
    <a class="podcast-btn" href="podcast.php?url=<?php echo urlencode($podcast['audio_url']); ?>&amp;title=<?php echo urlencode($podcast['title']); ?>&amp;name=<?php echo urlencode($podcast['name']); ?>" target="_blank">&#9654; Play <?php echo h($podcast['name']); ?></a>
    <span class="podcast-title"><?php echo h($podcast['title']); ?></span>
</div>
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
    var summary = 'Weather \u2014 <?php echo h($today_wx['temp'] . ', ' . $today_wx['condition']); ?>';
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
        btn.innerHTML = '&#9660; Hacker News (' + count + ')';
        btn.className = 'expander expander-open';
    } else {
        el.style.display = 'none';
        btn.innerHTML = '&#9658; Hacker News (' + count + ')';
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
