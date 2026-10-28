"""Build an MCP server from a product's plain functions (card P4).

    server = build_server("campus-ai-course-access", [audit_document, propose_fixes], instructions="...")
    serve(server)            # stdio (what MCP clients spawn); `--http PORT` serves streamable HTTP instead

Each function becomes a tool: its name, docstring and type hints give the
tool's name, description and input schema. Every tool takes a `data_class`
argument (P, I or S; R is refused before the function runs) and every call is
traced through `campus_ai.core.tracing` (tool, data class, latency, outcome;
never inputs or outputs). Nothing here is product logic.
"""

from __future__ import annotations

import argparse
import functools
import inspect
from collections.abc import Callable, Sequence

from mcp.server.mcpserver import MCPServer

from campus_ai.core import data_classes, tracing


def traced(fn: Callable) -> Callable:
    """Wrap a tool: refuse class R, trace the call, keep the signature and docstring."""
    signature = inspect.signature(fn)
    if "data_class" not in signature.parameters:
        raise TypeError(f"Tool {fn.__name__} must take a data_class argument")

    @functools.wraps(fn)
    def tool(*args, **kwargs):
        data_class = signature.bind(*args, **kwargs).arguments.get("data_class") or signature.parameters["data_class"].default
        with tracing.span("tool", tool=fn.__name__, data_class=str(data_class)):
            data_classes.check(data_class)
            return fn(*args, **kwargs)

    return tool


def build_server(name: str, tools: Sequence[Callable], instructions: str = "") -> MCPServer:
    server = MCPServer(name, instructions=instructions or None)
    for fn in tools:
        server.add_tool(traced(fn), name=fn.__name__)
    return server


def serve(server: MCPServer, argv: Sequence[str] | None = None) -> None:
    """Run over stdio, or over streamable HTTP with `--http PORT` (for the compose network)."""
    parser = argparse.ArgumentParser(description=server.instructions or server.name)
    parser.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on PORT instead of stdio")
    parser.add_argument("--host", default="0.0.0.0", help="address for --http (default: all interfaces)")
    args = parser.parse_args(argv)
    if args.http:
        import anyio
        anyio.run(lambda: server.run_streamable_http_async(host=args.host, port=args.http))
    else:
        server.run("stdio")
