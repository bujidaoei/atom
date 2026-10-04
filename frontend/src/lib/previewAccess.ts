import { api } from "./api";

export type PreviewGrant = Awaited<ReturnType<typeof api.issueRevisionPreview>>;

/** Only navigate to canonical server-issued project origins and scoped views. */
export async function acquireRevisionPreview(
  projectId: string, revisionId: string, signal?: AbortSignal, replaceViewId?: string,
): Promise<PreviewGrant> {
  const grant = await api.issueRevisionPreview(projectId, revisionId, signal, replaceViewId);
  const url = new URL(grant.url);
  const view = new URL(grant.viewUrl);
  if (grant.revisionId !== revisionId || url.protocol !== "https:" ||
      url.hostname !== window.location.hostname || Number(url.port) < 1024 ||
      url.origin === window.location.origin || url.username || url.password ||
      url.pathname !== "/_atom/open" || url.search !== "" || !/^#[0-9a-f]{64}$/.test(url.hash) ||
      !/^[0-9a-f]{64}$/.test(grant.viewId) || view.origin !== url.origin ||
      view.pathname !== `/_atom/view/${grant.viewId}/` || view.search || view.hash ||
      view.username || view.password || !Number.isFinite(grant.expiresAt) ||
      grant.expiresAt * 1000 <= Date.now()) {
    throw new Error("预览版本暂时无法确认，请重试。");
  }
  return grant;
}

/** Popup uses a distinct view so it cannot change an embedded preview's files. */
export async function openRevisionPreview(projectId: string, revisionId: string): Promise<void> {
  const popup = window.open("about:blank", "_blank");
  if (!popup) throw new Error("浏览器阻止了新窗口，请允许弹出窗口后重试。");
  popup.opener = null;
  popup.document.title = "正在打开版本预览";
  popup.document.body.textContent = "正在打开版本预览…";
  try {
    const grant = await acquireRevisionPreview(projectId, revisionId, AbortSignal.timeout(10000));
    popup.location.replace(grant.url);
  } catch (error) {
    popup.close();
    throw error;
  }
}
