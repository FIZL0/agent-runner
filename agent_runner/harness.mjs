#!/usr/bin/env node
// F106c: the harness loop, agent-runner's own agent loop for a session whose [models] role names a provider
// other than claude (copilot, codex, gemini, ollama, or one of [models.providers]). One session per process:
//
//   node harness.mjs --session-id SID --model codex:gpt-6-sol --notes DIR --prompt-file F [options]
//   node harness.mjs --resume SID ...          continue session SID from its transcript, F its next message
//   ... --once --tools read                    a one-shot (F406e): one answer, with only the tools named (a comma between)
//   ... --chat                                 a control session (F406f): many turns, waiting for the person between them
//
// Tools: bash, read, edit, write, finish, ask and publish_page (writes the page file and runs `run publish-page`
// on it: the run page shows it, and a one-shot publishes it to claude.ai when Claude Code is here).
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
import { fileURLToPath, pathToFileURL } from 'node:url';

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
  const a = { idle: 300, once: false, chat: false, resume: false, taskTokens: 0, taskUsd: 0, tools: null, contextWarn: 0, contextText: '', fence: null, runner: null,
    provider: null, systemFile: '', promptFile: '', notes: '', sid: '', model: '', fallback: [] };
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
    else if (k === '--chat') { a.chat = true; a.tools = CHAT_TOOLS; }
    else if (k === '--tools') a.tools = v().split(',').filter(Boolean);
    else if (k === '--task-tokens') a.taskTokens = Number(v()) || 0;
    else if (k === '--task-usd') a.taskUsd = Number(v()) || 0;
    else if (k === '--context-warn') a.contextWarn = Number(v()) || 0;
    else if (k === '--context-text') a.contextText = v();
    else if (k === '--fence-cmd') a.fence = JSON.parse(v());
    else if (k === '--runner-cmd') a.runner = JSON.parse(v());
    else if (k === '--provider') a.provider = JSON.parse(v());
    else if (k === '--fallback') a.fallback = JSON.parse(v());
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

// the context a call was made with, as watch.usage counts it
function contextOf(u) {
  return (u?.input_tokens || 0) + (u?.cache_read_input_tokens || 0) + (u?.cache_creation_input_tokens || 0);
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

// F106g: a usage cap or quota error: the session goes on with the next model in its --fallback chain
function capError(text) {
  return /\b429\b|rate.?limit|quota|usage limit|limit reached|resource.?exhausted|too many requests/i.test(text);
}

// F106g: `<notes>/capped.json` ({provider: until}), which the runner reads to start new tasks down the chain
const CAP_HOLD = 3600;
function markCapped(notes, provider) {
  const file = path.join(notes, 'capped.json');
  let d = {};
  try { d = JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch { d = {}; }
  d[provider] = Math.max(Number(d[provider]) || 0, Date.now() / 1000 + CAP_HOLD);
  try { fs.writeFileSync(file, JSON.stringify(d)); } catch { /* the switch goes on without it */ }
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

  // the biggest context, in tokens, the session has had so far (F177)
  peak() {
    let peak = 0;
    if (!fs.existsSync(this.file)) return peak;
    for (const line of fs.readFileSync(this.file, 'utf8').split('\n')) {
      let e;
      try { e = JSON.parse(line); } catch { continue; }
      if (e.type === 'assistant') peak = Math.max(peak, contextOf(e.message?.usage));
    }
    return peak;
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

  toolResult(call, text, isError, image = null) {
    const m = { role: 'toolResult', toolCallId: call.id, toolName: call.name, isError,
      content: [{ type: 'text', text }, ...(image ? [image] : [])], timestamp: Date.now() };
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
  constructor(input, chat = null) { // chat (F406f): {interrupt(), end()}, for Escape, Ctrl-C and a closed terminal
    this.queue = [];
    this.waiters = [];
    this.chat = chat;
    this.ended = false;
    this.changed = null; // called when the queue grew or was taken
    this.held = ''; // the start of an escape sequence, until the rest of it comes
    this.echo = Boolean(chat && input.isTTY);
    this.buf = '';
    this.paste = false;
    this.cr = false; // the last character was '\r': a '\n' after it is the same line end (CRLF, as Windows pipes it)
    if (input.isTTY && input.setRawMode) { // raw: a tell is not cut at the terminal's line limit (4 KB)
      input.setRawMode(true);
      if (process.platform !== 'win32') spawnSync('stty', ['opost', 'onlcr'], { stdio: ['inherit', 'ignore', 'ignore'] });
    }
    input.setEncoding('utf8');
    input.on('data', (d) => this.feed(d));
    input.on('error', () => {});
    input.on('end', () => { this.ended = true; this.wake(); });
    if (this.echo) process.stdout.write('\x1b[?2004h'); // bracketed paste on: it takes input (control_takes_input)
    input.resume();
  }

  show(s) { if (this.echo) process.stdout.write(s); }

  // B865: erase the line(s) the typed message was echoed on; it is printed again as saidLines once sent
  unshow() {
    if (!this.echo) return;
    const cols = process.stdout.columns || 100;
    let rows = 0;
    for (const line of this.buf.split('\n')) rows += Math.max(1, Math.ceil([...line].length / cols));
    this.show('\r\x1b[2K' + '\x1b[1A\x1b[2K'.repeat(rows - 1));
  }

  // a key of a chat's line editor; whether it was one
  key(c) {
    if (c === '\x03' || c === '\x1b') {
      if (!this.chat.interrupt() && c === '\x03') this.chat.end();
    } else if (c === '\x0f') { // Ctrl+O (F489): the calls behind the tally line
      this.unshow(); // the calls go above the message being typed, which is drawn again under them
      this.chat.expand?.();
      this.show(this.buf.replace(/\n/g, '\r\n'));
    } else if (c === '\x04') {
      if (!this.buf) this.chat.end();
    } else if (c === '\x7f' || c === '\b') {
      if (this.buf) this.show('\b \b');
      this.buf = [...this.buf].slice(0, -1).join('');
    } else if (c === '\x15') {
      this.show('\b \b'.repeat([...this.buf].length));
      this.buf = '';
    } else return false;
    return true;
  }

  feed(data) {
    data = this.held + data;
    this.held = '';
    clearTimeout(this.lone);
    for (let i = 0; i < data.length; i++) {
      if (data[i] === '\x1b') {
        const rest = data.slice(i);
        // a paste mark cut by the read: kept for the next one. A chat's lone Escape waits 50 ms for the rest of one
        if (['\x1b[200~', '\x1b[201~'].some((m) => m !== rest && m.startsWith(rest)) && (rest.length > 1 || this.paste || this.chat)) {
          this.held = rest;
          if (this.chat && rest === '\x1b' && !this.paste) {
            this.lone = setTimeout(() => { this.held = ''; this.key('\x1b'); }, 50);
          }
          return;
        }
        // an arrow or another key's sequence: nothing here
        const seq = this.chat && !this.paste && !/^\x1b\[20[01]~/.test(rest) && /^\x1b(?:\[[0-9;?]*[ -/]*[@-~]|O[A-Za-z])/.exec(rest);
        if (seq) { i += seq[0].length - 1; continue; }
      }
      if (data.startsWith('\x1b[200~', i)) { this.paste = true; this.cr = false; i += 5; continue; }
      if (data.startsWith('\x1b[201~', i)) { this.paste = false; this.cr = false; i += 5; continue; }
      const c = data[i];
      const crlf = this.cr && c === '\n';
      this.cr = c === '\r';
      if (crlf) continue;
      if ((c === '\r' || c === '\n') && !this.paste) { this.unshow(); this.push(this.buf); this.buf = ''; continue; }
      if (this.chat && !this.paste && this.key(c)) continue;
      if (c === '\x03') process.exit(130); // Ctrl-C in its terminal
      if (c === '\x1b' && !this.paste) continue; // a lone Escape (an interrupt to Claude Code): nothing here
      this.buf += c === '\r' ? '\n' : c;
      this.show(c === '\r' || c === '\n' ? '\r\n' : c < ' ' ? '' : c);
    }
  }

  push(text) {
    text = text.trim();
    if (!text) return;
    this.queue.push(text);
    this.changed?.();
    this.wake();
  }

  wake() { for (const w of this.waiters.splice(0)) w(); }

  take() {
    const got = this.queue.splice(0);
    if (got.length) this.changed?.();
    return got;
  }

  // resolves true when a tell came within `seconds` (Infinity: no limit, but a closed input ends it), false when none did
  wait(seconds) {
    if (this.queue.length) return Promise.resolve(true);
    if (seconds === Infinity) {
      if (this.ended) return Promise.resolve(false);
      return new Promise((resolve) => { this.waiters.push(() => resolve(this.queue.length > 0)); });
    }
    return new Promise((resolve) => {
      const t = setTimeout(() => resolve(false), seconds * 1000);
      this.waiters.push(() => { if (this.queue.length) { clearTimeout(t); resolve(true); } });
    });
  }
}

// --- what a chat is doing now (F406g) ------------------------------------------------------------------------------

// How a message about a chat's question begins, not its answer: as chat_question.py's ABOUT and NOT (F433)
const ABOUT = 'About your question “', NOT = '” (not my answer): ';
const isAbout = (text) => text.startsWith(ABOUT) && text.includes(NOT);

// `<notes>/<sid>.now`, which the run page reads (session_now.record): busy or idle, since when, how many messages are
// queued, and whether any of them is not about the chat's question (answers, F433). In Claude Code's words; gone once
// the chat ended.
class Now {
  constructor(a) {
    this.file = path.join(a.notes, `${a.sid}.now`);
    this.d = { pid: process.pid, sessionId: a.sid, startedAt: Date.now(), status: '', statusUpdatedAt: 0, queued: 0, answers: false };
    process.on('exit', () => { try { fs.unlinkSync(this.file); } catch { /* not there */ } });
  }

  set(status, queue) {
    if (status !== this.d.status) this.d.statusUpdatedAt = Date.now();
    Object.assign(this.d, { status, queued: queue.length, answers: !queue.every(isAbout) });
    const part = `${this.file}.part`;
    try { fs.writeFileSync(part, JSON.stringify(this.d)); fs.renameSync(part, this.file); } catch { /* the next change writes it */ }
  }
}

// A viewer that comes to a chat's terminal sees what was said: at its new size (attach.Viewers gives one to each viewer
// that comes) the screen is drawn again from the last SCREEN characters printed.
const SCREEN = 32000;
// B861: the person's message as Claude Code draws it: '❯ ' and every line, wrapped, on the
// colour-237 band the run page shows as the highlighted (.hy) band
export function saidLines(text, cols = (process.stdout.columns || 100)) {
  const w = Math.max(20, cols - 2), rows = [];
  for (const line of String(text).replace(/\r/g, '').split('\n')) {
    const cps = [...line];
    if (!cps.length) rows.push('');
    for (let i = 0; i < cps.length; i += w) rows.push(cps.slice(i, i + w).join(''));
  }
  return '\n' + rows.map((r, i) => `\x1b[48;5;237m${i ? '  ' : '❯ '}${r}${' '.repeat(Math.max(0, w - [...r].length))}\x1b[0m`).join('\n');
}

// F483: the model's reply as Claude Code draws it: '● ' then the markdown rendered (bold, italics, inline code,
// lists, headings), word-wrapped to the terminal with a hanging indent under the marker and under each list item
const visible = (s) => [...s.replace(/\x1b\[[0-9;]*m/g, '')].length;
function inlineMd(s) {
  const code = [];
  return s
    .replace(/`([^`]+)`/g, (_, x) => `\x00${code.push(x) - 1}\x00`)
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, x, y) => `\x1b[1m${x ?? y}\x1b[22m`)
    .replace(/(^|[^\w*])\*([^*\s][^*]*?)\*(?!\w)|(^|[^\w])_([^_\s][^_]*?)_(?!\w)/g,
      (_, p, x, q, y) => `${p ?? q}\x1b[3m${x ?? y}\x1b[23m`)
    .replace(/\x00(\d+)\x00/g, (_, i) => `\x1b[36m${code[i]}\x1b[39m`);
}
function wrapped(text, first, rest, w) {
  const out = [];
  let line = first, len = visible(first), empty = true;
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const n = visible(word);
    if (!empty && len + 1 + n > w) { out.push(line); line = rest; len = visible(rest); empty = true; }
    line += (empty ? '' : ' ') + word; len += (empty ? 0 : 1) + n; empty = false;
  }
  out.push(line);
  return out;
}
export function replyLines(text, cols = (process.stdout.columns || 100)) {
  const w = Math.max(20, cols), out = [];
  let fence = false;
  for (const raw of String(text).trim().replace(/\r/g, '').split('\n')) {
    const lead = out.length ? '  ' : '● ';
    if (/^\s*```/.test(raw)) { fence = !fence; if (!out.length) out.push('●'); continue; }
    if (fence) { out.push(lead + raw); continue; }
    if (!raw.trim()) { out.push(''); continue; }
    const h = raw.match(/^#{1,6}\s+(.*)$/);
    if (h) { out.push(...wrapped(`\x1b[1m${inlineMd(h[1])}\x1b[22m`, lead, '  ', w)); continue; }
    const li = raw.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
    if (li) {
      const mark = `${lead}${li[1]}${/\d/.test(li[2]) ? li[2] : '-'} `;
      out.push(...wrapped(inlineMd(li[3]), mark, ' '.repeat(visible(mark)), w));
      continue;
    }
    out.push(...wrapped(inlineMd(raw), lead, '  ', w));
  }
  return out.join('\n');
}
// F483: the dim line after a chat turn, as Claude Code words it: '✻ Worked for 12s · done 14:03'
export function doneLine(ms, at = new Date()) {
  const s = Math.max(1, Math.round(ms / 1000));
  const took = s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
  const hm = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
  return `\x1b[2m✻ Worked for ${took} · done ${hm}\x1b[22m`;
}

function redrawn(out) {
  let kept = '', due = null;
  const write = out.write.bind(out);
  out.write = (s, ...more) => {
    kept = (kept + String(s)).slice(-SCREEN);
    return write(s, ...more);
  };
  out.on('resize', () => {
    clearTimeout(due);
    due = setTimeout(() => {
      const cut = kept.length === SCREEN ? kept.slice(kept.indexOf('\n') + 1) : kept; // from a whole line on
      write(`\x1b[H\x1b[2J\x1b[3J${cut}`);
    }, 120);
  });
}

// what a resumed chat's terminal starts with: the words of its last messages
function recap(messages) {
  for (const m of messages.slice(-60)) {
    const said = m.role === 'toolResult' ? '' : textOf(m.content).trim();
    if (said.startsWith('[Request interrupted')) console.log('harness: interrupted');
    else if (said) console.log(m.role === 'user' ? saidLines(said) : replyLines(said));
  }
}

// --- images (F406g) ------------------------------------------------------------------------------------------------

const IMAGE_MAX = 5 * 1024 * 1024;

// what image the bytes are, '' for none a model takes
function imageType(data) {
  const at = (from, to) => data.subarray(from, to).toString('latin1');
  if (at(0, 8) === '\x89PNG\r\n\x1a\n') return 'image/png';
  if (at(0, 3) === '\xff\xd8\xff') return 'image/jpeg';
  if (at(0, 4) === 'GIF8') return 'image/gif';
  if (at(0, 4) === 'RIFF' && at(8, 12) === 'WEBP') return 'image/webp';
  return '';
}

// the messages as the provider gets them: an image is kept as its path, so the transcript stays small
function withImages(messages) {
  return messages.map((m) => (!Array.isArray(m.content) || !m.content.some((b) => b?.type === 'image' && b.path) ? m :
    { ...m, content: m.content.map((b) => {
      if (b?.type !== 'image' || !b.path) return b;
      try { return { type: 'image', mimeType: b.mimeType, data: fs.readFileSync(b.path).toString('base64') }; } catch {
        return { type: 'text', text: `(the image ${b.path} is gone)` };
      }
    }) }));
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
  // F501 (issue #9): a Pi session writes auth.json in place, so a read can catch it empty or half written; that
  // read seemed to say "no login" and a resumed session failed with "Provider is not configured". A missing file
  // is no logins; an unreadable one is read again for a few seconds, then said as the error it is.
  const all = () => {
    const end = Date.now() + 5000;
    for (;;) {
      let text;
      try { text = fs.readFileSync(file, 'utf8'); } catch (e) { if (e.code === 'ENOENT') return {}; text = null; }
      if (text !== null) { try { return JSON.parse(text); } catch {} }
      if (Date.now() > end) throw new Error(`harness: ${file} cannot be read as JSON; log in again with \`pi\` /login`);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    }
  };
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
  // F506: a named login (`run login <provider> --as NAME`) is kept beside the default one, under `<id>@<NAME>`;
  // AGENT_RUNNER_LOGIN_AS names the login this session (or login) uses, none the default
  const as = process.env.AGENT_RUNNER_LOGIN_AS || '';
  const key = (id) => (as ? `${id}@${as}` : id);
  const own = (k) => (as ? k.endsWith(`@${as}`) : !k.includes('@'));
  return {
    async read(id) { return all()[key(id)]; },
    async list() {
      return Object.entries(all()).filter(([k]) => own(k))
        .map(([k, c]) => ({ providerId: as ? k.slice(0, -as.length - 1) : k, type: c?.type }));
    },
    modify(id0, fn) {
      const id = key(id0);
      const run = chain.then(async () => {
        const unlock = await lock();
        try {
          const data = all();
          const next = await fn(data[id]);
          // undefined says no change (B771: another session refreshed the token first); only delete() removes a login
          if (next === undefined || JSON.stringify(next) === JSON.stringify(data[id])) return data[id];
          data[id] = next;
          save(data);
          return next;
        } finally { unlock(); }
      });
      chain = run.catch(() => {});
      return run;
    },
    async delete(id) { const data = all(); delete data[key(id)]; save(data); },
  };
}

// B862: Pi sends thinking {type:'disabled'} when its model data does not say "off" is unsupported (off: null), and
// Claude models with adaptive thinking only (Copilot's claude-sonnet-5.5 in Pi 1.6.0's data) refuse that with a 400.
// Such a model sends no thinking field then, as Pi already does for claude-opus-5.5, so the API's default applies.
export function thinkingOff(model) {
  if (model?.api !== 'anthropic-messages' || !model.reasoning || model.compat?.forceAdaptiveThinking !== true) return model;
  if (model.thinkingLevelMap?.off === null) return model;
  return { ...model, thinkingLevelMap: { ...(model.thinkingLevelMap || {}), off: null } };
}

function plainModel(id, provider, api, baseUrl) {
  return { id, name: id, api, provider, baseUrl, reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 16384 };
}

// --- Copilot on a GitHub Enterprise domain (F406b) ---
// Pi's login package signs in and refreshes on the stored enterpriseUrl, but takes the address of the model list and
// the model calls from the token (its proxy-ep), which can name githubcopilot.com. With a domain stored, an address
// off that domain is the domain's own Copilot address instead.

// the host of a domain as a person writes it (https://company.ghe.com/ too), '' when there is none
function enterpriseHost(text) {
  const t = typeof text === 'string' ? text.trim() : '';
  if (!t) return '';
  try {
    const host = new URL(t.includes('://') ? t : `https://${t}`).hostname;
    return host === 'github.com' ? '' : host; // typed for the blank: no Enterprise domain
  } catch { return ''; }
}

function onDomain(url, host) {
  const u = new URL(url);
  if (u.hostname !== host && !u.hostname.endsWith(`.${host}`)) u.host = `copilot-api.${host}`;
  return u.href.replace(/\/$/, '');
}

// run `fn` with each fetch it makes kept on `host()`; '' (github.com) changes none
async function keptOnDomain(host, fn) {
  const real = globalThis.fetch;
  globalThis.fetch = (url, init) => real(host() ? onDomain(String(url), host()) : url, init);
  try { return await fn(); } finally { globalThis.fetch = real; }
}

function enterpriseOAuth(oauth) {
  return { ...oauth,
    login(io, options) {
      let host = '';
      const prompt = async (p) => {
        const answer = await io.prompt(p);
        if (p.type !== 'select' && /enterprise/i.test(p.message || '')) host = enterpriseHost(answer);
        return answer;
      };
      return keptOnDomain(() => host, () => oauth.login({ ...io, prompt }, options));
    },
    refresh(credential, signal) {
      const host = enterpriseHost(credential.enterpriseUrl);
      return keptOnDomain(() => host, () => oauth.refresh(credential, signal));
    },
    async toAuth(credential) {
      const auth = await oauth.toAuth(credential), host = enterpriseHost(credential.enterpriseUrl);
      return host ? { ...auth, baseUrl: onDomain(auth.baseUrl, host) } : auth;
    } };
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
    let list = models.getModels(id);
    if (id === PROVIDER_IDS.copilot) {
      const p = models.getProvider(id);
      models.setProvider({ ...p, auth: { ...p.auth, oauth: enterpriseOAuth(p.auth.oauth) } });
      if (enterpriseHost((await credentials.read(id))?.enterpriseUrl)) { // the models that domain lists for the account
        try { await models.getAuth(id); } catch { /* a refresh that fails is said by the model call, which tries again */ }
        list = await models.getAvailable(id);
      }
    }
    model = list.find((m) => m.id === modelId);
    if (!model) {
      const known = list.map((m) => m.id);
      throw new Error(`harness: ${name} (${id}) has no model ${modelId}; it has: ${known.join(', ') || 'none'}`);
    }
  }
  model = thinkingOff(model);
  return { call: (context, signal) => models.completeSimple(model, context, { signal }) };
}

// F506: the login the runner named for this session (login.harness_env), kept as a fallback model names none
const LOGIN_GIVEN = process.env.AGENT_RUNNER_LOGIN_AS || '';

async function loadProvider(spec, custom) {
  const at = spec.indexOf(':');
  let provider = at < 0 ? spec : spec.slice(0, at), model = at < 0 ? '' : spec.slice(at + 1);
  // F506: `<provider>@<login>:<model>` runs on that login (`run login <provider> --as <login>`), else the default one
  const login = provider.includes('@') ? provider.slice(provider.indexOf('@') + 1) : LOGIN_GIVEN;
  if (provider.includes('@')) provider = provider.slice(0, provider.indexOf('@'));
  if (login) process.env.AGENT_RUNNER_LOGIN_AS = login; else delete process.env.AGENT_RUNNER_LOGIN_AS;
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
  { name: 'read', description: `Read a text file: its lines numbered, ${READ_LINES} from offset (1-based) unless limit says otherwise. ` +
      'An image (PNG, JPEG, GIF, WebP) is shown to you, when your model takes images.',
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
      'written to a file under the run\'s notes, the run page shows it, and it is published to claude.ai when Claude Code is here: its URL ' +
      'comes back, else the run page has it (recorded for `done`, which takes it as a concept\'s page). The same as `run publish-page <file>`.',
    parameters: { type: 'object', properties: { name: { type: 'string', description: 'a short file name' },
      html: { type: 'string' } }, required: ['name', 'html'] } },
];

const CHAT_TOOLS = ['bash', 'read', 'edit', 'write', 'publish_page'];

// the tool calls the git fence reads, as Claude Code's (tools.FENCE_TOOLS)
const FENCED = { bash: (a) => ['Bash', { command: a.command || '' }], edit: (a) => ['Edit', { file_path: a.path }],
  write: (a) => ['Write', { file_path: a.path }] };

function clip(text) {
  if (text.length <= OUTPUT_MAX) return text;
  const head = Math.floor(OUTPUT_MAX / 3);
  return `${text.slice(0, head)}\n\n[... ${text.length - OUTPUT_MAX} characters cut ...]\n\n${text.slice(-(OUTPUT_MAX - head))}`;
}

const RUNNING = new Set(); // the tools' processes, ended with a chat
const STOPPED = 130;

function killTree(p) {
  if (process.platform === 'win32') { // no process groups: taskkill ends the tree; a child it missed must not hold the call
    if (p.job) p.kill(); // B798: it alone, or it could see its command end first and let go of the rest
    else if (p.pid) spawnSync('taskkill', ['/T', '/F', '/PID', String(p.pid)], { stdio: 'ignore', windowsHide: true });
    p.stdout?.destroy();
    p.stderr?.destroy();
    return;
  }
  try { process.kill(-p.pid, 'SIGKILL'); } catch { try { p.kill('SIGKILL'); } catch {} }
}

const NO_JOB = 47798; // job_object.py's: no job could be made, and the command was not started

// B798: `argv` in a Windows job object (job_object.py, on the runner's Python), so a stop ends the Git Bash children
// too, whose parent is gone and taskkill misses
async function runInJob(argv, python, cwd, timeout, signal) {
  if (process.platform === 'win32' && python) {
    const r = await run([python, '-I', '-S', fileURLToPath(new URL('job_object.py', import.meta.url)), ...argv],
      cwd, '', timeout, signal, true);
    if (r.code !== NO_JOB) return r;
  }
  return run(argv, cwd, '', timeout, signal);
}

function run(argv, cwd, input, timeout, signal, job = false) {
  return new Promise((resolve) => {
    const p = spawn(argv[0], argv.slice(1), { cwd, env: process.env, detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '', timedOut = false;
    p.job = job;
    RUNNING.add(p);
    const t = setTimeout(() => {
      timedOut = true;
      killTree(p);
    }, timeout * 1000);
    const stop = () => killTree(p);
    if (signal?.aborted) stop();
    signal?.addEventListener('abort', stop, { once: true });
    const over = () => { clearTimeout(t); RUNNING.delete(p); signal?.removeEventListener('abort', stop); };
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { out += d; });
    p.on('error', (e) => { over(); resolve({ code: 127, out: String(e) }); });
    p.on('close', (code) => { over(); resolve({ code: timedOut ? 124 : signal?.aborted ? STOPPED : code, out, timedOut }); });
    p.stdin.on('error', () => {});
    p.stdin.end(input || '');
  });
}

class Session {
  constructor(a, cwd) {
    this.a = a;
    this.cwd = cwd;
    this.ended = '';
    this.ctl = null; // F406f: the turn under way's AbortController, which a chat's Escape stops
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
    if (this.a.tools && !this.a.tools.includes(name)) return [`${name} is not a tool of this session`, true];
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
    const r = await runInJob(['bash', '-c', String(a.command || '')], this.a.runner?.[0], this.cwd, timeout, this.ctl?.signal);
    const tail = r.timedOut ? `\n[timed out after ${timeout} s; the command was killed]` :
      r.code ? `\n[exit code ${r.code}]` : '';
    return [clip(r.out) + tail || '(no output)', Boolean(r.code)];
  }

  async tool_read(a) {
    const f = this.resolve(a.path);
    const data = fs.readFileSync(f);
    const mimeType = imageType(data);
    if (mimeType && data.length > IMAGE_MAX) return [`${f} is an image of ${Math.ceil(data.length / 1024 / 1024)} MB: one over ${IMAGE_MAX / 1024 / 1024} MB cannot be shown`, true];
    if (mimeType) return [`${f} (${mimeType})`, false, { type: 'image', mimeType, path: f }];
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

  // B155: a slot's task, and neither `done` nor `done --blocked` has succeeded (config.finished_mark)
  undone() {
    const slot = process.env.AGENT_RUNNER_SLOT;
    return Boolean(slot && this.tid && !fs.existsSync(path.join(this.a.notes, `slot${slot}.finished`)));
  }

  async tool_finish(a) {
    if (this.undone()) {
      const quoted = (w) => (/^[\w@%+=:,./-]+$/.test(w) ? w : `'${w.replaceAll("'", `'\\''`)}'`);
      const done = `${(this.a.runner || ['run']).map(quoted).join(' ')} done ${this.tid} "<commit message>"`;
      return [`finish refused: \`done\` has not run for ${this.tid}, so the session goes on. Run \`${done}\` with bash ` +
        `first (add --blocked "<why + what would unblock it>" when you are stuck), then finish. When only a person ` +
        `can answer what you need, call the ask tool instead.`, true];
    }
    return this.runner('finish', a.summary);
  }

  async tool_ask(a) { return this.runner('ask', a.question); }

  async tool_publish_page(a) {
    const name = String(a.name || 'page').replace(/\.html?$/i, '').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80) || 'page';
    const f = path.join(this.a.notes, 'harness-pages', this.tid || this.a.sid, `${name}.html`);
    const denied = await this.fence('write', { path: f });
    if (denied) return [denied, true];
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, String(a.html ?? ''));
    // F106f: `run publish-page` copies it where the run page shows it and publishes it to claude.ai (a one-shot
    // of up to 300 s), printing the URL and recording it for `done`
    if (!this.a.runner) return [`page written to ${f}; no runner command was given, so it is not published`, true];
    // a chat has no task: its page gets an id of its own, the same each time it publishes that name
    const id = this.a.chat && !this.tid ? ['--id', `chat1${crypto.createHash('md5').update(`${this.a.sid}/${name}`).digest('hex').slice(0, 8)}`] : [];
    const r = await run([...this.a.runner, 'publish-page', f, ...id], this.cwd, '', 420, this.ctl?.signal);
    return [`page written to ${f}\n${r.out.trim() || `publish-page failed (exit code ${r.code})`}`, Boolean(r.code)];
  }
}

// --- the loop -------------------------------------------------------------------------------------------------

const SYSTEM = `You are an unattended coding agent that agent-runner started in a git worktree; nobody watches ` +
  `this session live. Do the task in the first message with your tools: bash, read, edit, write, and finish when ` +
  `you are done, ask when only a person can answer, publish_page to show the person a page. Paths are relative ` +
  `to the worktree. A message that arrives while you work is the person telling you something: take it into ` +
  `account. When the task's brief names \`run finish\` or \`run ask\`, the finish and ask tools do the same.`;

// F406e: a one-shot with --tools: no task of its own, so nothing of finish, ask or a worktree to change
const ONE_SHOT = `You answer one message, unattended: nobody can reply. Use only the tools you are given, change nothing, ` +
  `and end with your whole answer as text.`;

// F406f: a control session; what it is for is in the control brief (--system-file)
const CHAT = `You are in a conversation with a person, in the main checkout of a git repository. Answer each message, ` +
  `using your tools (bash, read, edit, write, publish_page) as the brief below says, then stop: the person's next ` +
  `message comes when they send it. Paths are relative to the checkout. A message that names a file the person attached ` +
  `means that file: read it before you answer, an image too.`;

// F464: a run of tool calls on screen is one collapsed line, as Claude Code draws it: 'Ran 3 shell commands, read 2 files'
const TALLY = { bash: ['Ran', 'shell command'], read: ['Read', 'file'], edit: ['Edited', 'file'], write: ['Wrote', 'file'],
  publish_page: ['Published', 'page'] };
export function tallyLine(counts) {
  const parts = Object.entries(counts).map(([name, n]) => {
    const [verb, noun] = TALLY[name] || ['Called', name];
    return TALLY[name] ? `${verb} ${n} ${noun}${n === 1 ? '' : 's'}` : `${verb} ${noun}${n === 1 ? '' : ` ${n} times`}`;
  });
  return parts.map((p, i) => (i ? p[0].toLowerCase() + p.slice(1) : p)).join(', ');
}

// the tally of the run of tool calls going on now: counted up live on a terminal, said once off one
export class Tally {
  constructor(out, tty) { this.out = out; this.tty = tty; this.counts = {}; this.calls = []; this.last = []; }
  // F489: each call is kept, {tool, arg, ok, out}: ok and out once done() has its result
  add(name, args = {}) {
    this.counts[name] = (this.counts[name] || 0) + 1;
    const call = { tool: name, arg: callArg(args), ok: null, out: '' };
    this.calls.push(call);
    if (this.tty) this.out.write(`\r\x1b[2K\x1b[2m${tallyLine(this.counts)}\x1b[0m`);
    return call;
  }
  done(call, text, isError) {
    call.ok = !isError;
    call.out = String(text || '').split('\n').slice(0, CALL_LINES).join('\n');
  }
  end() {
    if (!Object.keys(this.counts).length) return;
    this.out.write(this.tty ? '\n' : `${tallyLine(this.counts)}\n`);
    this.counts = {};
    this.last = this.calls;
    this.calls = [];
  }
  // Ctrl+O: the calls of the tally going on now, or else of the last one, a line each and their output under it
  expand() {
    const calls = this.calls.length ? this.calls : this.last;
    if (!calls.length) return;
    const live = this.calls.length && this.tty;
    this.out.write(`${this.tty ? '\r\x1b[2K' : ''}${callLines(calls)}\n`);
    if (live) this.out.write(`\x1b[2m${tallyLine(this.counts)}\x1b[0m`);
  }
}

const CALL_LINES = 5; // the lines of a call's output it keeps
// a call's argument as Claude Code words it: the command, the path
export function callArg(args) {
  const a = args && typeof args === 'object' ? args : {};
  const v = ['command', 'path', 'file_path', 'name', 'title'].map((k) => a[k]).find((x) => typeof x === 'string' && x.trim())
    ?? Object.values(a).find((x) => typeof x === 'string' && x.trim()) ?? '';
  return v.trim();
}
export function callLines(calls) {
  return calls.map((c) => {
    const name = c.tool.charAt(0).toUpperCase() + c.tool.slice(1);
    const mark = c.ok === false ? '\x1b[31m●\x1b[0m' : c.ok ? '\x1b[32m●\x1b[0m' : '●';
    const out = c.out ? `\n${c.out.split('\n').map((l, i) => `${i ? '     ' : '  ⎿  '}${l}`).join('\n')}` : '';
    return `${mark} ${name}(${c.arg.split('\n')[0]})${c.ok === false ? ' failed' : ''}${out}`;
  }).join('\n');
}

function overBudget(a, tokens, usd) {
  const tok = tokens >= 1e6 ? `${(tokens / 1e6).toFixed(1)}M` : `${Math.round(tokens / 1e3)}k`;
  const spent = `${tok} tok $${usd.toFixed(2)}`;
  if (a.taskTokens && tokens >= a.taskTokens) return `${spent} is past [run] task_tokens (${a.taskTokens.toLocaleString('en-US')})`;
  if (a.taskUsd && usd >= a.taskUsd) return `${spent} is past [run] task_usd ($${a.taskUsd.toFixed(2)})`;
  return '';
}

// `p`, or undefined as soon as `signal` aborts
function stoppable(signal, p) {
  if (!signal) return p;
  return Promise.race([p, new Promise((resolve) => {
    if (signal.aborted) resolve();
    signal.addEventListener('abort', () => resolve(), { once: true });
  })]);
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const tally = new Tally(process.stdout, process.stdout.isTTY);
  const log = console.log; // any other line ends the run of tool calls first
  console.log = (...x) => { tally.end(); log(...x); };
  process.on('exit', () => tally.end());
  const cwd = process.cwd();
  const file = path.join(a.notes, 'harness-sessions', `${a.sid}.jsonl`);
  if (a.resume && !fs.existsSync(file)) throw new Error(`harness: session ${a.sid} has no transcript at ${file}`);
  if (!a.resume && fs.existsSync(file) && !(a.chat && !fs.statSync(file).size)) throw new Error(`harness: session ${a.sid} exists already (${file}); --resume it`);
  const t = new Transcript(file, a.sid, cwd);
  let { messages, tokens, usd } = t.load();
  const system = [a.chat ? CHAT : a.tools ? ONE_SHOT : SYSTEM, a.systemFile && fs.existsSync(a.systemFile) ? fs.readFileSync(a.systemFile, 'utf8') : '']
    .filter(Boolean).join('\n\n');
  const prompt = a.promptFile ? fs.readFileSync(a.promptFile, 'utf8') : '';
  const s = new Session(a, cwd);
  const quit = (code) => {
    for (const p of RUNNING) killTree(p);
    if (process.stdout.isTTY) process.stdout.write('\x1b[?2004l');
    process.exit(code);
  };
  if (a.chat && process.stdout.isTTY) redrawn(process.stdout); // F406g
  const tells = new Tells(process.stdin, a.chat ? { end: () => quit(0), expand: () => tally.expand(),
    interrupt: () => { const going = Boolean(s.ctl && !s.ctl.signal.aborted); s.ctl?.abort(); return going; } } : null);
  if (a.chat) for (const sig of ['SIGTERM', 'SIGHUP']) process.on(sig, () => quit(0));
  const now = a.chat ? new Now(a) : null; // F406g
  const is = (status) => now?.set(status, tells.queue);
  tells.changed = () => is(now?.d.status);
  is(prompt.trim() ? 'busy' : 'idle');
  let provider = await loadProvider(a.model, a.provider);
  console.log(`harness: ${a.resume ? 'resumed' : 'started'} session ${a.sid} on ${a.model} in ${cwd}`);
  if (a.chat && a.resume) recap(messages);
  const pending = prompt.trim() ? [prompt] : [];
  const stopped = () => { // as Claude Code words it, so the transcript's readers know it
    messages.push(t.user('[Request interrupted by user]'));
    console.log('harness: interrupted');
  };
  let failures = 0, peak = t.peak(), over = a.chat, turnStart = Date.now(); // over: a chat's turn is done (or none has begun)
  for (;;) {
    if (over && !pending.length) {
      s.ctl = null;
      if (!tells.queue.length) is('idle');
      if (!(await tells.wait(Infinity))) return 0;
      if (tells.queue.some((x) => x === '/exit' || x === '/quit')) return 0;
    }
    if (a.chat && (over || !s.ctl)) s.ctl = new AbortController();
    if (over) turnStart = Date.now();
    over = false;
    is('busy');
    for (const text of pending.splice(0)) {
      messages.push(t.user(text));
      console.log(saidLines(text));
    }
    for (const text of tells.take()) { // B865: the raw echo was erased at Enter; the tell shows as saidLines
      messages.push(t.user(text));
      console.log(saidLines(text));
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
      const context = { systemPrompt: system, messages: withImages(messages),
        tools: a.tools ? TOOLS.filter((x) => a.tools.includes(x.name)) : TOOLS };
      m = await stoppable(s.ctl?.signal, provider.call(context, s.ctl?.signal));
    } catch (e) {
      m = { role: 'assistant', content: [], stopReason: 'error', errorMessage: String(e?.message || e), model: a.model,
        timestamp: Date.now() };
    }
    if (s.ctl?.signal.aborted) {
      stopped();
      over = true;
      continue;
    }
    if (m.stopReason === 'error' && transientError(m.errorMessage || '') && failures < RETRIES) {
      failures++;
      console.log(`harness: the model call failed (${m.errorMessage}); trying again (${failures}/${RETRIES})`);
      await stoppable(s.ctl?.signal, new Promise((r) => setTimeout(r, 5000 * 2 ** failures)));
      continue;
    }
    if (m.stopReason === 'error' && capError(m.errorMessage || '') && a.fallback.length) {
      // F106g: the provider hit its cap: the same session goes on with the chain's next model
      const was = a.model;
      let next = null;
      while (!next && a.fallback.length) { // an entry that will not load is passed over for the one after it
        const c = a.fallback.shift();
        try {
          provider = await loadProvider(c.model, c.provider);
          next = c;
        } catch (e) {
          console.log(`harness: cannot switch to ${c.model}: ${e?.message || e}`);
        }
      }
      if (!next) {
        t.assistant(m);
        console.log(`harness: the model call failed: ${m.errorMessage}; no model in --fallback could be loaded`);
        if (!a.chat) return 1;
        over = true;
        continue;
      }
      markCapped(a.notes, was.split(':')[0]);
      a.model = next.model;
      try { fs.writeFileSync(path.join(a.notes, `${a.sid}.model`), a.model); } catch { /* status only */ }
      t.note(`${was} hit its cap (${m.errorMessage}); the session goes on with ${a.model}, the next in [models] fallback`);
      console.log(`harness: ${was} hit its cap (${m.errorMessage}); going on with ${a.model}`);
      failures = 0;
      continue;
    }
    failures = 0;
    t.assistant(m);
    const [dt, du] = turnSpend(claudeUsage(m.usage), m.model);
    tokens += dt; usd += du;
    peak = Math.max(peak, contextOf(claudeUsage(m.usage)));
    if (m.stopReason === 'error' || m.stopReason === 'aborted') {
      console.log(`harness: the model call failed: ${m.errorMessage || m.stopReason}`);
      if (!a.chat) return 1;
      over = true; // the person sees it, and their next message is tried
      continue;
    }
    messages.push(m);
    const said = textOf(m.content.filter((b) => b.type === 'text'));
    if (said) console.log(a.chat ? replyLines(said) : said);
    const calls = m.content.filter((b) => b.type === 'toolCall');
    for (const c of calls) {
      const kept = tally.add(c.name, c.arguments);
      const [text, isError, image] = s.ctl?.signal.aborted ? ['The person interrupted before this tool call ran; it did not run.', true] : c.argumentsError ? [c.argumentsError, true] : await s.call(c.name, c.arguments);
      tally.done(kept, text, isError);
      messages.push(t.toolResult(c, text, isError, image));
      if (!s.ended) s.ended = s.endedNow();
    }
    if (s.ctl?.signal.aborted) {
      stopped();
      over = true;
      continue;
    }
    if (s.ended) {
      console.log(`harness: the session ended (${s.ended})`);
      return 0;
    }
    if (calls.length) continue;
    if (a.once) return 0;
    if (a.chat) {
      console.log(doneLine(Date.now() - turnStart));
      over = true;
      continue;
    }
    const full = path.join(a.notes, `${a.sid}.full`); // F177: said once, at a turn's end (watch.full_message)
    if (a.contextWarn && Math.floor(peak / 1000) > a.contextWarn && s.undone() && !/^[KV]\d/.test(s.tid) && !fs.existsSync(full)) {
      fs.writeFileSync(full, `${Math.floor(peak / 1000)}\n`);
      pending.push(a.contextText.replaceAll('{tid}', s.tid).replaceAll('{peak}', String(Math.floor(peak / 1000))));
      continue;
    }
    if (!(await tells.wait(a.idle))) {
      console.log(`harness: ${a.idle} s at the prompt with nothing told: the session ends`);
      return 0;
    }
  }
}

// --- run login (F106e) ----------------------------------------------------------------------------------------
// `harness.mjs --login <provider> [--provider <json>] [--enterprise <domain>]`: one login through Pi's login
// package, kept in Pi's auth.json as Pi keeps it (so the harness loop and Pi both use it). Copilot and Codex sign
// in by OAuth (a device code, a browser page); Gemini and a custom provider take an API key. It talks to
// `run login` (agent_runner/login.py) in JSON lines on stdout: {"say": text}, {"ask": prompt} (answered by one
// line {"answer": text} on stdin), {"saved": id, "file": path}. --enterprise answers the package's GitHub
// Enterprise question with what the person gave run login ('' is github.com). AGENT_RUNNER_HARNESS_LOGIN, a
// module path, stands in for the package (the tests' fake): its default export `({id, custom}) -> auth`, auth
// being {oauth?: {login(interaction)}, apiKey?: {login(interaction)}}.

async function loginAuth(id, custom) {
  if (process.env.AGENT_RUNNER_HARNESS_LOGIN) {
    const mod = await import(pathToFileURL(path.resolve(process.env.AGENT_RUNNER_HARNESS_LOGIN)).href);
    return mod.default({ id, custom });
  }
  const ai = await piAi('index');
  if (custom) return { apiKey: ai.envApiKeyAuth(`${id} API key`, custom.key_env ? [custom.key_env] : []) };
  const p = (await piAi('providers/all')).builtinProviders().find((x) => x.id === id);
  if (!p) throw new Error(`harness: Pi's login package has no provider ${id}`);
  return id === PROVIDER_IDS.copilot ? { ...p.auth, oauth: enterpriseOAuth(p.auth.oauth) } : p.auth;
}

async function login(argv) {
  const name = argv[0] || '';
  let custom = null, enterprise = null;
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === '--provider') custom = JSON.parse(argv[++i]);
    else if (argv[i] === '--enterprise') enterprise = argv[++i] ?? '';
    else if (argv[i] === '--as') process.env.AGENT_RUNNER_LOGIN_AS = argv[++i] || ''; // F506: a named login

    else throw new Error(`harness: --login: unknown argument ${argv[i]}`);
  }
  if (!name) throw new Error('harness: --login names no provider');
  const id = custom ? name : PROVIDER_IDS[name] || name;
  const out = (o) => process.stdout.write(`${JSON.stringify(o)}\n`);
  const lines = [];
  let waiter = null, buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (d) => {
    buf += d;
    for (let at; (at = buf.indexOf('\n')) >= 0; buf = buf.slice(at + 1)) {
      lines.push(buf.slice(0, at));
      if (waiter) { const w = waiter; waiter = null; w(); }
    }
  });
  const nextLine = async () => {
    while (!lines.length) await new Promise((r) => { waiter = r; });
    return lines.shift();
  };
  const interaction = {
    signal: new AbortController().signal,
    async prompt(p) {
      if (enterprise !== null && p.type !== 'select' && /enterprise/i.test(p.message || '')) return enterprise;
      out({ ask: { type: p.type, message: p.message, placeholder: p.placeholder || '',
        options: (p.options || []).map((o) => ({ id: o.id, label: o.label })) } });
      const answer = JSON.parse(await nextLine()).answer;
      if (answer === undefined || answer === null) throw new Error('harness: login cancelled');
      return answer;
    },
    notify(e) {
      if (e.type === 'auth_url') out({ say: `Open this page in your browser:\n${e.url}${e.instructions ? `\n${e.instructions}` : ''}` });
      else if (e.type === 'device_code') out({ say: `Open ${e.verificationUri} and enter the code ${e.userCode}` });
      else if (e.message) out({ say: e.message });
    },
  };
  const auth = await loginAuth(id, custom);
  let credential;
  if (auth.oauth) credential = await auth.oauth.login(interaction, { getDeviceId: () => crypto.randomUUID() });
  else if (auth.apiKey?.login) credential = await auth.apiKey.login(interaction);
  else throw new Error(`harness: ${name} (${id}) has no login in Pi's login package`);
  if (!credential) throw new Error(`harness: the ${name} login gave no credential`);
  const dir = process.env.PI_CODING_AGENT_DIR || path.join(os.homedir(), '.pi', 'agent');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  await piCredentials().modify(id, async () => credential);
  const as = process.env.AGENT_RUNNER_LOGIN_AS;
  out({ saved: as ? `${id}@${as}` : id, file: path.join(dir, 'auth.json') });
  process.stdin.pause();
  return 0;
}

(process.argv[2] === '--login' ? login(process.argv.slice(3)) : main()).then((code) => process.exit(code), (e) => {
  console.error(e?.message || e);
  process.exit(2);
});
