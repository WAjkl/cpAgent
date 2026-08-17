import { app, shell, BrowserWindow, ipcMain, net } from 'electron'
import { join } from 'path'

// 后端服务地址（M2 FastAPI）；默认 8766（8765 被本机 IDE 面板进程常驻占用）
const BACKEND_URL = process.env.CPAGENT_BACKEND_URL || 'http://127.0.0.1:8766'

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    title: 'cpAgent 装机顾问',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  win.on('ready-to-show', () => win.show())

  // 外部链接用系统浏览器打开
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // 开发态加载 Vite dev server，生产态加载打包产物
  if (process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// ---------- IPC 桥：转发 HTTP/SSE 到后端（3.9 扩展，此处提供基础转发） ----------
ipcMain.handle('backend:proxy', async (_e, options: { method: string; path: string; body?: unknown }) => {
  const url = `${BACKEND_URL}${options.path}`
  const resp = await net.fetch(url, {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: options.body ? JSON.stringify(options.body) : undefined
  })
  const text = await resp.text()
  return { status: resp.status, body: text }
})

ipcMain.handle('backend:url', () => BACKEND_URL)

app.whenReady().then(() => {
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
