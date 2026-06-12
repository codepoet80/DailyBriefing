#!/usr/bin/env python3
"""Read data/health/{weight,alcohol,exercise}.jsonl and summarise for the
briefing renderer and proactive notifications.

Returns a dict shaped:
{
  "weight":   {latest, latest_date, today_logged, sparkline, trend, unit},
  "alcohol":  {today_drinks, week_drinks, today_logged, sparkline, trend,
               weekly_target, raw_today},
  "exercise": {today_minutes, week_minutes, today_logged, sparkline, trend,
               weekly_target, last_kind},
}

Sparklines are lists of length `chart_days` (default 30), one entry per day
ending today. Entries are numbers (the day's value) or null (no log that day).
"""
import json
import os
from datetime import date, datetime, timedelta

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
HEALTH_DIR = os.path.join(BASE_DIR, 'data', 'health')


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _day_range(days):
    today = date.today()
    return [today - timedelta(days=days - 1 - i) for i in range(days)]


def _trend(sparkline, direction='down'):
    """Compare last 7 days' avg vs prior 7 days' avg. Direction is the "good"
    direction so we can return 'good'/'bad'/'flat' in addition to up/down."""
    vals = [(i, v) for i, v in enumerate(sparkline) if v is not None]
    if len(vals) < 2:
        return 'flat'
    n = len(sparkline)
    recent = [v for i, v in vals if i >= n - 7]
    prior  = [v for i, v in vals if n - 14 <= i < n - 7]
    if not recent or not prior:
        return 'flat'
    r = sum(recent) / len(recent)
    p = sum(prior)  / len(prior)
    diff = r - p
    threshold = max(abs(p) * 0.02, 0.5)
    if abs(diff) < threshold:
        return 'flat'
    if direction == 'down':
        return 'good' if diff < 0 else 'bad'
    return 'good' if diff > 0 else 'bad'


def _weight_summary(cfg, days):
    rows = _read_jsonl(os.path.join(HEALTH_DIR, 'weight.jsonl'))
    by_day = {}
    for r in rows:
        d = r.get('date')
        if not d:
            continue
        # Keep latest log per day (overwrite on duplicates)
        by_day[d] = r.get('pounds')

    today_iso = date.today().isoformat()
    spark = [by_day.get(d.isoformat()) for d in _day_range(days)]

    latest = None
    latest_date = None
    if rows:
        latest_row = max(rows, key=lambda r: (r.get('date', ''), r.get('ts', '')))
        latest = latest_row.get('pounds')
        latest_date = latest_row.get('date')

    return {
        'latest': latest,
        'latest_date': latest_date,
        'today_logged': today_iso in by_day,
        'sparkline': spark,
        'trend': _trend(spark, cfg.get('weight', {}).get('goal_direction', 'down')),
        'unit': cfg.get('weight', {}).get('unit', 'lbs'),
    }


def _sum_by_day(rows, value_key):
    out = {}
    for r in rows:
        d = r.get('date')
        if not d:
            continue
        try:
            v = float(r.get(value_key, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        out[d] = out.get(d, 0) + v
    return out


def _alcohol_summary(cfg, days):
    rows = _read_jsonl(os.path.join(HEALTH_DIR, 'alcohol.jsonl'))
    by_day = _sum_by_day(rows, 'drinks')
    today_iso = date.today().isoformat()
    spark = [by_day.get(d.isoformat(), 0) if by_day else None for d in _day_range(days)]
    if not by_day:
        spark = [None] * days

    today_drinks = by_day.get(today_iso, 0)
    week_dates = [d.isoformat() for d in _day_range(7)]
    week_drinks = round(sum(by_day.get(d, 0) for d in week_dates), 2)

    raw_today = [r.get('raw_input', '') for r in rows if r.get('date') == today_iso]

    return {
        'today_drinks':   round(today_drinks, 2),
        'week_drinks':    week_drinks,
        'today_logged':   today_iso in by_day,
        'sparkline':      spark,
        'trend':          _trend(spark, direction='down'),
        'weekly_target':  cfg.get('alcohol', {}).get('weekly_target_drinks'),
        'raw_today':      raw_today,
    }


def _exercise_summary(cfg, days):
    rows = _read_jsonl(os.path.join(HEALTH_DIR, 'exercise.jsonl'))
    by_day = _sum_by_day(rows, 'minutes')
    today_iso = date.today().isoformat()
    spark = [by_day.get(d.isoformat(), 0) if by_day else None for d in _day_range(days)]
    if not by_day:
        spark = [None] * days

    today_minutes = int(by_day.get(today_iso, 0))
    week_dates = [d.isoformat() for d in _day_range(7)]
    week_minutes = int(sum(by_day.get(d, 0) for d in week_dates))

    last_kind = ''
    if rows:
        last = max(rows, key=lambda r: (r.get('date', ''), r.get('ts', '')))
        last_kind = last.get('kind', '') or last.get('intensity', '')

    return {
        'today_minutes': today_minutes,
        'week_minutes':  week_minutes,
        'today_logged':  today_iso in by_day,
        'sparkline':     spark,
        'trend':         _trend(spark, direction='up'),
        'weekly_target': cfg.get('exercise', {}).get('weekly_target_minutes'),
        'last_kind':     last_kind,
    }


def fetch_health(full_config, compact=False):
    cfg = full_config.get('health', {}) or {}
    days = int(cfg.get('chart_days', 30))
    summary = {
        'weight':   _weight_summary(cfg, days),
        'alcohol':  _alcohol_summary(cfg, days),
        'exercise': _exercise_summary(cfg, days),
    }
    if compact:
        # drop the full sparkline for chat-tool output, keep totals/trends
        for k in summary:
            summary[k].pop('sparkline', None)
    return summary


if __name__ == '__main__':
    import sys
    cfg_path = os.path.join(BASE_DIR, 'config', 'config.json')
    with open(cfg_path) as f:
        cfg = json.load(f)
    json.dump(fetch_health(cfg), sys.stdout, indent=2)
    print()
