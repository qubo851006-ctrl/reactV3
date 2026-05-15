import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const read = (path) => readFileSync(join(root, path), 'utf8')

const branding = read('src/branding.ts')
const versionHistory = read('src/versionHistory.ts')
const app = read('src/App.tsx')
const sidebar = read('src/components/Sidebar.tsx')
const login = read('src/components/IdentityLogin.tsx')
const versionPanel = read('src/components/VersionPanel.tsx')

assert.match(branding, /APP_NAME\s*=\s*'法度云图'/)
assert.match(branding, /getLatestVersionLabel/)
assert.match(versionHistory, /VERSION_ENTRIES/)
assert.match(versionHistory, /version:\s*'v2\.4'/)
assert.doesNotMatch(app, /法务合规部智能体V\d/)
assert.doesNotMatch(sidebar, /法务合规部智能体V\d/)
assert.doesNotMatch(login, /法务合规部智能体 V\d/)
assert.doesNotMatch(versionPanel, /法务合规部智能体/)
assert.doesNotMatch(versionHistory, /法务合规部智能体/)
assert.match(app, /APP_TITLE/)
assert.doesNotMatch(app, /AI 驱动的企业培训与法务管理系统/)
assert.match(sidebar, /APP_TITLE/)
assert.match(login, /APP_TITLE/)
assert.match(versionPanel, /APP_NAME/)
assert.match(versionPanel, /VERSION_ENTRIES/)
