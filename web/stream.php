<?php
$url = isset($_GET['url']) ? $_GET['url'] : '';

if (empty($url) || !preg_match('/^https?:\/\//', $url)) {
    http_response_code(400);
    echo 'Invalid URL';
    exit;
}

// Stream the audio through our server with explicit headers.
// This avoids SSL/CORS issues with old WebKit and ensures correct Content-Type.
$ch = curl_init($url);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
curl_setopt($ch, CURLOPT_USERAGENT, 'DailyBriefing/1.0');
curl_setopt($ch, CURLOPT_TIMEOUT, 0);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
curl_setopt($ch, CURLOPT_HEADERFUNCTION, function($ch, $header) {
    // Forward content-length so the browser can show duration/progress
    if (stripos($header, 'Content-Length:') === 0) {
        header(trim($header));
    }
    return strlen($header);
});

header('Content-Type: audio/mpeg');
header('Content-Disposition: inline; filename="podcast.mp3"');
header('Accept-Ranges: none');
header('Cache-Control: no-cache');

curl_exec($ch);
curl_close($ch);
