"""Expose tool errors with a stable code while keeping MCP is_error semantics."""
import re
from mcp.server.mcpserver import MCPServer


class StructuredMCPServer(MCPServer):
    async def _handle_call_tool(self, ctx, params):
        result = await super()._handle_call_tool(ctx, params)
        if getattr(result, 'is_error', False):
            message = result.content[0].text if result.content else 'Tool failed'
            match = re.search(r'\[([a-z_]+)\] (.*)', message, re.DOTALL)
            if match:
                code, detail = match.groups()
            elif 'validation error' in message.lower():
                code, detail = 'invalid_input', message
            else:
                code, detail = 'internal_error', message
            result.structured_content = {'error': {'code': code, 'message': detail}}
        return result
