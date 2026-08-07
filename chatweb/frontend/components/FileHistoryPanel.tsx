"use client";
// 文件历史 diff 面板(Phase 2 §2.5,桌面为主,web 也可用)。
// 数据源:chatweb 后端的 file-history sidecar + file-history/{sha16}@vN 备份。
// 左列文件列表;右侧 Monaco DiffEditor(选中历史版本 vs 磁盘当前内容)。
// 使用方:ChatHeader「文件历史」按钮(有 activeSessionId 时可用)。
import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { FileCode2, History, RefreshCw, X } from "lucide-react";
import { apiFiles, apiFileContent } from "@/lib/api";
import { languageFromPath } from "@/lib/fileLanguage";
import "@/lib/monacoSetup";

const DiffEditor = dynamic(
  () => import("@monaco-editor/react").then((m) => m.DiffEditor),
  { ssr: false, loading: () => <div className="p-4 text-sm text-[var(--muted-foreground)]">加载编辑器…</div> },
);

interface FileVersion {
  version: number;
  step_id: number;
  time: number;
  exists: boolean;
}
interface FileEntry {
  key: string;
  path: string;
  name: string;
  current_exists: boolean;
  versions: FileVersion[];
}

interface Props {
  runId: string;
  onClose: () => void;
}

export default function FileHistoryPanel({ runId, onClose }: Props) {
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [version, setVersion] = useState<number | null>(null);
  const [original, setOriginal] = useState<{ lang: string; text: string } | null>(null);
  const [current, setCurrent] = useState<{ lang: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    async (key: string, ver: number | null) => {
      if (!key || !runId) return;
      setBusy(true);
      try {
        const entry = files?.find((f) => f.key === key);
        // 默认版本 = 倒数第二个(通常是"最后一次编辑前");只有 1 版就取它本身
        let targetVer = ver;
        if (targetVer == null) {
          const vs = entry?.versions ?? [];
          targetVer = vs.length >= 2 ? vs[vs.length - 2].version : vs[0]?.version ?? null;
        }
        setVersion(targetVer);
        const lang = languageFromPath(entry?.path ?? "");
        const [curR, oldR] = await Promise.all([
          apiFileContent(runId, key, "current"),
          targetVer == null ? Promise.resolve(null) : apiFileContent(runId, key, targetVer),
        ]);
        const curD = curR?.ok ? await curR.json() : { exists: false, content: "" };
        setCurrent({ lang, text: curD.exists ? curD.content : "" });
        if (oldR) {
          const oldD = oldR.ok ? await oldR.json() : { exists: false, content: "" };
          setOriginal({ lang, text: oldD.exists ? oldD.content : "" });
        } else {
          setOriginal(null);
        }
        setError("");
      } catch {
        setError("加载内容失败");
      }
      setBusy(false);
    },
    [runId, files],
  );

  const loadFiles = useCallback(async () => {
    setBusy(true);
    try {
      const r = await apiFiles(runId);
      if (!r.ok) {
        setFiles([]);
        setError(`加载失败 (${r.status})`);
        return;
      }
      const data: FileEntry[] = await r.json();
      setFiles(data);
      setError("");
      // 保留当前选择;没有则默认第一个
      const keep = data.some((f) => f.key === selected) ? selected : data[0]?.key ?? "";
      setSelected(keep);
      if (keep) void refresh(keep, null);
      else { setOriginal(null); setCurrent(null); }
    } catch {
      setFiles([]);
      setError("无法连接后端");
    }
    setBusy(false);
  }, [runId, refresh, selected]);

  useEffect(() => {
    void loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const onSelectFile = (key: string) => {
    setSelected(key);
    void refresh(key, null);
  };

  const onSelectVersion = (v: number) => {
    setVersion(v);
    void refresh(selected, v);
  };

  const selFile = files?.find((f) => f.key === selected);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label="文件历史">
      <div className="flex h-[88vh] w-[92vw] max-w-6xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-2xl">
        {/* 标题栏 */}
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-[var(--border)]/60 px-4">
          <History size={15} className="text-[var(--primary)]" />
          <span className="text-sm font-medium text-[var(--foreground)]">文件历史</span>
          <span className="truncate font-mono text-[11px] text-[var(--muted-foreground)]">{runId}</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => void loadFiles()}
            disabled={busy}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 disabled:opacity-50"
            title="刷新"
          >
            <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> 刷新
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>

        {error && (
          <div className="border-b border-red-500/20 bg-red-500/10 px-4 py-1.5 text-xs text-red-500">{error}</div>
        )}

        {/* 主体:左列文件列表 + 右侧 diff */}
        <div className="flex min-h-0 flex-1">
          <div className="w-60 shrink-0 overflow-auto border-r border-[var(--border)]/60">
            {files === null ? (
              <div className="p-3 text-xs text-[var(--muted-foreground)]">加载中…</div>
            ) : files.length === 0 ? (
              <div className="flex flex-col items-start gap-1 p-3 text-xs text-[var(--muted-foreground)]">
                <FileCode2 size={14} />
                本次会话还没有编辑过文件。
              </div>
            ) : (
              files.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => onSelectFile(f.key)}
                  className={`flex w-full items-center gap-2 border-l-2 px-3 py-2 text-left text-xs transition-colors ${
                    f.key === selected
                      ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                      : "border-transparent text-[var(--muted-foreground)] hover:bg-[var(--muted)]/30"
                  }`}
                >
                  <FileCode2 size={13} className="shrink-0" />
                  <span className="truncate font-mono">{f.name}</span>
                  <span className="ml-auto shrink-0 rounded bg-[var(--muted)]/50 px-1 text-[10px]">
                    v{f.versions.length}
                  </span>
                </button>
              ))
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col">
            {!selFile ? (
              <div className="flex flex-1 items-center justify-center text-xs text-[var(--muted-foreground)]">
                选择左侧文件查看 diff
              </div>
            ) : (
              <>
                {/* 版本选择条 */}
                <div className="flex h-10 shrink-0 items-center gap-2 border-b border-[var(--border)]/60 px-3 text-xs">
                  <span className="truncate font-mono text-[var(--foreground)]">{selFile.path}</span>
                  <div className="flex-1" />
                  <label className="text-[var(--muted-foreground)]">对比版本</label>
                  <select
                    value={version ?? ""}
                    onChange={(e) => onSelectVersion(Number(e.target.value))}
                    className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                  >
                    {selFile.versions.length === 0 && <option value="">无可对比版本</option>}
                    {[...selFile.versions].reverse().map((v) => (
                      <option key={v.version} value={v.version}>
                        v{v.version} {v.exists ? `(step ${v.step_id})` : "(空)"}
                      </option>
                    ))}
                  </select>
                  <span className="rounded bg-[var(--muted)]/50 px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                    修改自
                  </span>
                </div>
                {/* DiffEditor:original=选中版本,modified=磁盘当前 */}
                <div className="min-h-0 flex-1">
                  {original == null ? (
                    <div className="p-4 text-xs text-[var(--muted-foreground)]">无可对比的历史版本(新建文件?)。</div>
                  ) : (
                    <DiffEditor
                      height="100%"
                      theme="vs-dark"
                      language={original.lang}
                      original={original.text}
                      modified={current?.text ?? ""}
                      options={{
                        readOnly: true,
                        renderSideBySide: true,
                        minimap: { enabled: false },
                        fontSize: 12,
                        automaticLayout: true,
                        scrollBeyondLastLine: false,
                      }}
                    />
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
