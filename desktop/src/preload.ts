import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('v3Desktop', {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
  openExternal: (url: string) => ipcRenderer.invoke('desktop:open-external', url),
  showNotification: (title: string, body: string) =>
    ipcRenderer.invoke('desktop:show-notification', { title, body }),
})
