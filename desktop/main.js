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
