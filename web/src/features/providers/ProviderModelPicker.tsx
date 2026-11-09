import { Check, ChevronDown, RefreshCw, Search, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ProviderModelOption } from "../../api/client";

export function ProviderModelPicker({ label, value, choices, disabled, loading, status, onChange, onRefresh }: {
  label: string; value: string; choices: ProviderModelOption[]; disabled: boolean; loading: boolean;
  status: string; onChange: (value: string) => void; onRefresh: () => void;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const filtered = choices.filter((item) => `${item.id} ${item.label}`.toLowerCase().includes(query.trim().toLowerCase()));
  const visible = filtered.slice(0, 100);

  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => { setActive(0); }, [query, choices]);
  useEffect(() => {
    if (open) document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, open, id]);

  function close() { setOpen(false); trigger.current?.focus(); }
  function select(item: ProviderModelOption) { onChange(item.id); close(); }
  function toggle() { setQuery(""); setActive(0); setOpen(!open); }

  return <div className="stack-field model-picker" ref={root} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }} onKeyDown={(event) => {
    if (event.key === "Escape" && open) { event.preventDefault(); event.stopPropagation(); close(); }
  }}>
    <div className="model-picker-heading"><label htmlFor={`${id}-value`}>{label}</label><span>{loading ? "正在同步" : choices.length ? `${choices.length} 个可选模型` : "支持手动填写"}</span></div>
    <div className="model-picker-control">
      <input id={`${id}-value`} type="text" value={value} disabled={disabled} placeholder="选择模型或输入完整模型 ID" autoComplete="off" spellCheck={false} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => {
        if (event.key === "ArrowDown") { event.preventDefault(); setQuery(""); setOpen(true); }
      }} />
      <button ref={trigger} type="button" className={`model-picker-toggle ${open ? "is-open" : ""}`} aria-label={`选择${label}`} aria-expanded={open} aria-controls={`${id}-panel`} disabled={disabled} onClick={toggle}><ChevronDown size={17} /></button>
    </div>
    <div className="model-picker-footer"><span role="status" title={status}>{loading ? "正在读取模型目录…" : status || "填写连接信息后自动获取，也可直接输入模型 ID"}</span><button type="button" disabled={disabled || loading} onClick={onRefresh}><RefreshCw size={12} className={loading ? "model-picker-spin" : ""} />{loading ? "获取中" : "刷新"}</button></div>
    {open && <div id={`${id}-panel`} className="model-picker-panel">
      <div className="model-picker-search"><Search size={15} /><input ref={search} type="search" role="combobox" aria-label={`搜索${label}`} aria-autocomplete="list" aria-expanded={true} aria-controls={`${id}-list`} aria-activedescendant={visible[active] ? `${id}-option-${active}` : undefined} placeholder="搜索模型名称或 ID…" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault(); setActive((current) => Math.max(0, Math.min(visible.length - 1, current + (event.key === "ArrowDown" ? 1 : -1))));
        } else if (event.key === "Enter") {
          event.preventDefault(); if (visible[active]) select(visible[active]);
        }
      }} /><button type="button" aria-label="关闭模型列表" onClick={close}><X size={14} /></button></div>
      <div id={`${id}-list`} className="model-picker-options" role="listbox" aria-label={`${label}候选`}>
        {visible.map((item, index) => <button type="button" role="option" id={`${id}-option-${index}`} aria-selected={value === item.id} key={item.id} className={`model-picker-option ${active === index ? "is-active" : ""}`} onPointerMove={() => setActive(index)} onClick={() => select(item)}><span><strong>{item.label || item.id}</strong>{item.label !== item.id && <small>{item.id}</small>}</span>{value === item.id && <Check size={15} />}</button>)}
        {!visible.length && <div className="model-picker-empty"><Search size={22} /><strong>{loading ? "正在获取模型…" : query ? "没有匹配的模型" : "暂无可选模型"}</strong><span>{query ? "试试其他关键词，或关闭列表后手动填写。" : "可点击刷新重试，也可以直接填写完整模型 ID。"}</span></div>}
      </div>
      <div className="model-picker-panel-footer"><span>{filtered.length > 100 ? `显示前 100 / ${filtered.length} 项，请搜索缩小范围` : `${filtered.length} 个模型`}</span><span>↑ ↓ 选择 · Enter 确认</span></div>
    </div>}
  </div>;
}
