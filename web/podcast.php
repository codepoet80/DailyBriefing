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
audio {
    width: 100%;
    max-width: 560px;
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
    <audio controls autoplay>
        <source src="<?php echo h($url); ?>" type="audio/mpeg">
        Your browser does not support HTML5 audio.
    </audio>
    <br>
    <a class="back" href="javascript:window.close()">Close</a>
</div>
</body>
</html>
