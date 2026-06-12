#!/usr/bin/env python3
"""Chat handler invoked once per HTTP request from web/chat.php.

Reads a JSON payload from stdin:
    {
      "session_id": "...",       # optional; new session created if missing/invalid
      "user_message": "...",
      "shared_secret": "..."     # if chat_agent.shared_secret is set
    }

Runs the Anthropic tool-use loop against the live MCP server and writes a
JSON result to stdout:
    {
      "ok": true,
      "session_id": "...",
      "reply": "...",
      "tool_events": [{"name": "dialectic_save", "ok": true, "summary": "..."}],
      "active_dialectic_id": "..." | null
    }
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.mcp_bridge import call_mcp_tool, mcp_session, to_anthropic_tools
from agent import sessions

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.json')
BRIEFING_PATH = os.path.join(BASE_DIR, 'data', 'briefing.json')
MCP_SERVER_PATH = os.path.join(BASE_DIR, 'src', 'mcp_server.py')

DEFAULT_MODEL = 'claude-sonnet-4-6'
MAX_REPLY_TOKENS = 1024

_SAVE_ID_RE = re.compile(r'id:\s*([0-9a-f-]{36})', re.IGNORECASE)


def _emit(payload):
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _fail(message, session_id=None):
    _emit({'ok': False, 'error': message, 'session_id': session_id})
    sys.exit(0)


def _load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _load_briefing():
    if not os.path.exists(BRIEFING_PATH):
        return None
    try:
        with open(BRIEFING_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _build_stable_system_text(config):
    """The half that doesn't change between briefing cron runs — safe to cache.

    Must exceed the Anthropic prompt-cache minimum (1024 tokens on Sonnet) for
    the cache breakpoint to register, so this section is intentionally verbose
    with reusable context, the full briefing-data schema, and detailed dialectic
    protocol. Add new stable content here rather than to the volatile half.
    """
    name = config.get('greeting', {}).get('name', 'Jon')
    extra = config.get('chat_agent', {}).get('system_prompt_extra', '') or ''
    dialectic_stance = config.get('dialectic', {}).get('system_prompt', '') or ''

    sections = [
        f"You are {name}'s briefing assistant, reached via a chat box on the read-only "
        "Daily Briefing webpage that aggregates calendars, todos, news, weather, server "
        "status, security events, and more for a personal start-of-day overview. The "
        "user is often on a legacy device (e.g. a 2011 webOS TouchPad), so keep replies "
        "short, plain-text-friendly, and avoid markdown tables, deeply nested lists, or "
        "long preambles. Speak directly. When the user asks for facts about today's "
        "briefing, answer from the data section provided further down — do not call "
        "tools just to retrieve information already attached.",

        "Tool use guidelines:\n"
        "- Only call tools when the user is asking you to *do* something: add a todo, "
        "create a calendar event, send a notification, send a message, save or resume "
        "or close a dialectic, refresh the briefing data.\n"
        "- For factual questions about today's briefing, read the attached JSON.\n"
        "- Prefer one tool call per request when possible. If a call fails, summarize "
        "the failure and ask before retrying with different arguments.\n"
        "- After any write action, briefly confirm what you did in plain language; "
        "don't paste raw JSON results back at the user.",

        "Briefing JSON schema reference (top-level keys that may be present):\n"
        "- greeting: {greeting, quote, author}\n"
        "- verse: verse of the day from Bible Gateway / ESV\n"
        "- weather: {today: {temp, condition, ...}, forecast: [...]}\n"
        "- servers: {all_up, sites: [{name, all_up, services: [...]}, ...]}\n"
        "- my_calendar: events for today on Jon's own calendars; each item has\n"
        "    title, calendar, date_iso, sort_key (HH:MM string), start (display "
        "time), end, all_day, location, notes\n"
        "- family_calendar: 7-day view across family members; each item has\n"
        "    title, person, color, date_iso, sort_key, start, end, all_day\n"
        "- tomorrow_preview: same shape as my_calendar but for tomorrow (only on "
        "afternoon/evening runs)\n"
        "- todos: [{title, done, n}, ...] from checkmate\n"
        "- news_important: top stories elevated by cross-source clustering\n"
        "- news_regular: remaining stories\n"
        "- hackernews: HN + Slashdot interleaved (geek news section)\n"
        "- github: GitHub notifications {title, repo, reason, type, updated_at}\n"
        "- reading: {stagnant: [{title, days_since}, ...], all: [...]}\n"
        "- unifi: overnight security event summary {total_events, smart, motion, "
        "cameras: [...], window_label}\n"
        "- imessage: overnight message summary {count, threads: [...], window_label}\n"
        "- xkcd: today's comic if new\n"
        "- generated_at, run_type: when the data was produced and which cron run "
        "(morning, midday, afternoon, evening)\n"
        "If a field is missing or empty, just say so plainly. Do not invent data.",

        "Dialectics protocol:\n"
        "- A 'dialectic' is an exploratory conversation Jon and the assistant save "
        "for later resumption. It is the only kind of conversation that persists "
        "across web-chat sessions (the chat box itself only remembers a rolling "
        "window of recent turns).\n"
        "- When Jon marks a discussion as a dialectic — using phrases like 'mark "
        "this', 'save this as a dialectic', 'this is a dialectic', 'remember this "
        "discussion', or labeling the topic — call dialectic_save with a concise "
        "topic and the full exchange so far as turns.\n"
        "- Once a dialectic is active in this session, after every assistant reply, "
        "call dialectic_append with the new user turn and your new reply, before "
        "finishing the turn. Do not wait for Jon to remind you.\n"
        "- When Jon signs off ('thanks for the chat', 'good talk', 'I'm done with "
        "this', 'let's stop here') or clearly switches to an unrelated briefing "
        "domain (calendars, todos, messages, news, weather, servers), call "
        "dialectic_close with the active dialectic id. Do NOT create a new "
        "dialectic just to close it.\n"
        "- When Jon asks to resume, reopen, or continue a past dialectic, call "
        "dialectic_resume with that dialectic's id. From that point treat the "
        "session as active and append after every reply.\n"
        "- To list or browse past dialectics without resuming, use dialectic_list "
        "and dialectic_get.\n"
        "- The id of the currently active dialectic (if any) is in the volatile "
        "section below. Always reuse that id for append and close — never invent "
        "one.",

        "Health logging protocol:\n"
        "- Jon tracks weight (lbs), alcohol (US standard drinks), and exercise "
        "(minutes + intensity). Three MCP tools: log_weight, log_alcohol, "
        "log_exercise. A fourth, get_health_summary, returns fresh totals/trend.\n"
        "- When Jon mentions health information conversationally — 'I'm 178 this "
        "morning', 'we shared a bottle of wine', 'just ran 3 miles' — translate "
        "and log it WITHOUT asking confirmation unless the input is genuinely "
        "ambiguous. Briefly confirm afterward in plain language.\n"
        "- Alcohol → US standard drinks (1 drink = 14g pure ethanol):\n"
        "    * 5oz wine (12% ABV) = 1 drink; standard 750ml wine bottle = 5 drinks\n"
        "    * 12oz beer (5% ABV) = 1 drink; tall boy / 16oz = 1.3 drinks; "
        "double IPA at ~8% = 1.6 drinks\n"
        "    * 1.5oz spirit (40% ABV) = 1 drink; double pour = 2 drinks; "
        "old fashioned ≈ 2 drinks; martini ≈ 2 drinks; margarita ≈ 1.5 drinks\n"
        "    * shared bottle of wine between two people = 2.5 drinks each\n"
        "    * 'a couple beers' = 2 drinks; 'a few' = 3; 'a nightcap' = 1\n"
        "  Always include the user's original wording as raw_input. If you list "
        "items, pass them via the items array.\n"
        "- Exercise → minutes + intensity (light / moderate / vigorous):\n"
        "    * walking the dog, easy yoga, stretching → light\n"
        "    * brisk walk, bike commute, gentle swim, weights → moderate\n"
        "    * running, HIIT, hot yoga, sports games → vigorous\n"
        "    * rough duration estimates if not given: 'ran 3 miles' ≈ 30 min "
        "vigorous, 'walked dog' ≈ 20 min light, 'yoga class' ≈ 60 min moderate, "
        "'lifted' ≈ 45 min moderate. Ask if truly unclear.\n"
        "- Weight: just a number in pounds. If Jon gives kg, multiply by 2.20462.\n"
        "- If Jon asks 'how am I doing on X?' or 'what's my trend?' call "
        "get_health_summary for fresh numbers — the briefing JSON snapshot below "
        "may be stale if he logged something this session.",

        "Reply style:\n"
        "- Match the length of the question. One-line questions get one-line "
        "answers.\n"
        "- For lists of events or todos, use a short plain-text bulleted format "
        "with times when relevant.\n"
        "- Never echo back large JSON payloads to the user.\n"
        "- When you call a tool, the chat UI surfaces a small status line "
        "automatically — don't also describe the call in your prose.",
    ]
    if dialectic_stance:
        sections.append(
            'Default dialectic stance (apply once a dialectic is active unless a '
            f'stored stance overrides it): {dialectic_stance}'
        )
    if extra:
        sections.append(extra)
    return '\n\n'.join(sections)


def _build_volatile_system_text(briefing, active_dialectic_id):
    """The per-request half: briefing data and active dialectic state. Not cached."""
    sections = []
    if active_dialectic_id:
        sections.append(
            f'Active dialectic id for this session: {active_dialectic_id}. '
            'Use this exact id for dialectic_append and dialectic_close.'
        )
    else:
        sections.append('No dialectic is currently active in this session.')
    if briefing:
        sections.append(
            "Today's briefing data (JSON):\n"
            + json.dumps(briefing, indent=2)
        )
    return '\n\n'.join(sections)


def _build_system_blocks(config, briefing, active_dialectic_id=None):
    """Two-block system prompt: stable text (cached) then volatile text (uncached)."""
    return [
        {
            'type': 'text',
            'text': _build_stable_system_text(config),
            'cache_control': {'type': 'ephemeral'},
        },
        {
            'type': 'text',
            'text': _build_volatile_system_text(briefing, active_dialectic_id),
        },
    ]


def _turns_to_messages(turns):
    """Convert stored turns to Anthropic message list. Drops tool-use detail."""
    out = []
    for t in turns:
        role = t.get('role')
        content = t.get('content', '')
        if role not in ('user', 'assistant') or not content:
            continue
        out.append({'role': role, 'content': content})
    return out


def _extract_text(content_blocks):
    parts = []
    for block in content_blocks:
        if getattr(block, 'type', None) == 'text':
            parts.append(block.text)
    return '\n'.join(p for p in parts if p).strip()


def _summarize_tool_result(text, max_len=140):
    text = (text or '').strip().splitlines()
    first = text[0] if text else ''
    if len(first) > max_len:
        first = first[:max_len - 1] + '…'
    return first


def _track_active_dialectic(state, tool_name, tool_input, result_text):
    if tool_name == 'dialectic_save':
        m = _SAVE_ID_RE.search(result_text or '')
        if m:
            state['active_dialectic_id'] = m.group(1)
    elif tool_name == 'dialectic_resume':
        new_id = (tool_input or {}).get('id')
        if new_id:
            state['active_dialectic_id'] = new_id
    elif tool_name == 'dialectic_close':
        closed_id = (tool_input or {}).get('id')
        if state.get('active_dialectic_id') == closed_id:
            state['active_dialectic_id'] = None


async def _run_turn(config, state, user_message):
    import anthropic

    chat_cfg = config.get('chat_agent', {})
    agent_cfg = config.get('agent', {})

    api_key = agent_cfg.get('anthropic_api_key', '')
    if not api_key:
        return {'ok': False, 'error': 'agent.anthropic_api_key not configured'}

    model = chat_cfg.get('model') or DEFAULT_MODEL
    allowed_tools = chat_cfg.get('allowed_tools') or []
    max_iter = int(chat_cfg.get('max_tool_iterations') or 8)

    briefing = _load_briefing()
    system_blocks = _build_system_blocks(
        config, briefing, active_dialectic_id=state.get('active_dialectic_id')
    )

    sessions.append_turn(state, 'user', user_message)
    sessions.trim(state, int(chat_cfg.get('max_turns_in_context') or 20))
    messages = _turns_to_messages(state['turns'])

    client = anthropic.AsyncAnthropic(api_key=api_key)
    tool_events = []
    reply_text = ''

    venv_python = sys.executable
    async with mcp_session(venv_python, [MCP_SERVER_PATH]) as session:
        tools_list = await session.list_tools()
        tools = to_anthropic_tools(tools_list.tools, allowed_tools)

        for _ in range(max_iter):
            resp = await client.messages.create(
                model=model,
                max_tokens=MAX_REPLY_TOKENS,
                system=system_blocks,
                tools=tools,
                messages=messages,
            )

            assistant_blocks = []
            tool_uses = []
            iter_text = ''
            for block in resp.content:
                btype = getattr(block, 'type', None)
                if btype == 'text':
                    assistant_blocks.append({'type': 'text', 'text': block.text})
                    if block.text:
                        iter_text = (iter_text + '\n' + block.text).strip()
                elif btype == 'tool_use':
                    assistant_blocks.append({
                        'type': 'tool_use',
                        'id': block.id,
                        'name': block.name,
                        'input': block.input,
                    })
                    tool_uses.append(block)

            if iter_text:
                reply_text = iter_text

            messages.append({'role': 'assistant', 'content': assistant_blocks})

            if resp.stop_reason != 'tool_use' or not tool_uses:
                break

            tool_results = []
            for tu in tool_uses:
                result_text, is_error = await call_mcp_tool(session, tu.name, tu.input)
                tool_events.append({
                    'name': tu.name,
                    'ok': not is_error,
                    'summary': _summarize_tool_result(result_text),
                })
                _track_active_dialectic(state, tu.name, tu.input, result_text)
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.id,
                    'content': result_text,
                    'is_error': is_error,
                })
            messages.append({'role': 'user', 'content': tool_results})
        else:
            reply_text = (reply_text or
                          '(stopped after reaching tool iteration limit)')

    if not reply_text:
        reply_text = '(no reply)'

    sessions.append_turn(state, 'assistant', reply_text)
    sessions.trim(state, int(chat_cfg.get('max_turns_in_context') or 20))

    return {
        'ok': True,
        'reply': reply_text,
        'tool_events': tool_events,
        'active_dialectic_id': state.get('active_dialectic_id'),
    }


async def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(f'invalid JSON input: {e}')

    user_message = (payload.get('user_message') or '').strip()
    if not user_message:
        _fail('user_message is required')

    config = _load_config()
    chat_cfg = config.get('chat_agent', {})
    if not chat_cfg.get('enabled'):
        _fail('chat_agent.enabled is false')

    secret = chat_cfg.get('shared_secret') or ''
    if secret and payload.get('shared_secret') != secret:
        _fail('invalid shared secret')

    session_id = payload.get('session_id') or ''
    state = sessions.load(session_id) if session_id else None
    if state is None:
        session_id = sessions.new_session_id()
        state = sessions.new_state()

    try:
        result = await _run_turn(config, state, user_message)
    except Exception as e:
        _fail(f'agent error: {type(e).__name__}: {e}', session_id=session_id)
        return

    sessions.save(session_id, state)
    result['session_id'] = session_id
    _emit(result)


if __name__ == '__main__':
    asyncio.run(main())
