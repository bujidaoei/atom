import { api } from "./api";

/** Open only a server-issued one-use URL for the exact saved revision. */
export async function openRevisionPreview(projectId: string, revisionId: string): Promise<void> {
  const popup = window.open("about:blank", "_blank");
  if (!popup) throw new Error("浏览器阻止了新窗口，请允许弹出窗口后重试。");
  popup.opener = null;
  popup.document.title = "正在打开版本预览";
  popup.document.body.textContent = "正在打开版本预览…";
  try {
    const grant = await api.issueRevisionPreview(projectId, revisionId);
    const url = new URL(grant.url);
    if (grant.revisionId !== revisionId || url.protocol !== "https:" ||
        url.hostname !== window.location.hostname || url.pathname !== "/_atom/open" ||
        url.search !== "" || !/^#[0-9a-f]{64}$/.test(url.hash)) {
      throw new Error("预览版本暂时无法确认，请重试。");
    }
    popup.location.replace(url.href);
  } catch (error) {
    popup.close();
    throw error;
  }
}
