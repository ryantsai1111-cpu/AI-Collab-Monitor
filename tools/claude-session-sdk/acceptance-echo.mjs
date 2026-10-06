/** Authorized one-run STDIO MCP fixture using the already installed official MCP SDK.
 * No filesystem, network, shell, credential or persistent configuration operations.
 */
import { McpServer } from './node_modules/.pnpm/@modelcontextprotocol+sdk@1.32.0_zod@4.6.5/node_modules/@modelcontextprotocol/sdk/dist/esm/server/mcp.js';
import { StdioServerTransport } from './node_modules/.pnpm/@modelcontextprotocol+sdk@1.32.0_zod@4.6.5/node_modules/@modelcontextprotocol/sdk/dist/esm/server/stdio.js';
import { z } from './node_modules/.pnpm/zod@4.6.5/node_modules/zod/index.js';

const server = new McpServer({ name: 'acw_acceptance', version: '1.0.0' });
server.registerTool('echo', {
  description: 'Isolated acceptance only: returns the exact fixed ACW_MCP_ACCEPTANCE_OK string. No side effects.',
  inputSchema: { text: z.literal('ACW_MCP_ACCEPTANCE_OK') },
  annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  _meta: { 'anthropic/requiresUserInteraction': true },
}, async () => ({ content: [{ type: 'text', text: 'ACW_MCP_ACCEPTANCE_OK' }] }));

process.stdin.once('end', () => { void server.close(); });
await server.connect(new StdioServerTransport());
