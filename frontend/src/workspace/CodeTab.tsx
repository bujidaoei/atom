import { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/ui/Icon";
import { EmptyState, ErrorState, LoadingState } from "../components/ui/States";
import { api, errorMessage } from "../lib/api";
import { formatBytes } from "../lib/format";
import type { FileEntry } from "../lib/types";

type TreeNode =
  | { kind: "file"; name: string; path: string; bytes: number }
  | { kind: "dir"; name: string; path: string; children: TreeNode[] };

function buildTree(files: FileEntry[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path))) {
    const segments = file.path.split("/").filter(Boolean);
    let level = root;
    let prefix = "";

    segments.forEach((segment, index) => {
      prefix = prefix ? `${prefix}/${segment}` : segment;
      if (index === segments.length - 1) {
        level.push({ kind: "file", name: segment, path: file.path, bytes: file.bytes });
        return;
      }
      let dir = level.find(
        (node): node is Extract<TreeNode, { kind: "dir" }> =>
          node.kind === "dir" && node.name === segment,
      );
      if (!dir) {
        dir = { kind: "dir", name: segment, path: prefix, children: [] };
        level.push(dir);
      }
      level = dir.children;
    });
  }

  const sort = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .map((node) => (node.kind === "dir" ? { ...node, children: sort(node.children) } : node))
      .sort((a, b) => {
        if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name);
      });

  return sort(root);
}

export function CodeTab({ projectId, files }: { projectId: string; files: FileEntry[] }) {
  const tree = useMemo(() => buildTree(files), [files]);
  const [selected, setSelected] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Default to the entry point so the tab is useful immediately.
  useEffect(() => {
    if (selected && files.some((file) => file.path === selected)) return;
    const entry =
      files.find((file) => file.path === "index.html") ??
      files.find((file) => file.path.endsWith(".html")) ??
      files[0];
    setSelected(entry ? entry.path : null);
  }, [files, selected]);

  if (files.length === 0) {
    return (
      <EmptyState
        icon="code"
        title="工作区还是空的"
        description="Alex 每写一个文件都会出现在这里，可以逐个点开看原文。"
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <div className="max-h-[200px] shrink-0 overflow-y-auto border-b border-neutral-12 p-xs md:max-h-none md:w-[220px] md:border-b-0 md:border-r">
        <TreeLevel
          nodes={tree}
          depth={0}
          selected={selected}
          onSelect={setSelected}
          collapsed={collapsed}
          onToggle={(path) =>
            setCollapsed((current) => ({ ...current, [path]: !current[path] }))
          }
        />
        <p className="px-xs py-s text-xs text-neutral-40">
          {files.length} 个文件 · {formatBytes(files.reduce((sum, file) => sum + file.bytes, 0))}
        </p>
      </div>

      <div className="min-h-0 min-w-0 flex-1">
        {selected ? <FileViewer projectId={projectId} path={selected} files={files} /> : null}
      </div>
    </div>
  );
}

function TreeLevel({
  nodes,
  depth,
  selected,
  onSelect,
  collapsed,
  onToggle,
}: {
  nodes: TreeNode[];
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  collapsed: Record<string, boolean>;
  onToggle: (path: string) => void;
}) {
  return (
    <ul className="flex flex-col" role={depth === 0 ? "tree" : "group"}>
      {nodes.map((node) =>
        node.kind === "dir" ? (
          <li key={node.path} role="none">
            <button
              type="button"
              onClick={() => onToggle(node.path)}
              aria-expanded={!collapsed[node.path]}
              style={{ paddingLeft: `${depth * 12 + 6}px` }}
              className="flex h-6 w-full items-center gap-xxs rounded-m pr-xs text-left text-sm text-neutral-80 transition-colors duration-ui ease-ui hover:bg-neutral-8 active:bg-neutral-12"
            >
              <Icon
                name="chevron-right"
                size={11}
                className={`text-neutral-40 transition-transform duration-ui ease-ui ${
                  collapsed[node.path] ? "" : "rotate-90"
                }`}
              />
              <Icon name="folder" size={12} className="text-neutral-40" />
              <span className="truncate">{node.name}</span>
            </button>
            {collapsed[node.path] ? null : (
              <TreeLevel
                nodes={node.children}
                depth={depth + 1}
                selected={selected}
                onSelect={onSelect}
                collapsed={collapsed}
                onToggle={onToggle}
              />
            )}
          </li>
        ) : (
          <li key={node.path} role="none">
            <button
              type="button"
              onClick={() => onSelect(node.path)}
              aria-current={selected === node.path}
              style={{ paddingLeft: `${depth * 12 + 6}px` }}
              className={[
                "flex h-6 w-full items-center gap-xxs rounded-m pr-xs text-left text-sm transition-colors duration-ui ease-ui",
                selected === node.path
                  ? "bg-neutral-16 text-neutral-95"
                  : "text-neutral-80 hover:bg-neutral-8 hover:text-neutral-95",
              ].join(" ")}
            >
              <Icon name="file" size={12} className="text-neutral-40" />
              <span className="truncate font-mono text-xs">{node.name}</span>
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

function FileViewer({
  projectId,
  path,
  files,
}: {
  projectId: string;
  path: string;
  files: FileEntry[];
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const entry = files.find((file) => file.path === path);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .readFile(projectId, path)
      .then((text) => {
        if (!cancelled) setContent(text);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, path, reloadKey]);

  const lines = useMemo(() => (content ?? "").replace(/\n$/, "").split("\n"), [content]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-s border-b border-neutral-12 px-m py-xs">
        <span className="truncate font-mono text-xs text-neutral-95">{path}</span>
        {entry ? (
          <span className="shrink-0 text-xs text-neutral-40">{formatBytes(entry.bytes)}</span>
        ) : null}
        <button
          type="button"
          onClick={() => setReloadKey((key) => key + 1)}
          className="ml-auto inline-flex items-center gap-xxs rounded-m px-s py-[2px] text-xs text-neutral-60 transition-colors duration-ui ease-ui hover:bg-neutral-8 hover:text-neutral-95"
        >
          <Icon name="refresh" size={12} />
          重新读取
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <LoadingState label="读取文件" />
        ) : error ? (
          <div className="p-m">
            <ErrorState message={error} onRetry={() => setReloadKey((key) => key + 1)} compact />
          </div>
        ) : (
          <table className="w-full border-collapse font-mono text-xs leading-5">
            <tbody>
              {lines.map((line, index) => (
                <tr key={index} className="align-top hover:bg-neutral-4">
                  <td className="w-[1%] select-none whitespace-nowrap border-r border-neutral-8 px-s text-right text-neutral-40">
                    {index + 1}
                  </td>
                  <td className="whitespace-pre-wrap break-all px-m text-neutral-80">
                    {line || " "}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
