// Newly — Electron-hoofdproces.
// Chromium doet de rendering; dit is de schil met tabs, adresbalk en de
// CDP-agenthook: de agent stuurt straks DevTools-commando's naar een tab.
const { app, BrowserWindow, WebContentsView, ipcMain } = require('electron');
const path = require('path');

let win;
let tabs = [];        // { view, title, url }
let active = -1;
const TOP_UI = 64;    // hoogte van de eigen UI-balk

function contentBounds() {
  const [w, h] = win.getContentSize();
  return { x: 0, y: TOP_UI, width: w, height: Math.max(0, h - TOP_UI) };
}

function sendInfo(i) {
  if (i < 0 || i >= tabs.length) return;
  win.webContents.send('tab:info', {
    i: i, title: tabs[i].title, url: tabs[i].url, count: tabs.length, active: active
  });
}

function createTab(url) {
  const view = new WebContentsView({ webPreferences: { contextIsolation: true, sandbox: true } });
  tabs.push({ view: view, title: url || 'Nieuwe tab', url: url || '' });
  const i = tabs.length - 1;
  // Agenthook: attach CDP zodat de MCP-server (fase 3) commando's kan sturen.
  try { view.webContents.debugger.attach('1.3'); } catch (e) { /* al attached */ }
  view.webContents.on('page-title-updated', function (e, title) { tabs[i].title = title; sendInfo(i); });
  view.webContents.on('did-navigate', function (e, u) { tabs[i].url = u; sendInfo(i); });
  view.webContents.on('did-navigate-in-page', function (e, u) { tabs[i].url = u; sendInfo(i); });
  if (url) view.webContents.loadURL(url);
  setActive(i);
  return i;
}

function setActive(i) {
  if (i < 0 || i >= tabs.length) return;
  if (active >= 0 && tabs[active]) win.contentView.removeChildView(tabs[active].view);
  active = i;
  win.contentView.addChildView(tabs[i].view);
  tabs[i].view.setBounds(contentBounds());
  sendInfo(i);
}

function closeTab(i) {
  if (i < 0 || i >= tabs.length || tabs.length === 1) return;
  const wasActive = (i === active);
  win.contentView.removeChildView(tabs[i].view);
  tabs.splice(i, 1);
  active = -1;
  setActive(wasActive ? Math.max(0, i - 1) : Math.min(i, tabs.length - 1));
}

app.whenReady().then(function () {
  win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 800, minHeight: 500,
    webPreferences: { preload: path.join(__dirname, 'preload.js') }
  });
  win.loadFile(path.join(__dirname, 'index.html'));
  win.on('resize', function () {
    if (active >= 0 && tabs[active]) tabs[active].view.setBounds(contentBounds());
  });
  createTab('https://example.com');
});

ipcMain.handle('tab:new', function (e, url) { return createTab(url || null); });
ipcMain.handle('tab:activate', function (e, i) { setActive(i); });
ipcMain.handle('tab:close', function (e, i) { closeTab(i); });
ipcMain.handle('tab:navigate', function (e, url) {
  if (active >= 0 && url) tabs[active].view.webContents.loadURL(url);
});
// De CDP-brug voor de agent: elk DevTools-commando kan naar een tab.
ipcMain.handle('cdp:send', async function (e, i, method, params) {
  const tab = tabs[i];
  if (!tab) return { error: 'tab bestaat niet' };
  const dbg = tab.view.webContents.debugger;
  try { if (!dbg.isAttached()) dbg.attach('1.3'); } catch (err) {}
  try { return await dbg.sendCommand(method, params || {}); }
  catch (err) { return { error: String(err) }; }
});

app.on('window-all-closed', function () { app.quit(); });
