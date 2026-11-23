#!/usr/bin/env node
// F106c: the harness loop, agent-runner's own agent loop for a session whose [models] role names a provider
// other than claude (copilot, codex, gemini, ollama, or one of [models.providers]). One session per process:
//
//   node harness.mjs --session-id SID --model codex:gpt-6-sol --notes DIR --prompt-file F [options]
//   node harness.mjs --resume SID ...          continue session SID from its transcript, F its next message
//
// Tools: bash, read, edit, write, finish, ask and publish_page (writes the page file; publishing it is F106f).
// Before every tool call the git fence (`run fence`, tools.fence's rules) is asked; before every model call the
// session's spend is held against --task-tokens and --task-usd. A line on stdin is a person's tell: queued,
// it goes in as the next user message. The transcript is <notes>/harness-sessions/<sid>.jsonl, one entry per
// line in Claude Code's shape (type user|assistant, message.content blocks text/tool_use/tool_result, usage in
// Claude's keys), so status, spend and resume read it as they read Claude's; each entry also keeps the provider
// message as it was (`harness`), which a resume reads back.
//
// The models come from @earendil-works/pi-ai, the provider and login package Pi itself uses (logins are Pi's:
// its auth.json). It is not bundled: the first session installs the pinned version under
// ~/.cache/agent-runner/harness (or AGENT_RUNNER_HARNESS_MODULES). AGENT_RUNNER_HARNESS_PROVIDER names a
// module that stands in for it (the tests' fake provider): its default export is
// `({provider, model}) => ({call(context) -> assistant message})`.

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const PI_AI = '@earendil-works/pi-ai';
const PI_AI_VERSION = '1.6.0'; // the version Pi 1.6.0 depends on
const OUTPUT_MAX = 30000; // characters of a tool's output the model sees: the head and the tail
const READ_LINES = 2000;
const BASH_TIMEOUT = 120;
const BASH_TIMEOUT_MAX = 3600;
const RETRIES = 3; // a transient model error is tried again this many times before the session ends
// $ per M tokens (input, output) when the provider gives no cost: cost.py's PRICES, an unknown model as opus
const PRICES = { opus: [5, 25], sonnet: [3, 15], haiku: [1, 5] };
const PROVIDER_IDS = { copilot: 'github-copilot', codex: 'openai-codex', gemini: 'google' };

// --- arguments ----------------------------------------------------------------------------------------------

function parseArgs(argv) {
  const a = { idle: 300, once: false, resume: false, taskTokens: 0, taskUsd: 0, fence: null, runner: null,
    provider: null, systemFile: '', promptFile: '', notes: '', sid: '', model: '' };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i], v = () => argv[++i];
    if (k === '--session-id') a.sid = v();
    else if (k === '--resume') { a.sid = v(); a.resume = true; }
    else if (k === '--model') a.model = v();
    else if (k === '--notes') a.notes = v();
    else if (k === '--prompt-file') a.promptFile = v();
    else if (k === '--system-file') a.systemFile = v();
    else if (k === '--idle') a.idle = Number(v());
    else if (k === '--once') a.once = true;
    else if (k === '--task-tokens') a.taskTokens = Number(v()) || 0;
    else if (k === '--task-usd') a.taskUsd = Number(v()) || 0;
    else if (k === '--fence-cmd') a.fence = JSON.parse(v());
    else if (k === '--runner-cmd') a.runner = JSON.parse(v());
    else if (k === '--provider') a.provider = JSON.parse(v());
    else throw new Error(`harness: unknown argument ${k}`);
  }
  if (!a.sid || !a.model || !a.notes) throw new Error('harness: --session-id (or --resume), --model and --notes are needed');
  return a;
}

// --- the transcript, in Claude Code's entry shape ------------------------------------------------------------

function textOf(content) {
  if (typeof content === 'string') return content;
  return (content || []).filter((b) => b && b.type === 'text').map((b) => b.text || '').join('\n');
}

function claudeUsage(u) {
  if (!u) return undefined;
  const out = { input_tokens: u.input || 0, output_tokens: u.output || 0, cache_read_input_tokens: u.cacheRead || 0,
    cache_creation_input_tokens: u.cacheWrite || 0 };
  if (u.cost && typeof u.cost.total === 'number') out.cost = { total: u.cost.total };
  return out;
}

// cost.turn_spend: tokens leave cache reads out, dollars count them all (the provider's own cost when it gives one)
function turnSpend(u, model) {
  if (!u) return [0, 0];
  const fresh = u.input_tokens || 0, read = u.cache_read_input_tokens || 0;
  const write = u.cache_creation_input_tokens || 0, out = u.output_tokens || 0;
  const m = (model || '').toLowerCase();
  const [pin, pout] = Object.entries(PRICES).find(([k]) => m.includes(k))?.[1] || PRICES.opus;
  let usd = (fresh * pin + write * pin * 1.25 + read * pin * 0.1 + out * pout) / 1e6;
  if (u.cost && typeof u.cost.total === 'number') usd = u.cost.total;
  return [fresh + write + out, usd];
}

function permanentError(text) {
  return /\b(?:400|401|403|404|413|422|429)\b|authentication|unauthorized|forbidden|billing|rate.?limit|invalid.?request/i.test(text);
}

function transientError(text) {
  return !permanentError(text) &&
    /network|fetch failed|ECONN|EAI_AGAIN|ETIMEDOUT|timeout|timed? out|connection|\b5\d\d\b|overloaded|unavailable/i.test(text);
}

class Transcript {
  constructor(file, sid, cwd) {
    this.file = file;
    this.sid = sid;
    this.cwd = cwd;
    this.last = null;
    fs.mkdirSync(path.dirname(file), { recursive: true });
  }

  // {messages, tokens, usd}: the provider messages a resume goes on from, and what the session has spent so far
  load() {
    const messages = [];
    let tokens = 0, usd = 0;
    if (!fs.existsSync(this.file)) return { messages, tokens, usd };
    for (const line of fs.readFileSync(this.file, 'utf8').split('\n')) {
      let e;
      try { e = JSON.parse(line); } catch { continue; }
      if (e.uuid) this.last = e.uuid;
      if (e.type === 'assistant' && e.message?.usage) {
        const [t, d] = turnSpend(e.message.usage, e.message.model);
        tokens += t; usd += d;
      }
      const m = e.harness;
      if (!m || (m.role === 'assistant' && (m.stopReason === 'error' || m.stopReason === 'aborted'))) continue;
      messages.push(m);
    }
    // a session cut off between a tool call and its result: the model is told the call never ran
    const out = [];
    for (let i = 0; i < messages.length; i++) {
      out.push(messages[i]);
      if (messages[i].role !== 'assistant') continue;
      const answered = new Set();
      for (let j = i + 1; j < messages.length && messages[j].role === 'toolResult'; j++) answered.add(messages[j].toolCallId);
      const missing = messages[i].content.filter((b) => b.type === 'toolCall' && !answered.has(b.id));
      let j = i + 1;
      while (j < messages.length && messages[j].role === 'toolResult') out.push(messages[j++]);
      for (const b of missing) {
        out.push({ role: 'toolResult', toolCallId: b.id, toolName: b.name, isError: true, timestamp: Date.now(),
          content: [{ type: 'text', text: 'The session was cut off before this tool call ran; it did not run.' }] });
      }
      i = j - 1;
    }
    return { messages: out, tokens, usd };
  }

  write(type, message, harness, extra = {}) {
    const uuid = crypto.randomUUID();
    const e = { type, uuid, parentUuid: this.last, sessionId: this.sid, timestamp: new Date().toISOString(),
      cwd: this.cwd, entrypoint: 'agent-runner-harness', ...extra, message, ...(harness ? { harness } : {}) };
    fs.appendFileSync(this.file, JSON.stringify(e) + '\n');
    this.last = uuid;
    return e;
  }

  user(text) {
    const m = { role: 'user', content: text, timestamp: Date.now() };
    this.write('user', { role: 'user', content: text }, m);
    return m;
  }

  assistant(m) {
    const content = [];
    for (const b of m.content || []) {
      if (b.type === 'text') content.push({ type: 'text', text: b.text });
      else if (b.type === 'thinking') content.push({ type: 'thinking', thinking: b.thinking || '' });
      else if (b.type === 'toolCall') content.push({ type: 'tool_use', id: b.id, name: b.name, input: b.arguments || {} });
    }
    const extra = {};
    if (m.stopReason === 'error') {
      const text = m.errorMessage || 'the model request failed';
      extra.isApiErrorMessage = true;
      extra.error = transientError(text) ? 'server_error' : 'invalid_request';
      content.splice(0, content.length, { type: 'text', text });
    }
    const stop = { stop: 'end_turn', toolUse: 'tool_use', length: 'max_tokens' }[m.stopReason] || null;
    this.write('assistant', { id: m.responseId || `msg_${crypto.randomUUID()}`, type: 'message', role: 'assistant',
      model: m.model, content, stop_reason: stop, usage: claudeUsage(m.usage) }, m, extra);
  }

  toolResult(call, text, isError) {
    const m = { role: 'toolResult', toolCallId: call.id, toolName: call.name, isError,
      content: [{ type: 'text', text }], timestamp: Date.now() };
    this.write('user', { role: 'user', content: [{ type: 'tool_result', tool_use_id: call.id, content: text,
      is_error: isError }] }, m);
    return m;
  }

  note(text) { // a line of the harness's own (a budget stop): shown, never sent to the model
    this.write('system', { role: 'system', content: text }, null, { subtype: 'harness' });
  }
}

// --- the person's tells, from stdin ----------------------------------------------------------------------------

// The runner types a tell as a bracketed paste and Enter (slots.send_fifo); a plain line works too. Each one is
// queued and goes in as the next user message.
class Tells {
  constructor(input) {
    this.queue = [];
    this.waiters = [];
    this.buf = '';
    this.paste = false;
    if (input.isTTY && input.setRawMode) { // raw: a tell is not cut at the terminal's line limit (4 KB)
      input.setRawMode(true);
      if (process.platform !== 'win32') spawnSync('stty', ['opost', 'onlcr'], { stdio: ['inherit', 'ignore', 'ignore'] });
    }
    input.setEncoding('utf8');
    input.on('data', (d) => this.feed(d));
    input.on('error', () => {});
    input.resume();
  }

  feed(data) {
    for (let i = 0; i < data.length; i++) {
      if (data.startsWith('\x1b[200~', i)) { this.paste = true; i += 5; continue; }
      if (data.startsWith('\x1b[201~', i)) { this.paste = false; i += 5; continue; }
      const c = data[i];
      if ((c === '\r' || c === '\n') && !this.paste) { this.push(this.buf); this.buf = ''; continue; }
      if (c === '\x03') process.exit(130); // Ctrl-C in its terminal
      if (c === '\x1b' && !this.paste) continue; // a lone Escape (an interrupt to Claude Code): nothing here
      this.buf += c === '\r' ? '\n' : c;
    }
  }

  push(text) {
    text = text.trim();
    if (!text) return;
    this.queue.push(text);
    for (const w of this.waiters.splice(0)) w();
  }

  take() { return this.queue.splice(0); }

  // resolves true when a tell came within `seconds`, false when none did
  wait(seconds) {
    if (this.queue.length) return Promise.resolve(true);
    return new Promise((resolve) => {
      const t = setTimeout(() => resolve(false), seconds * 1000);
      this.waiters.push(() => { clearTimeout(t); resolve(true); });
    });
  }
}

// --- the provider ---------------------------------------------------------------------------------------------

function modulesDir() {
  return process.env.AGENT_RUNNER_HARNESS_MODULES ||
    path.join(os.homedir(), '.cache', 'agent-runner', `harness-${PI_AI_VERSION}`);
}

async function piAi(sub) {
  const dir = modulesDir();
  const pkg = path.join(dir, 'node_modules', ...PI_AI.split('/'));
  if (!fs.existsSync(path.join(pkg, 'package.json'))) {
    console.log(`harness: installing ${PI_AI}@${PI_AI_VERSION} in ${dir} (once)`);
    fs.mkdirSync(dir, { recursive: true });
    const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
    const r = spawnSync(npm, ['install', '--prefix', dir, '--no-audit', '--no-fund', '--ignore-scripts',
      `${PI_AI}@${PI_AI_VERSION}`], { stdio: 'inherit', shell: process.platform === 'win32' });
    if (r.status !== 0) throw new Error(`harness: npm install ${PI_AI}@${PI_AI_VERSION} failed in ${dir}`);
  }
  return import(pathToFileURL(path.join(pkg, 'dist', `${sub}.js`)).href);
}

// Pi's own logins (`pi` /login): its auth.json, one credential per provider, read and written as Pi does
function piCredentials() {
  const file = path.join(process.env.PI_CODING_AGENT_DIR || path.join(os.homedir(), '.pi', 'agent'), 'auth.json');
  const all = () => { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; } };
  const save = (data) => {
    const tmp = `${file}.harness-${process.pid}`;
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, file);
  };
  // the lock Pi takes on it (proper-lockfile: a folder beside it, stale after 10 s), so a token refresh here and
  // one in a Pi session never write over each other
  const lock = async () => {
    const dir = `${file}.lock`, end = Date.now() + 15000;
    for (;;) {
      try { fs.mkdirSync(dir); return () => fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {
        if (e.code !== 'EEXIST') return () => {};
        try { if (Date.now() - fs.statSync(dir).mtimeMs > 10000) { fs.rmSync(dir, { recursive: true, force: true }); continue; } } catch {}
        if (Date.now() > end) throw new Error(`harness: ${dir} is held; a Pi session is writing its logins`);
        await new Promise((r) => setTimeout(r, 200));
      }
    }
  };
  let chain = Promise.resolve();
  return {
    async read(id) { return all()[id]; },
    async list() { return Object.entries(all()).map(([providerId, c]) => ({ providerId, type: c?.type })); },
    modify(id, fn) {
      const run = chain.then(async () => {
        const unlock = await lock();
        try {
          const data = all();
          const next = await fn(data[id]);
          if (JSON.stringify(next) === JSON.stringify(data[id])) return next;
          if (next === undefined) delete data[id]; else data[id] = next;
          save(data);
          return next;
        } finally { unlock(); }
      });
      chain = run.catch(() => {});
      return run;
    },
    async delete(id) { const data = all(); delete data[id]; save(data); },
  };
}

function plainModel(id, provider, api, baseUrl) {
  return { id, name: id, api, provider, baseUrl, reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 16384 };
}

async function realProvider(name, modelId, custom) {
  const ai = await piAi('index');
  const credentials = piCredentials();
  let models, model;
  if (name === 'ollama' || custom) {
    const api = custom?.kind === 'anthropic' ? 'anthropic-messages' : 'openai-completions';
    const baseUrl = custom?.url || `${(process.env.OLLAMA_HOST || 'http://localhost:11434').replace(/\/$/, '')}/v1`;
    const impl = api === 'anthropic-messages' ? (await piAi('api/anthropic-messages.lazy')).anthropicMessagesApi()
      : (await piAi('api/openai-completions.lazy')).openAICompletionsApi();
    const keyEnv = custom?.key_env;
    model = plainModel(modelId, name, api, baseUrl);
    if (api === 'openai-completions') model.compat = { supportsDeveloperRole: false, supportsReasoningEffort: false };
    const auth = keyEnv ? ai.envApiKeyAuth(name, [keyEnv]) : { name, resolve: async () => ({ auth: {} }) };
    models = ai.createModels({ credentials });
    models.setProvider(ai.createProvider({ id: name, name, baseUrl, auth: { apiKey: auth }, models: [model], api: impl }));
  } else {
    const id = PROVIDER_IDS[name] || name;
    models = (await piAi('providers/all')).builtinModels({ credentials });
    model = models.getModel(id, modelId);
    if (!model) {
      const known = models.getModels(id).map((m) => m.id);
      throw new Error(`harness: ${name} (${id}) has no model ${modelId}; it has: ${known.join(', ') || 'none'}`);
    }
  }
  return { call: (context, signal) => models.completeSimple(model, context, { signal }) };
}

async function loadProvider(spec, custom) {
  const at = spec.indexOf(':');
  const provider = at < 0 ? spec : spec.slice(0, at), model = at < 0 ? '' : spec.slice(at + 1);
  if (!model) throw new Error(`harness: --model ${spec} names no model after the provider`);
  if (process.env.AGENT_RUNNER_HARNESS_PROVIDER) {
    const mod = await import(pathToFileURL(path.resolve(process.env.AGENT_RUNNER_HARNESS_PROVIDER)).href);
    return mod.default({ provider, model, custom });
  }
  return realProvider(provider, model, custom);
}

// --- the tools ------------------------------------------------------------------------------------------------

const TOOLS = [
  { name: 'bash', description: `Run a bash command in the worktree (each call starts there; cd does not carry over). ` +
      `Output (stdout and stderr) beyond ${OUTPUT_MAX} characters is cut in the middle. timeout is in seconds ` +
      `(default ${BASH_TIMEOUT}, at most ${BASH_TIMEOUT_MAX}).`,
    parameters: { type: 'object', properties: { command: { type: 'string' }, timeout: { type: 'number' } },
      required: ['command'] } },
  { name: 'read', description: `Read a text file: its lines numbered, ${READ_LINES} from offset (1-based) unless limit says otherwise.`,
    parameters: { type: 'object', properties: { path: { type: 'string' }, offset: { type: 'number' },
      limit: { type: 'number' } }, required: ['path'] } },
  { name: 'edit', description: 'Replace old_string with new_string in a file. old_string must occur exactly once ' +
      'unless replace_all is true.',
    parameters: { type: 'object', properties: { path: { type: 'string' }, old_string: { type: 'string' },
      new_string: { type: 'string' }, replace_all: { type: 'boolean' } }, required: ['path', 'old_string', 'new_string'] } },
  { name: 'write', description: 'Write a whole file (its folders are made), replacing what was there.',
    parameters: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } },
      required: ['path', 'content'] } },
  { name: 'finish', description: 'The task is done (after `done`, or `done --blocked`): records the one-line summary ' +
      'and ends this session.',
    parameters: { type: 'object', properties: { summary: { type: 'string' } }, required: ['summary'] } },
  { name: 'ask', description: 'Ask the person a question only they can answer, with what you recommend: the task is ' +
      'parked under Needs you and their answer resumes this session as its next message. The session ends.',
    parameters: { type: 'object', properties: { question: { type: 'string' } }, required: ['question'] } },
  { name: 'publish_page', description: 'Make a page to show the person (a report, a concept\'s options): the HTML is ' +
      'written to a file under the run\'s notes, and its path comes back. Link that path in your journal.',
    parameters: { type: 'object', properties: { name: { type: 'string', description: 'a short file name' },
      html: { type: 'string' } }, required: ['name', 'html'] } },
];

// the tool calls the git fence reads, as Claude Code's (tools.FENCE_TOOLS)
const FENCED = { bash: (a) => ['Bash', { command: a.command || '' }], edit: (a) => ['Edit', { file_path: a.path }],
  write: (a) => ['Write', { file_path: a.path }] };

function clip(text) {
  if (text.length <= OUTPUT_MAX) return text;
  const head = Math.floor(OUTPUT_MAX / 3);
  return `${text.slice(0, head)}\n\n[... ${text.length - OUTPUT_MAX} characters cut ...]\n\n${text.slice(-(OUTPUT_MAX - head))}`;
}

function run(argv, cwd, input, timeout) {
  return new Promise((resolve) => {
    const p = spawn(argv[0], argv.slice(1), { cwd, env: process.env, detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '', timedOut = false;
    const t = setTimeout(() => {
      timedOut = true;
      try { process.kill(-p.pid, 'SIGKILL'); } catch { try { p.kill('SIGKILL'); } catch {} }
    }, timeout * 1000);
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { out += d; });
    p.on('error', (e) => { clearTimeout(t); resolve({ code: 127, out: String(e) }); });
    p.on('close', (code) => { clearTimeout(t); resolve({ code: timedOut ? 124 : code, out, timedOut }); });
    p.stdin.on('error', () => {});
    p.stdin.end(input || '');
  });
}

class Session {
  constructor(a, cwd) {
    this.a = a;
    this.cwd = cwd;
    this.ended = '';
    this.tid = this.task();
  }

  task() {
    const r = spawnSync('git', ['branch', '--show-current'], { cwd: this.cwd, encoding: 'utf8' });
    const b = (r.stdout || '').trim();
    return b.startsWith('task/') ? b.slice(5) : '';
  }

  endMark() {
    const slot = process.env.AGENT_RUNNER_SLOT;
    return slot ? path.join(this.a.notes, `slot${slot}.end`) : '';
  }

  // the end mark `run finish` or `run ask` leaves, whichever tool (or bash line) ran it
  endedNow() {
    const m = this.endMark();
    if (!m || !fs.existsSync(m)) return '';
    try { return JSON.parse(fs.readFileSync(m, 'utf8')).how || 'finish'; } catch { return 'finish'; }
  }

  resolve(p) { return path.resolve(this.cwd, String(p || '').replace(/^~(?=$|\/)/, os.homedir())); }

  async fence(name, args) {
    if (!this.a.fence || !FENCED[name]) return '';
    const [tool, input] = FENCED[name](args);
    const r = await run(this.a.fence, this.cwd, JSON.stringify({ tool_name: tool, tool_input: input, cwd: this.cwd }), 60);
    // the hook always exits 0 (tools.fence_hook); any other exit is a fence that could not run: denied, not let by
    if (r.code !== 0) return `the git fence could not run (exit code ${r.code}), so this call is denied: ${r.out.trim().slice(-300)}`;
    try {
      const out = JSON.parse(r.out.trim().split('\n').pop() || '{}').hookSpecificOutput;
      return out?.permissionDecision === 'deny' ? out.permissionDecisionReason || 'the git fence denies it' : '';
    } catch { return ''; }
  }

  async call(name, args) {
    args = args || {};
    const denied = await this.fence(name, args);
    if (denied) return [denied, true];
    try {
      return await this[`tool_${name}`](args);
    } catch (e) {
      return [`${name} failed: ${e.message || e}`, true];
    }
  }

  async tool_bash(a) {
    const timeout = Math.min(Math.max(Number(a.timeout) || BASH_TIMEOUT, 1), BASH_TIMEOUT_MAX);
    const r = await run(['bash', '-c', String(a.command || '')], this.cwd, '', timeout);
    const tail = r.timedOut ? `\n[timed out after ${timeout} s; the command was killed]` :
      r.code ? `\n[exit code ${r.code}]` : '';
    return [clip(r.out) + tail || '(no output)', Boolean(r.code)];
  }

  async tool_read(a) {
    const f = this.resolve(a.path);
    const data = fs.readFileSync(f);
    if (data.includes(0)) return [`${f} is a binary file`, true];
    const lines = data.toString('utf8').split('\n');
    const from = Math.max((Number(a.offset) || 1) - 1, 0), n = Number(a.limit) || READ_LINES;
    const shown = lines.slice(from, from + n).map((l, i) => `${String(from + i + 1).padStart(6)}\t${l.slice(0, 2000)}`);
    const more = from + n < lines.length ? `\n[${lines.length - from - n} more lines: read on with offset ${from + n + 1}]` : '';
    return [clip(shown.join('\n')) + more || '(empty file)', false];
  }

  async tool_edit(a) {
    const f = this.resolve(a.path);
    const text = fs.readFileSync(f, 'utf8');
    const old = String(a.old_string ?? '');
    if (!old) return ['old_string is empty', true];
    const n = text.split(old).length - 1;
    if (!n) return [`old_string is not in ${f}`, true];
    if (n > 1 && !a.replace_all) return [`old_string occurs ${n} times in ${f}: give more context, or replace_all`, true];
    fs.writeFileSync(f, a.replace_all ? text.split(old).join(String(a.new_string ?? '')) :
      text.replace(old, () => String(a.new_string ?? '')));
    return [`edited ${f}${n > 1 ? ` (${n} places)` : ''}`, false];
  }

  async tool_write(a) {
    const f = this.resolve(a.path);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, String(a.content ?? ''));
    return [`wrote ${f}`, false];
  }

  async runner(cmd, text) {
    if (!this.a.runner) return [`no runner command was given, so ${cmd} cannot run here`, true];
    const r = await run([...this.a.runner, cmd, String(text || '')], this.cwd, '', 120);
    if (!r.code && (this.ended = this.endedNow() || (this.endMark() ? '' : cmd))) return [r.out.trim(), false];
    return [r.out.trim() || `${cmd} failed (exit code ${r.code})`, Boolean(r.code)];
  }

  async tool_finish(a) { return this.runner('finish', a.summary); }

  async tool_ask(a) { return this.runner('ask', a.question); }

  async tool_publish_page(a) {
    const name = String(a.name || 'page').replace(/\.html?$/i, '').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80) || 'page';
    const f = path.join(this.a.notes, 'harness-pages', this.tid || this.a.sid, `${name}.html`);
    const denied = await this.fence('write', { path: f });
    if (denied) return [denied, true];
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, String(a.html ?? ''));
    return [`page written to ${f}`, false];
  }
}

// --- the loop -------------------------------------------------------------------------------------------------

const SYSTEM = `You are an unattended coding agent that agent-runner started in a git worktree; nobody watches ` +
  `this session live. Do the task in the first message with your tools: bash, read, edit, write, and finish when ` +
  `you are done, ask when only a person can answer, publish_page to show the person a page. Paths are relative ` +
  `to the worktree. A message that arrives while you work is the person telling you something: take it into ` +
  `account. When the task's brief names \`run finish\` or \`run ask\`, the finish and ask tools do the same.`;

function overBudget(a, tokens, usd) {
  const tok = tokens >= 1e6 ? `${(tokens / 1e6).toFixed(1)}M` : `${Math.round(tokens / 1e3)}k`;
  const spent = `${tok} tok $${usd.toFixed(2)}`;
  if (a.taskTokens && tokens >= a.taskTokens) return `${spent} is past [run] task_tokens (${a.taskTokens.toLocaleString('en-US')})`;
  if (a.taskUsd && usd >= a.taskUsd) return `${spent} is past [run] task_usd ($${a.taskUsd.toFixed(2)})`;
  return '';
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const cwd = process.cwd();
  const file = path.join(a.notes, 'harness-sessions', `${a.sid}.jsonl`);
  if (a.resume && !fs.existsSync(file)) throw new Error(`harness: session ${a.sid} has no transcript at ${file}`);
  if (!a.resume && fs.existsSync(file)) throw new Error(`harness: session ${a.sid} exists already (${file}); --resume it`);
  const t = new Transcript(file, a.sid, cwd);
  let { messages, tokens, usd } = t.load();
  const system = [SYSTEM, a.systemFile && fs.existsSync(a.systemFile) ? fs.readFileSync(a.systemFile, 'utf8') : '']
    .filter(Boolean).join('\n\n');
  const prompt = a.promptFile ? fs.readFileSync(a.promptFile, 'utf8') : '';
  const s = new Session(a, cwd);
  const tells = new Tells(process.stdin);
  const provider = await loadProvider(a.model, a.provider);
  console.log(`harness: ${a.resume ? 'resumed' : 'started'} session ${a.sid} on ${a.model} in ${cwd}`);
  const pending = prompt.trim() ? [prompt] : [];
  let failures = 0;
  for (;;) {
    for (const text of [...pending.splice(0), ...tells.take()]) {
      messages.push(t.user(text));
      console.log(`\n> ${text.split('\n')[0].slice(0, 160)}`);
    }
    const why = overBudget(a, tokens, usd);
    if (why) {
      if (s.tid) fs.writeFileSync(path.join(a.notes, `${s.tid}.budget`), why + '\n');
      t.note(`the session stopped before its next model call: ${why}`);
      console.log(`harness: stopped, ${why}`);
      return 0;
    }
    let m;
    try {
      m = await provider.call({ systemPrompt: system, messages, tools: TOOLS });
    } catch (e) {
      m = { role: 'assistant', content: [], stopReason: 'error', errorMessage: String(e?.message || e), model: a.model,
        timestamp: Date.now() };
    }
    if (m.stopReason === 'error' && transientError(m.errorMessage || '') && failures < RETRIES) {
      failures++;
      console.log(`harness: the model call failed (${m.errorMessage}); trying again (${failures}/${RETRIES})`);
      await new Promise((r) => setTimeout(r, 5000 * 2 ** failures));
      continue;
    }
    failures = 0;
    t.assistant(m);
    const [dt, du] = turnSpend(claudeUsage(m.usage), m.model);
    tokens += dt; usd += du;
    if (m.stopReason === 'error' || m.stopReason === 'aborted') {
      console.log(`harness: the model call failed: ${m.errorMessage || m.stopReason}`);
      return 1;
    }
    messages.push(m);
    const said = textOf(m.content.filter((b) => b.type === 'text'));
    if (said) console.log(said);
    const calls = m.content.filter((b) => b.type === 'toolCall');
    for (const c of calls) {
      console.log(`· ${c.name} ${JSON.stringify(c.arguments || {}).slice(0, 200)}`);
      const [text, isError] = c.argumentsError ? [c.argumentsError, true] : await s.call(c.name, c.arguments);
      messages.push(t.toolResult(c, text, isError));
      if (!s.ended) s.ended = s.endedNow();
    }
    if (s.ended) {
      console.log(`harness: the session ended (${s.ended})`);
      return 0;
    }
    if (calls.length) continue;
    if (a.once) return 0;
    if (!(await tells.wait(a.idle))) {
      console.log(`harness: ${a.idle} s at the prompt with nothing told: the session ends`);
      return 0;
    }
  }
}

main().then((code) => process.exit(code), (e) => {
  console.error(e?.message || e);
  process.exit(2);
});
