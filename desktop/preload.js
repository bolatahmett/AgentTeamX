const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('team', {
  status: () => ipcRenderer.invoke('status'),
  action: (name) => ipcRenderer.invoke('action', name),
  tasks: () => ipcRenderer.invoke('tasks'),
  agents: () => ipcRenderer.invoke('agents'),
  approvals: () => ipcRenderer.invoke('approvals'),
  approvalImage: (id, file) => ipcRenderer.invoke('approvalImage', id, file),
  decide: (id, decision, comment) => ipcRenderer.invoke('decide', id, decision, comment),
  setStatus: (id, status) => ipcRenderer.invoke('setStatus', id, status),
});
