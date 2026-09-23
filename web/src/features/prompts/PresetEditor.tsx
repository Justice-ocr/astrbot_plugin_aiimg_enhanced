import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { saveStudioPresets } from "../../api/client";

type Row = { name: string; prompt: string };

export function PresetEditor({ feature, values, revision, onSaved }: {
  feature: string;
  values: unknown[];
  revision: string;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() => values.map((value) => {
    if (typeof value !== "string") return { name: "", prompt: "" };
    const colon = value.indexOf(":");
    return colon < 0 ? { name: value, prompt: "" } : { name: value.slice(0, colon), prompt: value.slice(colon + 1) };
  }));
  const [savedRevision, setSavedRevision] = useState(revision);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const unsupported = values.some((value) => typeof value !== "string");
  function update(index: number, changes: Partial<Row>) {
    setRows((current) => current.map((row, position) => position === index ? { ...row, ...changes } : row));
    setStatus("");
  }
  async function save() {
    if (busy || unsupported) return;
    if (rows.some((row) => !row.name.trim() || row.name.includes(":") || !row.prompt.trim())) {
      setStatus("名称和提示词不能为空，名称不能包含英文冒号");
      return;
    }
    if (new Set(rows.map((row) => row.name.trim())).size !== rows.length) {
      setStatus("预设名称不能重复");
      return;
    }
    setBusy(true);
    try {
      setSavedRevision(await saveStudioPresets(feature, rows.map((row) => `${row.name.trim()}:${row.prompt.trim()}`), savedRevision));
      setStatus("已保存");
      onSaved();
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  return <section aria-label="预设编辑">
    {unsupported && <p role="alert">存在非标准预设格式，请在旧版设置中编辑；本页不会覆盖它们。</p>}
    <fieldset disabled={busy || unsupported} style={{ border: 0, padding: 0, minWidth: 0 }}>
      {rows.map((row, index) => <div key={index} className="prompt-library-toolbar">
        <input aria-label={`预设 ${index + 1} 名称`} maxLength={80} value={row.name} onChange={(event) => update(index, { name: event.target.value })} />
        <textarea aria-label={`预设 ${index + 1} 提示词`} maxLength={8000} rows={3} value={row.prompt} onChange={(event) => update(index, { prompt: event.target.value })} />
        <button type="button" className="icon-button danger" title="删除预设" onClick={() => {
          if (window.confirm(`删除预设「${row.name || index + 1}」？保存后生效。`)) setRows((current) => current.filter((_, position) => position !== index));
        }}><Trash2 size={17} /><span className="sr-only">删除预设</span></button>
      </div>)}
      <div className="composer-actions">
        <button type="button" className="secondary-action" disabled={rows.length >= 200} onClick={() => setRows((current) => [...current, { name: "", prompt: "" }])}><Plus size={17} />新增预设</button>
        <button type="button" className="primary-action" onClick={() => void save()}>{busy ? "保存中" : "保存预设"}</button>
      </div>
    </fieldset>
    {status && <p role="status">{status}</p>}
  </section>;
}
