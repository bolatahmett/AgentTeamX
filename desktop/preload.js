const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('team', {
  status: () => ipcRenderer.invoke('status'),
  action: (name) => ipcRenderer.invoke('action', name),
});
