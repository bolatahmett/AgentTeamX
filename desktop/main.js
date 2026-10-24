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

ipcMain.handle('status', async () => {
  const result = await run('python', ['team.py', 'status']);
  return { ok: result.ok, fields: parseStatus(result.output), raw: result.output, events: recentEvents(25) };
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
