/** Read-only public SDK session bridge. Never starts Claude or touches login APIs. */
import { readFile, realpath, stat } from 'node:fs/promises';
import { isAbsolute } from 'node:path';

const requestText = await new Promise((resolve, reject) => {
  let data = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => {
    data += chunk;
    if (data.length > 65536) reject(new Error('Session helper request too large'));
  });
  process.stdin.on('end', () => resolve(data));
  process.stdin.on('error', reject);
});

function metadata(info) {
  if (!info) return null;
  return {
    session_id: info.sessionId,
    summary: info.summary,
    custom_title: info.customTitle,
    last_modified: info.lastModified,
    file_size: info.fileSize,
    git_branch: info.gitBranch,
    cwd: info.cwd,
    created_at: info.createdAt,
  };
}

function excludePrivateBlocks(value) {
  if (Array.isArray(value)) return value.map(excludePrivateBlocks);
  if (!value || typeof value !== 'object') return value;
  const kind = String(value.type || '').toLowerCase();
  if (kind.includes('reasoning') || kind.startsWith('thinking') || kind === 'redacted_thinking') {
    return { type: 'omitted_reasoning', redaction: 'Hidden reasoning excluded' };
  }
  const result = {};
  for (const [key,item] of Object.entries(value)) {
    if (['thinking','signature','chain_of_thought','encrypted_content','reasoning_content'].includes(key)) {
      result[key] = '[OMITTED: hidden reasoning]';
    } else {
      result[key] = excludePrivateBlocks(item);
    }
  }
  if (['image','document'].includes(kind) && result.source && 'data' in result.source) {
    result.source.data = '[OMITTED: attachment binary; original file retained]';
  }
  return result;
}

try {
  const request = JSON.parse(requestText);
  const sdk = await import('@anthropic-ai/claude-agent-sdk');
  for (const name of ['listSessions','getSessionInfo','getSessionMessages']) {
    if (typeof sdk[name] !== 'function') throw new Error('Installed official SDK lacks public '+name);
  }
  const packageInfo = JSON.parse(await readFile(new URL('./package.json', import.meta.resolve('@anthropic-ai/claude-agent-sdk')), 'utf8'));
  let result;
  if (request.action === 'capabilities') {
    result = { version: packageInfo.version, api: 'official TypeScript Agent SDK',
      methods: ['listSessions','getSessionInfo','getSessionMessages'] };
  } else {
    if (typeof request.directory !== 'string' || !isAbsolute(request.directory)) throw new Error('An explicit absolute project directory is required');
    const dir = await realpath(request.directory);
    if (!(await stat(dir)).isDirectory()) throw new Error('Selected project is not a directory');
    const limit = request.limit ?? 100;
    const offset = request.offset ?? 0;
    if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !Number.isInteger(offset) || offset < 0 || offset > 10000) throw new Error('Invalid bounded page');
    if (request.action === 'list') {
      // Public listSessions has limit but no offset; apply bounded paging here.
      result = (await sdk.listSessions({dir,limit:offset+limit,includeWorktrees:false}))
        .slice(offset,offset+limit).map(metadata);
    } else {
      const sessionId = request.session_id;
      if (typeof sessionId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId)) throw new Error('Invalid explicit session ID');
      if (request.action === 'info') {
        result = metadata(await sdk.getSessionInfo(sessionId,{dir}));
      } else if (request.action === 'history') {
        const info = await sdk.getSessionInfo(sessionId,{dir});
        if (!info || info.sessionId !== sessionId) throw new Error('Selected native session no longer exists');
        const maxBytes = Math.min(request.max_bytes ?? 16777216,33554432);
        if (!Number.isInteger(info.fileSize) || info.fileSize < 0 || info.fileSize > maxBytes) throw new Error('Native transcript exceeds bounded history reader limit');
        if (info.cwd && (await realpath(info.cwd)).toLowerCase() !== dir.toLowerCase()) throw new Error('Native session belongs to a different project');
        result = (await sdk.getSessionMessages(sessionId,{dir,limit,offset})).map(item => ({
          type:item.type,uuid:item.uuid,session_id:item.session_id || item.sessionId,
          message:excludePrivateBlocks(item.message),parent_tool_use_id:item.parent_tool_use_id,
        }));
      } else throw new Error('Unsupported read-only session action');
    }
  }
  process.stdout.write(JSON.stringify({ok:true,version:packageInfo.version,result})+'\n');
} catch (error) {
  process.stdout.write(JSON.stringify({ok:false,error:String(error.message || error)})+'\n');
  process.exitCode = 1;
}
