import { contextBridge, ipcRenderer } from 'electron'

export interface BackendProxyResult {
  status: number
  body: string
}

const api = {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node
  },
  /** 获取后端服务地址 */
  backendUrl: (): Promise<string> => ipcRenderer.invoke('backend:url'),
  /** 通过主进程转发 HTTP 请求到后端（绕过 CORS / 统一出口） */
  proxy: (method: string, path: string, body?: unknown): Promise<BackendProxyResult> =>
    ipcRenderer.invoke('backend:proxy', { method, path, body }),
  on: (channel: string, cb: (...args: unknown[]) => void): (() => void) => {
    const listener = (_e: unknown, ...args: unknown[]): void => cb(...args)
    ipcRenderer.on(channel, listener)
    return () => ipcRenderer.removeListener(channel, listener)
  }
}

contextBridge.exposeInMainWorld('electronAPI', api)

export type ElectronAPI = typeof api
