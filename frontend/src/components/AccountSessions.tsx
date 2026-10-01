import { useRef, useState } from "react";
import { useAuth } from "../lib/auth";
import { Button } from "./ui/Button";
import { ErrorState, Panel } from "./ui/States";

export function AccountSessions() {
  const { user, signOut } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const pending = useRef(false);

  async function revoke() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setFailed(false);
    try { await signOut(true); }
    catch { setFailed(true); }
    finally { pending.current = false; setBusy(false); }
  }

  if (!user?.canRevokeSessions) return null;
  return <Panel className="flex flex-col gap-m p-xl">
    <h2 className="text-md font-medium text-neutral-95">账户会话</h2>
    <p className="text-base text-neutral-60">退出当前及其他设备上的现有登录，并使这些登录授权的私有项目访问失效。之后仍可重新登录。</p>
    {confirming ? <>
      <p className="text-base text-neutral-95">确认退出所有设备？未保存的页面修改可能丢失。</p>
      {failed ? <ErrorState title="退出未能确认完成" message="部分会话可能仍然有效。请重试；若登录已失效，请重新登录后核对。" compact /> : null}
      <div className="flex flex-wrap gap-s">
        <Button variant="danger" loading={busy} onClick={() => void revoke()}>确认退出所有设备</Button>
        <Button variant="secondary" disabled={busy} onClick={() => { setConfirming(false); setFailed(false); }}>取消</Button>
      </div>
    </> : <div><Button variant="secondary" onClick={() => setConfirming(true)}>退出所有设备</Button></div>}
  </Panel>;
}
