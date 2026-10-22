const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nieuw', {
  newTab: function (url) { return ipcRenderer.invoke('tab:new', url); },
  activate: function (i) { return ipcRenderer.invoke('tab:activate', i); },
  closeTab: function (i) { return ipcRenderer.invoke('tab:close', i); },
  navigate: function (url) { return ipcRenderer.invoke('tab:navigate', url); },
  cdp: function (i, method, params) { return ipcRenderer.invoke('cdp:send', i, method, params); },
  onInfo: function (cb) { ipcRenderer.on('tab:info', function (e, info) { cb(info); }); }
});
