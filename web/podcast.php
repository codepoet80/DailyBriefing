<?php
$url   = isset($_GET['url'])   ? $_GET['url']   : '';
$title = isset($_GET['title']) ? $_GET['title'] : 'Podcast';
$name  = isset($_GET['name'])  ? $_GET['name']  : '';

if (empty($url)) {
    echo '<html><body>No audio URL provided.</body></html>';
    exit;
}

function h($str) {
    return htmlspecialchars((string)$str, ENT_QUOTES, 'UTF-8');
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo h($name); ?></title>
<style type="text/css">
* { margin: 0; padding: 0; }
body {
    background: #1a1a1a;
    color: #ddd;
    font-family: Arial, Helvetica, sans-serif;
    display: table;
    width: 100%;
    height: 100%;
}
.player {
    display: table-cell;
    vertical-align: middle;
    text-align: center;
    padding: 40px 24px;
}
.show-name {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #888;
    margin-bottom: 14px;
}
.episode-title {
    font-size: 18px;
    color: #eee;
    line-height: 1.4;
    margin-bottom: 30px;
    max-width: 600px;
    margin-left: auto;
    margin-right: auto;
}
.player-controls {
    margin-bottom: 20px;
}
.play-btn {
    display: inline-block;
    background: #2e7d6e;
    color: #fff;
    font-size: 20px;
    font-weight: bold;
    padding: 12px 32px;
    cursor: pointer;
    border: none;
    font-family: Arial, Helvetica, sans-serif;
}
.play-btn:hover { background: #235f53; }
.progress-bar-wrap {
    width: 100%;
    max-width: 560px;
    height: 6px;
    background: #333;
    margin: 16px auto 8px auto;
    cursor: pointer;
}
.progress-bar-fill {
    height: 6px;
    background: #2e7d6e;
    width: 0%;
}
.time-display {
    font-size: 12px;
    color: #666;
    font-family: Arial, Helvetica, sans-serif;
}
.back {
    display: inline-block;
    margin-top: 28px;
    font-size: 13px;
    color: #666;
    text-decoration: none;
}
.back:hover { color: #aaa; }
</style>
</head>
<body>
<div class="player">
    <?php if ($name): ?>
    <div class="show-name"><?php echo h($name); ?></div>
    <?php endif; ?>
    <div class="episode-title"><?php echo h($title); ?></div>
    <div class="player-controls">
        <button class="play-btn" id="playbtn" onclick="togglePlay()">&#9654; Play</button>
    </div>
    <div class="progress-bar-wrap" onclick="seek(event)" id="progress-wrap">
        <div class="progress-bar-fill" id="progress-fill"></div>
    </div>
    <div class="time-display" id="time-display">0:00 / --:--</div>
    <br>
    <a class="back" href="javascript:window.close()">Close</a>
</div>
<script type="text/javascript">
var audio = new Audio('<?php echo h($url); ?>');
var playing = false;

audio.addEventListener('timeupdate', function() {
    if (audio.duration) {
        var pct = (audio.currentTime / audio.duration) * 100;
        document.getElementById('progress-fill').style.width = pct + '%';
        document.getElementById('time-display').innerHTML = fmt(audio.currentTime) + ' / ' + fmt(audio.duration);
    }
});

audio.addEventListener('ended', function() {
    playing = false;
    document.getElementById('playbtn').innerHTML = '&#9654; Play';
});

function togglePlay() {
    if (playing) {
        audio.pause();
        playing = false;
        document.getElementById('playbtn').innerHTML = '&#9654; Play';
    } else {
        audio.play();
        playing = true;
        document.getElementById('playbtn').innerHTML = '&#9646;&#9646; Pause';
    }
}

function seek(e) {
    if (!audio.duration) return;
    var wrap = document.getElementById('progress-wrap');
    var rect = wrap.getBoundingClientRect();
    var pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
}

function fmt(s) {
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
}
</script>
</body>
</html>
