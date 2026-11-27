"""Minimal compliant MCP JSON-RPC 2.0 server over stdio for integration tests."""

from __future__ import annotations

import hashlib
import json
import sys


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        req_id = msg.get("id")

        if req_id is None:
            continue  # JSON-RPC notification

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mock-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "sha256_hex",
                        "description": "Compute SHA-256 hex digest of text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            }
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "sha256_hex":
                digest = hashlib.sha256(str(args.get("text", "")).encode("utf-8")).hexdigest()[:16]
                result = {"content": [{"type": "text", "text": f"digest={digest}"}], "isError": False}
            else:
                result = {"content": [{"type": "text", "text": f"Unknown tool {name}"}], "isError": True}
        else:
            result = {}

        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
