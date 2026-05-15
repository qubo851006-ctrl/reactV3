import { APP_NAME, getAppTitle, getLatestVersionLabel } from './branding'
import { VERSION_ENTRIES } from './versionHistory'

export { APP_NAME }

export const APP_VERSION = getLatestVersionLabel(VERSION_ENTRIES)
export const APP_TITLE = getAppTitle(VERSION_ENTRIES)
