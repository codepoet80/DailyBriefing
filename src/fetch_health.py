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
  "joy":      {latest, latest_date, today_logged, sparkline, trend,
               week_avg, scale_max},
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


def _week_dates():
    """Dates for the current calendar week, Sunday through Saturday."""
    today = date.today()
    # weekday(): Mon=0 .. Sun=6; days since the most recent Sunday.
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    return [start + timedelta(days=i) for i in range(7)]


def _weight_slope_trend(sparkline, goal_direction='down'):
    """Compare recent 3 weight logs to the prior 3. Skip if not enough data."""
    vals = [v for v in sparkline if v is not None]
    if len(vals) < 4:
        return 'flat'
    recent = vals[-3:]
    prior  = vals[-6:-3] if len(vals) >= 6 else vals[:-3]
    if not prior:
        return 'flat'
    r = sum(recent) / len(recent)
    p = sum(prior)  / len(prior)
    diff = r - p
    threshold = max(abs(p) * 0.005, 0.3)  # 0.5% or 0.3 lb, whichever bigger
    if abs(diff) < threshold:
        return 'flat'
    if goal_direction == 'down':
        return 'good' if diff < 0 else 'bad'
    return 'good' if diff > 0 else 'bad'


def _target_status(value, target, under_is_good=True,
                   good_ratio=0.6, bad_ratio=1.0):
    """Target-based status. For 'under_is_good' (e.g. alcohol):
       good when value <= target*good_ratio, bad when value > target.
       For 'over_is_good' (e.g. exercise):
       good when value >= target, bad when value < target*good_ratio."""
    if target is None or target <= 0:
        return 'flat'
    ratio = float(value) / float(target)
    if under_is_good:
        if ratio > bad_ratio:  return 'bad'
        if ratio <= good_ratio: return 'good'
        return 'flat'
    if ratio >= 1.0:        return 'good'
    if ratio < good_ratio:  return 'bad'
    return 'flat'


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
        'trend': _weight_slope_trend(spark, cfg.get('weight', {}).get('goal_direction', 'down')),
        'unit': cfg.get('weight', {}).get('unit', 'lbs'),
        'target': cfg.get('weight', {}).get('target'),
        'chart_pad': cfg.get('weight', {}).get('chart_pad', 10),
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
    week_dates = [d.isoformat() for d in _week_dates()]
    week_drinks = round(sum(by_day.get(d, 0) for d in week_dates), 2)

    raw_today = [r.get('raw_input', '') for r in rows if r.get('date') == today_iso]

    target = cfg.get('alcohol', {}).get('weekly_target_drinks')
    return {
        'today_drinks':   round(today_drinks, 2),
        'week_drinks':    week_drinks,
        'today_logged':   today_iso in by_day,
        'sparkline':      spark,
        'trend':          _target_status(week_drinks, target, under_is_good=True),
        'weekly_target':  target,
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
    week_dates = [d.isoformat() for d in _week_dates()]
    week_minutes = int(sum(by_day.get(d, 0) for d in week_dates))

    last_kind = ''
    if rows:
        last = max(rows, key=lambda r: (r.get('date', ''), r.get('ts', '')))
        last_kind = last.get('kind', '') or last.get('intensity', '')

    target = cfg.get('exercise', {}).get('weekly_target_minutes')
    return {
        'today_minutes': today_minutes,
        'week_minutes':  week_minutes,
        'today_logged':  today_iso in by_day,
        'sparkline':     spark,
        'trend':         _target_status(week_minutes, target, under_is_good=False),
        'weekly_target': target,
        'last_kind':     last_kind,
    }


def _joy_summary(cfg, days):
    """Joy is a subjective daily rating (1..scale_max, higher is better).
    One value per day (latest log wins, like weight). Trend is slope-based
    with up-is-good, so a rising mood reads as 'good'."""
    rows = _read_jsonl(os.path.join(HEALTH_DIR, 'joy.jsonl'))
    by_day = {}
    for r in rows:
        d = r.get('date')
        if not d:
            continue
        # Keep latest log per day (overwrite on duplicates)
        by_day[d] = r.get('rating')

    today_iso = date.today().isoformat()
    spark = [by_day.get(d.isoformat()) for d in _day_range(days)]

    latest = None
    latest_date = None
    if rows:
        latest_row = max(rows, key=lambda r: (r.get('date', ''), r.get('ts', '')))
        latest = latest_row.get('rating')
        latest_date = latest_row.get('date')

    week_vals = [by_day[d.isoformat()] for d in _week_dates()
                 if by_day.get(d.isoformat()) is not None]
    week_avg = round(sum(week_vals) / len(week_vals), 1) if week_vals else None

    return {
        'latest': latest,
        'latest_date': latest_date,
        'today_logged': today_iso in by_day,
        'sparkline': spark,
        'trend': _weight_slope_trend(spark, goal_direction='up'),
        'week_avg': week_avg,
        'scale_max': int(cfg.get('joy', {}).get('scale_max', 5)),
    }


def fetch_health(full_config, compact=False):
    cfg = full_config.get('health', {}) or {}
    days = int(cfg.get('chart_days', 30))
    summary = {
        'weight':   _weight_summary(cfg, days),
        'alcohol':  _alcohol_summary(cfg, days),
        'exercise': _exercise_summary(cfg, days),
        'joy':      _joy_summary(cfg, days),
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
