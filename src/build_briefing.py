#!/usr/bin/env python3
import json
import os
import sys
import socket
from datetime import datetime

socket.setdefaulttimeout(20)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_verse import fetch_verse
from fetch_calendars import fetch_calendars
from fetch_todos import fetch_todos
from fetch_podcast import fetch_podcast
from fetch_weather import fetch_weather
from fetch_servers import fetch_servers
from fetch_news import fetch_news
from cluster_news import cluster_stories
from fetch_hackernews import fetch_hackernews
from fetch_xkcd import fetch_xkcd


BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
DATA_DIR = os.path.join(BASE_DIR, 'data')


def load_config():
    with open(os.path.join(CONFIG_DIR, 'config.json')) as f:
        config = json.load(f)
    with open(os.path.join(CONFIG_DIR, 'feeds.json')) as f:
        feeds = json.load(f)
    return config, feeds


def determine_run_type():
    hour = datetime.now().hour
    if hour < 10:
        return 'morning'
    elif hour < 14:
        return 'midday'
    return 'afternoon'


def main():
    config, feeds = load_config()
    run_type = determine_run_type()
    include_tomorrow = (run_type == 'afternoon')

    print('Building briefing (' + run_type + ')...')

    print('  Fetching verse...')
    verse = fetch_verse(config)

    print('  Fetching calendars...')
    my_calendar, family_calendar, tomorrow_preview = fetch_calendars(config, include_tomorrow)
    # Filter out None events from parse failures
    my_calendar = [e for e in my_calendar if e]
    family_calendar = [e for e in family_calendar if e]
    tomorrow_preview = [e for e in tomorrow_preview if e]

    print('  Fetching server status...')
    servers = fetch_servers(config)

    print('  Fetching weather...')
    weather = fetch_weather(config)

    print('  Fetching podcast...')
    podcast = fetch_podcast(config)

    print('  Fetching todos...')
    todos = fetch_todos(config)

    print('  Fetching news feeds (' + str(len(feeds)) + ' configured)...')
    raw_stories = fetch_news(feeds)
    print('  Clustering ' + str(len(raw_stories)) + ' raw stories...')
    news_cfg = config.get('news', {})
    news_important, news_regular = cluster_stories(
        raw_stories,
        threshold=news_cfg.get('similarity_threshold', 0.65),
        importance_threshold=news_cfg.get('importance_threshold', 2),
    )
    news_important = news_important[:news_cfg.get('max_important', 8)]
    news_regular = news_regular[:news_cfg.get('max_regular', 20)]

    print('  Fetching HackerNews...')
    hackernews = fetch_hackernews(config.get('hackernews', {}).get('top_count', 25))

    print('  Fetching XKCD...')
    xkcd = fetch_xkcd(DATA_DIR)

    briefing = {
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'run_type': run_type,
        'verse': verse,
        'servers': servers,
        'weather': weather,
        'podcast': podcast,
        'my_calendar': my_calendar,
        'todos': todos,
        'family_calendar': family_calendar,
        'tomorrow_preview': tomorrow_preview if include_tomorrow else [],
        'news_important': news_important,
        'news_regular': news_regular,
        'hackernews': hackernews,
        'xkcd': xkcd,
    }

    output_path = os.path.join(DATA_DIR, 'briefing.json')
    with open(output_path, 'w') as f:
        json.dump(briefing, f, indent=2, default=str)

    print('Done. Wrote ' + output_path)
    print('  ' + str(len(news_important)) + ' important stories, ' +
          str(len(news_regular)) + ' regular')
    print('  ' + str(len(my_calendar)) + ' my calendar, ' +
          str(len(family_calendar)) + ' family items')
    print('  ' + str(len(hackernews)) + ' HN stories')
    if xkcd:
        label = 'NEW' if xkcd['is_new'] else 'not new'
        print('  XKCD #' + str(xkcd['num']) + ': ' + xkcd['title'] + ' (' + label + ')')


if __name__ == '__main__':
    main()
