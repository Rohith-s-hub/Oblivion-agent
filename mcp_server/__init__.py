"""
mcp_server — Oblivion MCP protocol server implementation.
"""
def main(*args, **kwargs):
    from mcp_server.server import main as _main
    return _main(*args, **kwargs)

__all__ = ["main"]
