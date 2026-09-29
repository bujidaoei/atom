/**
 * Public QoderWake download center served by the production business host.
 *
 * The download center is the only sanctioned distribution surface for Desktop
 * installers: its catalog is the PostgreSQL-backed `/api/downloads/releases`
 * document and every asset resolves to an immutable COS object. Web and Desktop
 * must not link to source-hosting release pages, which carry no binaries.
 */
export const QODERWAKE_DOWNLOAD_CENTER_ORIGIN = 'https://129.204.151.235';

/** Landing page that lists the current version for every platform. */
export const QODERWAKE_DOWNLOAD_CENTER_URL = `${QODERWAKE_DOWNLOAD_CENTER_ORIGIN}/`;

/** Public release catalog consumed by the download page and Desktop update check. */
export const QODERWAKE_RELEASE_CATALOG_URL = `${QODERWAKE_DOWNLOAD_CENTER_ORIGIN}/api/downloads/releases`;

export function qoderwakeDeviceInstallCommand(platform: 'macOS' | 'Windows' | 'Linux'): string {
  return platform === 'Windows'
    ? `irm ${QODERWAKE_DOWNLOAD_CENTER_ORIGIN}/install/install.ps1 | iex`
    : `curl -fsSL ${QODERWAKE_DOWNLOAD_CENTER_ORIGIN}/install/install.sh | bash`;
}

/** Shareable per-version notes URL rendered by the download center history page. */
export function qoderwakeReleaseNotesUrl(version: string): string {
  return `${QODERWAKE_DOWNLOAD_CENTER_ORIGIN}/history.html#version=${encodeURIComponent(version)}`;
}
