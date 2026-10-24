const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('team', {
  status: () => ipcRenderer.invoke('status'),
  action: (name) => ipcRenderer.invoke('action', name),
  tasks: () => ipcRenderer.invoke('tasks'),
  agents: () => ipcRenderer.invoke('agents'),
  setStatus: (id, status) => ipcRenderer.invoke('setStatus', id, status),
});
