import type { Requirement, RuntimeResult } from "./types";

export function instrumentHtml(html: string, snapshot: Record<string, string>, nonce: string): string {
  const payload = JSON.stringify({ snapshot, nonce }).replace(/</g, "\\u003c");
  const boot = `<script>(function(){
    var cfg = ${payload};
    var saved = cfg.snapshot || {};
    var quiet = true;
    function snapshotNow(){
      if (quiet) return;
      var data = {};
      try {
        for (var i = 0; i < localStorage.length; i++) {
          var key = localStorage.key(i);
          if (key) data[key] = localStorage.getItem(key);
        }
      } catch (err) { return; }
      parent.postMessage({ source: "atom-preview", nonce: cfg.nonce, type: "state", snapshot: data }, "*");
    }
    var nativeOk = false;
    try {
      localStorage.setItem("__atom_probe", "1");
      localStorage.removeItem("__atom_probe");
      nativeOk = true;
    } catch (err) {}
    if (!nativeOk) {
      var memory = {};
      var fake = {
        getItem: function(key){ return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null; },
        setItem: function(key, value){ memory[String(key)] = String(value); snapshotNow(); },
        removeItem: function(key){ delete memory[String(key)]; snapshotNow(); },
        clear: function(){ memory = {}; snapshotNow(); },
        key: function(index){ return Object.keys(memory)[index] || null; },
        get length(){ return Object.keys(memory).length; }
      };
      try { Object.defineProperty(window, "localStorage", { configurable: true, get: function(){ return fake; } }); } catch (err) {}
    }
    try {
      Object.keys(saved).forEach(function(key){ localStorage.setItem(key, saved[key]); });
    } catch (err) {}
    if (nativeOk) {
      var setItem = localStorage.setItem.bind(localStorage);
      var removeItem = localStorage.removeItem.bind(localStorage);
      var clear = localStorage.clear.bind(localStorage);
      localStorage.setItem = function(key, value){ setItem(key, String(value)); snapshotNow(); };
      localStorage.removeItem = function(key){ removeItem(key); snapshotNow(); };
      localStorage.clear = function(){ clear(); snapshotNow(); };
    }
    quiet = false;
    function wait(ms){ return new Promise(function(resolve){ setTimeout(resolve, ms); }); }
    async function runFlow(key, index, steps){
      for (var i = 0; i < steps.length; i++) {
        var step = steps[i];
        if (step.do === "fill" || step.do === "click") {
          var el = document.querySelector(step.selector);
          if (!el) return { key: key, index: index, ok: false, detail: "找不到 " + step.selector };
          if (step.do === "fill") {
            el.focus();
            el.value = step.value || "";
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
          } else {
            el.click();
          }
        } else if (step.do === "see") {
          await wait(80);
          var text = document.body ? document.body.innerText : "";
          if (text.indexOf(step.contains || "") === -1) {
            return { key: key, index: index, ok: false, detail: "页面上没有出现「" + (step.contains || "") + "」" };
          }
        }
      }
      return { key: key, index: index, ok: true, detail: "操作之后页面符合预期" };
    }
    window.addEventListener("message", function(event){
      var data = event.data || {};
      if (data.nonce !== cfg.nonce || data.type !== "probe") return;
      var requirements = data.requirements || [];
      var jobs = [];
      requirements.forEach(function(req){
        (req.checks || []).forEach(function(check, index){
          if (check.op === "flow") jobs.push(runFlow(req.key, index, check.steps || []));
        });
      });
      Promise.all(jobs).then(function(results){
        parent.postMessage({ source: "atom-preview", nonce: cfg.nonce, type: "probe-result", results: results }, "*");
      });
    });
  })();</script>`;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head[^>]*>/i, (match) => match + boot);
  }
  return boot + html;
}

export function probeFrame(
  frame: HTMLIFrameElement,
  nonce: string,
  requirements: Requirement[],
): Promise<RuntimeResult[]> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error("验收没有在预览里跑完，可以再试一次"));
    }, 8000);

    function onMessage(event: MessageEvent) {
      const data = event.data as { source?: string; nonce?: string; type?: string; results?: RuntimeResult[] };
      if (!data || data.source !== "atom-preview" || data.nonce !== nonce || data.type !== "probe-result") return;
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      resolve(data.results || []);
    }

    window.addEventListener("message", onMessage);
    frame.contentWindow?.postMessage({ nonce, type: "probe", requirements }, "*");
  });
}
