import {
  app,
  BrowserWindow,
  Menu,
  Tray,
  Notification,
  dialog,
  ipcMain,
  nativeImage,
  shell,
  session,
} from 'electron'
import fs from 'node:fs'
import path from 'node:path'

interface DesktopConfig {
  serverUrl: string
  allowInvalidCertificateForHost?: string
  minimizeToTray?: boolean
  openExternalLinksInBrowser?: boolean
}

const DEFAULT_SERVER_URL = 'https://192.168.9.226:8443'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let isQuitting = false
let config: DesktopConfig = {
  serverUrl: DEFAULT_SERVER_URL,
  allowInvalidCertificateForHost: '',
  minimizeToTray: true,
  openExternalLinksInBrowser: true,
}

function readJsonConfig(filePath: string): Partial<DesktopConfig> {
  try {
    if (!fs.existsSync(filePath)) return {}
    return JSON.parse(fs.readFileSync(filePath, 'utf8')) as Partial<DesktopConfig>
  } catch (error) {
    console.warn(`Failed to read desktop config at ${filePath}:`, error)
    return {}
  }
}

function loadConfig(): DesktopConfig {
  const candidates = [
    process.env.V3_DESKTOP_CONFIG,
    path.join(process.cwd(), 'desktop.config.json'),
    path.join(path.dirname(process.execPath), 'desktop.config.json'),
  ].filter(Boolean) as string[]

  const fileConfig = candidates.reduce<Partial<DesktopConfig>>(
    (acc, filePath) => ({ ...acc, ...readJsonConfig(filePath) }),
    {},
  )

  const serverUrl = process.env.V3_DESKTOP_URL || fileConfig.serverUrl || DEFAULT_SERVER_URL
  const parsed = new URL(serverUrl)
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`Unsupported V3 server protocol: ${parsed.protocol}`)
  }

  return {
    serverUrl: parsed.toString().replace(/\/$/, ''),
    allowInvalidCertificateForHost: fileConfig.allowInvalidCertificateForHost || '',
    minimizeToTray: fileConfig.minimizeToTray ?? true,
    openExternalLinksInBrowser: fileConfig.openExternalLinksInBrowser ?? true,
  }
}

function getPreloadPath(): string {
  return path.join(__dirname, 'preload.js')
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1024,
    minHeight: 720,
    title: '法度云图 V3',
    show: false,
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  win.once('ready-to-show', () => {
    win.show()
  })

  win.on('close', (event) => {
    if (!isQuitting && config.minimizeToTray) {
      event.preventDefault()
      win.hide()
    }
  })

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (config.openExternalLinksInBrowser && !url.startsWith(config.serverUrl)) {
      shell.openExternal(url)
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })

  win.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedUrl) => {
    dialog.showMessageBox(win, {
      type: 'error',
      title: 'V3 加载失败',
      message: '无法打开 V3 服务',
      detail: `${validatedUrl}\n\n${errorCode}: ${errorDescription}`,
      buttons: ['重试', '关闭'],
    }).then(({ response }) => {
      if (response === 0) win.loadURL(config.serverUrl)
    }).catch(() => {})
  })

  win.loadURL(config.serverUrl)
  return win
}

function createTray(): void {
  const icon = nativeImage.createFromDataURL(
    'data:image/svg+xml;utf8,' +
      encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1f5eff"/><path d="M18 17h28v7H27v8h17v7H27v15h-9z" fill="white"/></svg>'),
  )
  tray = new Tray(icon)
  tray.setToolTip('法度云图 V3')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 V3', click: () => mainWindow?.show() },
    { label: '刷新', click: () => mainWindow?.reload() },
    { label: '在浏览器中打开', click: () => shell.openExternal(config.serverUrl) },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true
        app.quit()
      },
    },
  ]))
  tray.on('double-click', () => mainWindow?.show())
}

function installMenu(): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'V3',
      submenu: [
        { label: '打开 V3', click: () => mainWindow?.show() },
        { label: '刷新', accelerator: 'F5', click: () => mainWindow?.reload() },
        { label: '开发者工具', accelerator: 'Ctrl+Shift+I', click: () => mainWindow?.webContents.openDevTools() },
        { type: 'separator' },
        {
          label: '退出',
          click: () => {
            isQuitting = true
            app.quit()
          },
        },
      ],
    },
  ]))
}

function installDownloads(): void {
  session.defaultSession.on('will-download', (event, item) => {
    const suggestedName = item.getFilename()
    const saveOptions = {
      title: '保存 V3 文件',
      defaultPath: path.join(app.getPath('downloads'), suggestedName),
    }
    const targetPath = mainWindow
      ? dialog.showSaveDialogSync(mainWindow, saveOptions)
      : dialog.showSaveDialogSync(saveOptions)

    if (!targetPath) {
      event.preventDefault()
      item.cancel()
      return
    }

    item.setSavePath(targetPath)
    item.once('done', (_doneEvent, state) => {
      if (state === 'completed') {
        new Notification({
          title: '下载完成',
          body: path.basename(targetPath),
        }).show()
      }
    })
  })
}

function installIpc(): void {
  ipcMain.handle('desktop:open-external', async (_event, url: string) => {
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol)) return false
    await shell.openExternal(parsed.toString())
    return true
  })

  ipcMain.handle('desktop:show-notification', async (_event, payload: { title: string; body: string }) => {
    if (!Notification.isSupported()) return false
    new Notification({
      title: String(payload.title || 'V3'),
      body: String(payload.body || ''),
    }).show()
    return true
  })
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
  })

  app.on('certificate-error', (event, _webContents, url, _error, certificate, callback) => {
    const allowedHost = config?.allowInvalidCertificateForHost
    if (allowedHost && new URL(url).hostname === allowedHost && certificate) {
      event.preventDefault()
      callback(true)
      return
    }
    callback(false)
  })

  app.whenReady().then(() => {
    config = loadConfig()
    installMenu()
    installDownloads()
    installIpc()
    mainWindow = createWindow()
    if (config.minimizeToTray) createTray()
  }).catch((error) => {
    dialog.showErrorBox('V3 Desktop 启动失败', error instanceof Error ? error.message : String(error))
    app.quit()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow()
    else mainWindow?.show()
  })

  app.on('before-quit', () => {
    isQuitting = true
  })
}
