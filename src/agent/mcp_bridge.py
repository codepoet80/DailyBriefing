"""Spawn the local MCP server over stdio and adapt its tools for the Anthropic API.

The chat handler runs as a short-lived CLI process per HTTP request. For each
turn we spin up `src/mcp_server.py` as a stdio MCP subprocess, list the tools
it advertises, filter by the configured allowlist, translate the schemas to
Anthropic's tool-use format, and shut everything down when the request ends.
"""
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@asynccontextmanager
async def mcp_session(server_command, server_args):
    params = StdioServerParameters(command=server_command, args=server_args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def to_anthropic_tools(mcp_tools, allowed):
    allowed_set = set(allowed)
    result = []
    for t in mcp_tools:
        if t.name not in allowed_set:
            continue
        schema = t.inputSchema or {'type': 'object', 'properties': {}}
        result.append({
            'name': t.name,
            'description': t.description or '',
            'input_schema': schema,
        })
    return result


async def call_mcp_tool(session, name, arguments):
    resp = await session.call_tool(name, arguments=arguments or {})
    parts = []
    for c in resp.content:
        text = getattr(c, 'text', None)
        if text:
            parts.append(text)
        else:
            parts.append(str(c))
    is_error = bool(getattr(resp, 'isError', False))
    return ('\n'.join(parts) if parts else '(no content)'), is_error
