export interface VersionEntry {
  version: string
  date: string
  changes: { type: 'feat' | 'fix' | 'perf' | 'refactor'; text: string }[]
}

export const APP_NAME = '法度云图'

function versionSegments(version: string) {
  return version
    .replace(/^v/i, '')
    .split('.')
    .map(part => Number.parseInt(part, 10))
}

function compareVersions(a: string, b: string) {
  const left = versionSegments(a)
  const right = versionSegments(b)
  const length = Math.max(left.length, right.length)

  for (let i = 0; i < length; i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0)
    if (diff !== 0) return diff
  }

  return 0
}

export function getLatestVersionLabel(entries: readonly Pick<VersionEntry, 'version'>[]) {
  const latest = entries.reduce<string>(
    (current, entry) => (compareVersions(entry.version, current) > 0 ? entry.version : current),
    'v0',
  )

  return latest.replace(/^v/i, 'V')
}

export function getAppTitle(entries: readonly Pick<VersionEntry, 'version'>[]) {
  return `${APP_NAME}${getLatestVersionLabel(entries)}`
}
