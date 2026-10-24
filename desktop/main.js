// Thin shell: every action delegates to Team.ps1 / team.py. Closing the window never stops the team.
const { app, BrowserWindow, ipcMain } = require('electron');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(path.join(ROOT, 'team.json'), 'utf8'));
const PROJECT = path.resolve(ROOT, process.env.AGENT_TEAM_PROJECT || config.project);
const EVENTS = path.join(PROJECT, '.supervisor', 'team-v2', 'events.jsonl');

function run(file, args) {
  return new Promise((resolve) => {
    execFile(file, args, { cwd: ROOT, windowsHide: true, timeout: 180000, encoding: 'utf8' },
      (error, stdout, stderr) => resolve({ ok: !error, output: (stdout + stderr).trim() }));
  });
}

function teamPs1(args) {
  return run('powershell.exe', ['-NoLogo', '-NoProfile', '-File', path.join(ROOT, 'Team.ps1'), ...args]);
}

function parseStatus(text) {
  const fields = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^(\w+):\s?(.*)$/);
    if (match) fields[match[1]] = match[2];
  }
  return fields;
}

function recentEvents(limit) {
  try {
    const lines = fs.readFileSync(EVENTS, 'utf8').trim().split(/\r?\n/).slice(-limit);
    return lines.map((line) => { try { return JSON.parse(line); } catch { return null; } }).filter(Boolean).reverse();
  } catch {
    return [];
  }
}

// Same classification as dashboard.command_label: shell text becomes a fixed label.
const COMMAND_LABELS = [
  [['write_text', 'apply_patch', 'set-content', 'writefile'], 'Update source / test artifacts'],
  [['verify-project-language'], 'Project language / UTF-8 checks'],
  [['git diff --check'], 'Whitespace checks'],
  [['browser-probe', 'playwright', 'puppeteer', 'chrome', 'isolation_probe'], 'Browser journey / session isolation'],
  [['bootstrap.ps1', 'serve-loopback', 'run-probe.ps1'], 'Build/start local acceptance environment'],
  [['typecheck'], 'TypeScript checks'],
  [['lint'], 'Lint checks'],
  [['pnpm build', 'pnpm --filter @afterdark/web build', 'pnpm --filter @afterdark/api build'], 'Application build'],
  [['i18n.test'], 'Translation regression tests'],
  [['node --test', 'pnpm test', '.test.mjs', 'unittest'], 'Automated regression tests'],
  [['pnpm install', 'npm install', 'pip install'], 'Prepare local dependencies'],
  [['get-content', 'read_text', 'rg ', 'cat ', 'sed -n', 'grep '], 'Inspect source / project instructions'],
  [['git status', 'git diff', 'rev-parse', 'git log'], 'Inspect source revision / changes'],
];

function commandLabel(command) {
  const text = String(command || '').toLowerCase();
  const hit = COMMAND_LABELS.find(([needles]) => needles.some((n) => text.includes(n)));
  return hit ? hit[1] : 'Local diagnostic / tool command';
}

function toolLabel(name, input) {
  input = input || {};
  if (name === 'Bash' || name === 'PowerShell') return commandLabel(input.command);
  const file = input.file_path || input.notebook_path || input.path;
  if (file) return path.basename(String(file));
  if (input.pattern) return 'pattern';
  return '';
}

// Live worker steps from the active role log. Like dashboard.py, raw shell text is never shown.
function workerSteps(limit) {
  try {
    const runtime = path.join(PROJECT, '.supervisor', 'team-v2');
    const state = JSON.parse(fs.readFileSync(path.join(runtime, 'state.json'), 'utf8'));
    if (!state.active_role || !state.active_log) return [];
    const log = path.resolve(PROJECT, state.active_log);
    if (!log.startsWith(path.join(runtime, 'logs') + path.sep)) return [];
    const stat = fs.statSync(log);
    const size = Math.min(stat.size, 262144);
    const buffer = Buffer.alloc(size);
    const fd = fs.openSync(log, 'r');
    fs.readSync(fd, buffer, 0, size, stat.size - size);
    fs.closeSync(fd);
    const at = stat.mtime.toISOString();
    const steps = new Map();
    for (const line of buffer.toString('utf8').split(/\r?\n/)) {
      let e; try { e = JSON.parse(line); } catch { continue; }
      if (e.item && e.item.type === 'command_execution') {
        const status = e.item.status || (e.type === 'item.started' ? 'in_progress' : 'completed');
        steps.set(e.item.id || String(steps.size), { at, event: 'worker_step', role: state.active_role, tool: 'shell', step: commandLabel(e.item.command), status });
      } else if (e.type === 'assistant' && e.message && Array.isArray(e.message.content)) {
        for (const c of e.message.content) {
          if (c.type !== 'tool_use') continue;
          steps.set(c.id, { at, event: 'worker_step', role: state.active_role, tool: c.name, step: toolLabel(c.name, c.input) });
        }
      }
    }
    return [...steps.values()].slice(-limit).reverse();
  } catch {
    return [];
  }
}

ipcMain.handle('status', async () => {
  const result = await run('python', ['team.py', 'status']);
  return { ok: result.ok, fields: parseStatus(result.output), raw: result.output, steps: workerSteps(15), events: recentEvents(100) };
});

// Task board: same row grammar as dashboard.TASK_ROW. Only the header's checkbox and status token are edited.
const TASKS = path.join(PROJECT, 'tasks.md');
const ARCHIVE = path.join(PROJECT, 'docs', 'history', 'tasks-archive.md');
const TASK_ROW = /^- \[([ x])\] \*\*(T\d+[A-Z]?) - (.*?)\*\* \| (\w+) \| Dependencies: ([^.]*)\./;
const BOARD_STATUSES = ['todo', 'in_progress', 'blocked', 'done'];

function readText(file) {
  try { return fs.readFileSync(file, 'utf8').replace(/^﻿/, ''); } catch { return ''; }
}

function parseRows(text, archived) {
  const rows = [];
  const lines = text.split(/\r?\n/);
  let section = '';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith('## ')) { section = lines[i].slice(3).trim(); continue; }
    const m = lines[i].match(TASK_ROW);
    if (!m) continue;
    const body = [];
    for (let j = i + 1; j < lines.length && !TASK_ROW.test(lines[j]) && !lines[j].startsWith('## '); j++) body.push(lines[j]);
    rows.push({ id: m[2], title: m[3], status: m[4], checked: m[1] === 'x', section, archived,
      deps: m[5].split(',').map((d) => d.trim()).filter((d) => d && d.toLowerCase() !== 'none'),
      body: body.join('\n').trim() });
  }
  return rows;
}

function boardRows() {
  const live = parseRows(readText(TASKS), false).filter((r) => r.section !== 'Archived dependency references');
  const ids = new Set(live.map((r) => r.id));
  const archived = parseRows(readText(ARCHIVE), true).filter((r) => !ids.has(r.id));
  return [...live, ...archived];
}

function setTaskStatus(id, status) {
  if (!BOARD_STATUSES.includes(status) || !/^T\d+[A-Z]?$/.test(String(id))) return { ok: false, output: 'Invalid status change' };
  const raw = fs.readFileSync(TASKS, 'utf8');
  const eol = raw.includes('\r\n') ? '\r\n' : '\n';
  const lines = raw.split(/\r?\n/);
  const index = lines.findIndex((l) => { const m = l.match(TASK_ROW); return m && m[2] === id; });
  if (index < 0) return { ok: false, output: id + ' is not an open row in tasks.md (archived rows are read-only)' };
  const box = status === 'done' ? 'x' : ' ';
  lines[index] = lines[index].replace(/^- \[[ x]\]/, '- [' + box + ']').replace(/\*\* \| \w+ \|/, '** | ' + status + ' |');
  const temp = TASKS + '.board.tmp';
  fs.writeFileSync(temp, lines.join(eol), 'utf8');
  fs.renameSync(temp, TASKS);
  return { ok: true, output: id + ' -> ' + status };
}

// Agents tab: role definitions, configured engine/model, live state and recent reports per role.
const RUNTIME = path.join(PROJECT, '.supervisor', 'team-v2');

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, '')); } catch { return fallback; }
}

function roleReports(files, role, limit) {
  const suffix = new RegExp('-' + role + '-[0-9a-f]+\\.json$');
  // File names can be rewritten later than the report was recorded, so order by recorded_at.
  return files.filter((f) => suffix.test(f)).slice(-limit * 4).map((f) => {
    const data = readJson(path.join(RUNTIME, 'reports', f), {});
    const report = data.report || {};
    return { file: f, at: data.recorded_at || '', status: report.status || '', summary: report.summary || '',
      next_action: report.next_action || '', findings: Array.isArray(report.findings) ? report.findings.length : 0 };
  }).sort((a, b) => b.at.localeCompare(a.at)).slice(0, limit);
}

function agentDetails() {
  const live = readJson(path.join(ROOT, 'team.json'), config);
  const state = readJson(path.join(RUNTIME, 'state.json'), {});
  let files = [];
  try { files = fs.readdirSync(path.join(RUNTIME, 'reports')).filter((f) => f.endsWith('.json')).sort(); } catch { /* no reports yet */ }
  const events = recentEvents(800);
  let roles = [];
  try { roles = fs.readdirSync(path.join(ROOT, 'agents')).filter((d) => fs.existsSync(path.join(ROOT, 'agents', d, 'role.json'))); } catch { /* no roles */ }
  const agents = roles.map((id) => {
    const role = readJson(path.join(ROOT, 'agents', id, 'role.json'), {});
    const engine = (live.role_engines || {})[id] || live.primary_engine || 'codex';
    const model = engine === 'claude' ? ((live.claude_models || {})[id] || (live.claude_models || {}).default || {}) : ((live.role_models || {})[id] || {});
    const active = state.active_role === id;
    return {
      id, title: role.title || id, worker: !!role.worker, sandbox: (live.execution_sandboxes || {})[id] || role.sandbox || live.default_sandbox || '',
      engine: active && state.active_engine ? state.active_engine : engine,
      model: active && state.active_model ? state.active_model : model,
      write_scope: role.write_scope || [], triggers: role.triggers || [], prohibitions: role.prohibitions || [],
      active, task: active ? state.task || '' : '', steps: active ? workerSteps(25) : [],
      reports: roleReports(files, id, 5), report_count: files.filter((f) => f.includes('-' + id + '-')).length,
      events: events.filter((e) => e.role === id).slice(0, 15),
    };
  });
  agents.sort((a, b) => (b.active - a.active) || a.title.localeCompare(b.title));
  return { stage: state.stage || '', controller: state.controller_status || '', task: state.task || '', resume_role: state.resume_role || '', agents };
}

ipcMain.handle('agents', async () => agentDetails());
// The controller does not rewrite row status while it works, so the board overlays the live batch.
function liveWork() {
  const state = readJson(path.join(RUNTIME, 'state.json'), {});
  if (state.controller_status !== 'running' || !state.task) return { tasks: [], role: '', stage: '' };
  const batch = (state.delivery_batch && Array.isArray(state.delivery_batch.tasks)) ? state.delivery_batch.tasks : [];
  return { tasks: [...new Set([state.task, ...batch])], role: state.active_role || '', stage: state.stage || '' };
}

ipcMain.handle('tasks', async () => ({ statuses: BOARD_STATUSES, rows: boardRows(), live: liveWork() }));
ipcMain.handle('setStatus', async (_event, id, status) => {
  try { return setTaskStatus(id, status); } catch (error) { return { ok: false, output: String(error.message || error) }; }
});

ipcMain.handle('action', async (_event, name) => {
  if (name === 'start') return teamPs1(['-Action', 'start', '-Resume']);
  if (name === 'stop') return teamPs1(['-Action', 'stop']);
  if (name === 'retry') return run('python', ['team.py', 'retry']);
  return { ok: false, output: 'Unknown action' };
});

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1100, height: 760, title: 'AgentTeamX',
    backgroundColor: '#0f1417',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, 'index.html'));
});

app.on('window-all-closed', () => app.quit());
