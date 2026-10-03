import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ChevronRight, ExternalLink, FileArchive, FileSearch, FileText, FolderOpen, LayoutDashboard, LoaderCircle, Plus, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { api } from "./api/client";
import type { Evidence, Material, MaterialSet } from "./types/api";
import { ResumeRecognitionPanel } from "./features/resume-recognition/ResumeRecognitionPanel";

type View = "overview" | "materials" | "resume";
const navigation: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "总览", icon: LayoutDashboard },
  { id: "materials", label: "材料库", icon: FolderOpen },
  { id: "resume", label: "简历确认", icon: FileText },
];

function App() {
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>(() => viewFromHash());
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("Python 后端简历");
  const [notice, setNotice] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Material | null>(null);

  useEffect(() => {
    const handleHashChange = () => setView(viewFromHash());
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  function navigate(nextView: View) {
    window.location.hash = `#/${nextView}`;
    setView(nextView);
  }

  const setsQuery = useQuery({
    queryKey: ["material-sets"],
    queryFn: () => api<MaterialSet[]>("/api/v1/material-sets"),
    refetchInterval: (current) => current.state.data?.some((item) => item.materials.some((material) => ["processing", "partial"].includes(material.status))) ? 1500 : false,
  });
  const sets = setsQuery.data ?? [];
  const activeSet = sets.find((item) => item.id === selectedId) ?? sets[0];
  const resumeMaterials = activeSet?.materials.filter((item) => item.kind === "resume") ?? [];
  const resume = resumeMaterials.find((item) => item.id === selectedResumeId) ?? [...resumeMaterials].reverse()[0];
  const readyCount = useMemo(() => activeSet?.materials.filter((item) => item.status === "ready").length ?? 0, [activeSet]);
  const evidenceQuery = useQuery({
    queryKey: ["evidence", activeSet?.id],
    queryFn: () => api<Evidence[]>(`/api/v1/material-sets/${activeSet!.id}/evidence`),
    enabled: Boolean(activeSet?.id),
  });

  const createSet = useMutation({
    mutationFn: (title: string) => api<MaterialSet>("/api/v1/material-sets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }),
    onSuccess: (item) => {
      client.invalidateQueries({ queryKey: ["material-sets"] });
      setSelectedId(item.id);
      navigate("materials");
      setShowCreate(false);
      setNotice("材料集合已创建");
    },
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (!activeSet) throw new Error("请先创建材料集合");
      const body = new FormData();
      body.append("file", file);
      return api<MaterialSet>(`/api/v1/material-sets/${activeSet.id}/materials?kind=resume`, { method: "POST", body });
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["material-sets"] });
      navigate("materials");
      setNotice("简历已上传，正在本地解析和 OCR");
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "上传失败"),
  });

  const removeSet = useMutation({
    mutationFn: () => activeSet ? api(`/api/v1/material-sets/${activeSet.id}`, { method: "DELETE" }) : Promise.resolve(null),
    onSuccess: () => {
      setSelectedId(null);
      navigate("overview");
      setSelectedEvidence(null);
      client.invalidateQueries({ queryKey: ["material-sets"] });
      setNotice("材料集合已删除");
    },
  });

  const removeMaterial = useMutation({
    mutationFn: (materialId: string) => api(`/api/v1/materials/${materialId}`, { method: "DELETE" }),
    onSuccess: (_, materialId) => {
      const removedCurrentResume = materialId === resume?.id;
      if (removedCurrentResume) setSelectedResumeId(null);
      if (removedCurrentResume && resumeMaterials.length <= 1) navigate("materials");
      setPendingDelete(null);
      setSelectedEvidence(null);
      client.invalidateQueries({ queryKey: ["material-sets"] });
      client.invalidateQueries({ queryKey: ["evidence"] });
      setNotice("材料已从当前版本移除");
    },
  });
  const retryMaterial = useMutation({
    mutationFn: (materialId: string) => api<MaterialSet>(`/api/v1/materials/${materialId}/retry`, { method: "POST" }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["material-sets"] }); client.invalidateQueries({ queryKey: ["evidence"] }); setNotice("项目材料已重新解析"); },
  });

  function submitCreate(event: FormEvent) {
    event.preventDefault();
    if (newTitle.trim()) createSet.mutate(newTitle.trim());
  }

  function selectSet(id: string, nextView: View = "materials") {
    setSelectedId(id);
    setSelectedResumeId(null);
    navigate(nextView);
    setSelectedEvidence(null);
  }

  function openEvidence(evidence: Evidence) {
    setSelectedEvidence(evidence);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">/</span><div><strong>问简历</strong><small>resume workspace</small></div></div>
        <nav className="main-nav" aria-label="主导航">
          {navigation.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${view === id ? "active" : ""}`} onClick={() => navigate(id)}><Icon size={16} /><span>{label}</span></button>)}
        </nav>
        <div className="sidebar-label"><span>材料集合</span><button className="icon-button" onClick={() => setShowCreate(true)} aria-label="创建材料集合" title="创建材料集合"><Plus size={16} /></button></div>
        {showCreate && <form className="create-inline" onSubmit={submitCreate}><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} aria-label="材料集合名称" autoFocus /><button type="submit" aria-label="确认创建"><Check size={15} /></button><button type="button" onClick={() => setShowCreate(false)} aria-label="取消创建"><X size={15} /></button></form>}
        <div className="set-list">
          {sets.map((item) => <button key={item.id} className={`set-item ${item.id === activeSet?.id ? "active" : ""}`} onClick={() => selectSet(item.id)}><span className="set-dot" /><span className="set-copy"><b>{item.title}</b><small>{item.materials.length ? `${item.materials.length} 份材料` : "等待上传"}</small></span><ChevronRight size={15} /></button>)}
          {!sets.length && <div className="empty-sidebar">还没有材料集合<br /><button onClick={() => setShowCreate(true)}>创建第一组 <ChevronRight size={13} /></button></div>}
        </div>
        <div className="sidebar-foot"><span className="status-dot" />本地工作区 <span className="version">OCR MVP</span></div>
      </aside>

      <section className="workspace">
        <header className="topbar"><div><span className="eyebrow">LOCAL OCR WORKSPACE</span><h1>{activeSet?.title ?? "简历材料工作区"}</h1></div><div className="top-actions">{activeSet && <button className="text-button danger" onClick={() => removeSet.mutate()}><Trash2 size={15} /> 删除集合</button>}<div className="avatar">候</div></div></header>
        {notice && <div className="notice"><span>{notice}</span><button onClick={() => setNotice("")} aria-label="关闭提示"><X size={14} /></button></div>}
        <div className={`workspace-body ${selectedEvidence ? "has-evidence" : ""}`}>
          <div className="workspace-main">
            {view === "overview" && <Overview sets={sets} activeSet={activeSet} onCreate={() => setShowCreate(true)} onSelect={selectSet} />}
            {view === "materials" && <MaterialsView activeSet={activeSet} resume={resume} resumes={resumeMaterials} readyCount={readyCount} uploadPending={upload.isPending} onUpload={(file) => upload.mutate(file)} evidence={evidenceQuery.data ?? []} onEvidence={openEvidence} onResume={(id) => { setSelectedResumeId(id); navigate("resume"); }} onDelete={setPendingDelete} onRetry={(id) => retryMaterial.mutate(id)} />}
            {view === "resume" && <ResumeView resumeId={resume?.id} resumes={resumeMaterials} onSelectResume={setSelectedResumeId} evidence={evidenceQuery.data ?? []} onEvidence={openEvidence} onGoMaterials={() => navigate("materials")} />}
          </div>
          {selectedEvidence && <EvidencePanel evidence={selectedEvidence} onClose={() => setSelectedEvidence(null)} />}
        </div>
      </section>
      {pendingDelete && <DeleteMaterialDialog material={pendingDelete} pending={removeMaterial.isPending} error={removeMaterial.isError} onCancel={() => setPendingDelete(null)} onConfirm={() => removeMaterial.mutate(pendingDelete.id)} />}
    </main>
  );
}

function viewFromHash(): View {
  const value = window.location.hash.replace(/^#\//, "");
  return value === "materials" || value === "resume" ? value : "overview";
}

function Overview({ sets, activeSet, onCreate, onSelect }: { sets: MaterialSet[]; activeSet?: MaterialSet; onCreate: () => void; onSelect: (id: string, view?: View) => void }) {
  const materialCount = sets.reduce((total, item) => total + item.materials.length, 0);
  const processingCount = sets.reduce((total, item) => total + item.materials.filter((material) => ["processing", "partial"].includes(material.status)).length, 0);
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">OVERVIEW</span><h2>先把简历整理成可信材料</h2><p>上传后由本地解析和 OCR 提取内容，你可以在确认页逐项修正并保留原文依据。</p></div><button className="primary-button" onClick={onCreate}><Plus size={16} /> 新建材料集合</button></div><div className="stat-grid"><div className="stat-card"><span>材料集合</span><strong>{sets.length}</strong><small>本地保存</small></div><div className="stat-card"><span>材料文件</span><strong>{materialCount}</strong><small>简历与解析结果</small></div><div className="stat-card"><span>处理中</span><strong>{processingCount}</strong><small>自动轮询状态</small></div></div><section className="overview-section"><div className="section-heading"><div><span className="eyebrow">RECENT SETS</span><h3>最近材料集合</h3></div></div>{sets.length ? <div className="set-grid">{sets.map((item) => <button className={`set-card ${item.id === activeSet?.id ? "selected" : ""}`} key={item.id} onClick={() => onSelect(item.id)}><span className="set-card-icon"><FolderOpen size={18} /></span><span><b>{item.title}</b><small>{item.materials.length ? `${item.materials.length} 份材料` : "等待上传简历"}</small></span><ChevronRight size={16} /></button>)}</div> : <div className="empty-panel large-empty">还没有材料集合，从上传一份简历开始。</div>}</section></section>;
}

function MaterialsView({ activeSet, resume, resumes, readyCount, uploadPending, onUpload, evidence, onEvidence, onResume, onDelete, onRetry }: { activeSet?: MaterialSet; resume?: Material; resumes: Material[]; readyCount: number; uploadPending: boolean; onUpload: (file: File) => void; evidence: Evidence[]; onEvidence: (evidence: Evidence) => void; onResume: (id: string) => void; onDelete: (material: Material) => void; onRetry: (materialId: string) => void }) {
  if (!activeSet) return <EmptyPage title="先创建材料集合" action="创建集合后上传简历" />;
  const groups = groupEvidence(evidence);
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">MATERIAL LIBRARY</span><h2>材料库</h2><p>管理当前版本的原始文件、解析状态和可追溯证据。</p></div><label className="upload-button"><Upload size={15} /> {uploadPending ? "上传中" : "上传简历"}<input type="file" accept=".pdf,.docx" disabled={uploadPending} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.currentTarget.value = ""; }} /></label></div><div className="material-summary"><div><FileText size={18} /><span><b>{readyCount} 份材料已完成解析</b><small>历史版本不会因删除当前材料而失效</small></span></div>{resume && <button className="secondary-button" onClick={() => onResume(resume.id)}><ExternalLink size={14} />打开简历确认</button>}</div><div className="material-library-intro"><div><span className="eyebrow">CURRENT REVISION</span><strong>{activeSet.materials.length} 份材料</strong><span>删除单份材料会生成新的当前版本，旧对话仍保留。</span></div></div><div className="material-list">{activeSet.materials.map((material) => <div className="material-row" key={material.id}><span className="material-row-icon">{material.kind === "resume" ? <FileText size={17} /> : <FileArchive size={17} />}</span><div className="material-row-copy"><b>{material.filename}</b><small>{material.kind === "resume" ? "简历" : "项目档案"} · {formatStatus(material.status)}</small>{material.errorMessage && <em>{material.errorMessage}</em>}</div><StatusPill status={material.status} /><div className="material-row-actions">{material.kind === "resume" && <button className="icon-button light" onClick={() => onResume(material.id)} aria-label="打开简历确认" title="打开简历确认"><ExternalLink size={14} /></button>}{material.kind === "project_archive" && <button className="icon-button light" onClick={() => onRetry(material.id)} aria-label="重试解析" title="重试解析"><RefreshCw size={14} /></button>}<button className="icon-button light" onClick={() => onEvidence(evidence.find((item) => item.materialId === material.id) ?? { id: `material-${material.id}`, content: "该材料暂无可展示的原文证据。", sourcePath: material.filename, materialId: material.id })} aria-label="查看原文" title="查看原文"><FileSearch size={14} /></button><button className="icon-button danger-light" onClick={() => onDelete(material)} aria-label={`删除材料 ${material.filename}`} title="删除材料"><Trash2 size={14} /></button></div></div>)}{!activeSet.materials.length && <div className="empty-panel large-empty">上传 PDF 或 DOCX 简历后，解析结果会显示在这里。</div>}</div><section className="evidence-section"><div className="section-heading"><div><span className="eyebrow">EVIDENCE INDEX</span><h3>按文件和页码查看原文</h3></div><span className="count-badge">{evidence.length}</span></div><div className="evidence-groups">{groups.map(([key, items]) => <section className="evidence-group" key={key}><div className="evidence-group-heading"><FileText size={14} /><strong>{key}</strong><span>{items.length} 个片段</span></div>{items.map((item) => <button className="evidence-item" key={item.id} onClick={() => onEvidence(item)}><span className="evidence-meta">{item.pageNumber ? `第 ${item.pageNumber} 页` : "段落原文"}</span><span>{item.content.slice(0, 220)}{item.content.length > 220 ? "…" : ""}</span></button>)}</section>)}{!evidence.length && <div className="empty-panel">解析完成后，页级和段落级证据会按文件分组显示。</div>}</div></section></section>;
}

function ResumeView({ resumeId, resumes, onSelectResume, evidence, onEvidence, onGoMaterials }: { resumeId?: string; resumes: Material[]; onSelectResume: (id: string) => void; evidence: Evidence[]; onEvidence: (evidence: Evidence) => void; onGoMaterials: () => void }) {
  if (!resumeId) return <EmptyPage title="还没有简历" action="请先在材料库上传 PDF 或 DOCX" onAction={onGoMaterials} />;
  return <section className="page-stack"><div className="page-heading compact-heading"><div><span className="eyebrow">RESUME CONFIRMATION</span><h2>简历确认</h2><p>按章节修正识别草稿，字段依据会在右侧分块展示。</p></div><div className="resume-picker"><label htmlFor="resume-picker">当前简历</label><select id="resume-picker" value={resumeId} onChange={(event) => onSelectResume(event.target.value)}>{resumes.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}</select></div></div><ResumeRecognitionPanel materialId={resumeId} evidence={evidence} onSelectEvidence={onEvidence} /></section>;
}

function EvidencePanel({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  return <aside className="evidence-pane" aria-label="原文依据"><div className="evidence-pane-heading"><div><span className="eyebrow">SOURCE EVIDENCE</span><h3>原文依据</h3><p>只读 · 当前字段关联片段</p></div><button className="icon-button" onClick={onClose} aria-label="关闭原文依据"><X size={16} /></button></div><div className="evidence-pane-meta"><span>{evidence.sourcePath ?? "简历原文"}</span>{evidence.pageNumber && <span>第 {evidence.pageNumber} 页</span>}</div><div className="evidence-pane-block"><span className="evidence-block-label">相关原文</span><p>{evidence.content}</p></div></aside>;
}

function groupEvidence(evidence: Evidence[]) {
  const groups = new Map<string, Evidence[]>();
  evidence.forEach((item) => { const key = item.sourcePath?.startsWith("resume-recognition:") ? "已确认结构化内容" : item.sourcePath ?? "简历原文"; groups.set(key, [...(groups.get(key) ?? []), item]); });
  return [...groups.entries()];
}

function DeleteMaterialDialog({ material, pending, error, onCancel, onConfirm }: { material: Material; pending: boolean; error: boolean; onCancel: () => void; onConfirm: () => void }) {
  return <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-material-title"><div className="modal-icon"><AlertTriangle size={19} /></div><div><span className="eyebrow">REMOVE MATERIAL</span><h3 id="delete-material-title">删除这份材料？</h3><p><strong>{material.filename}</strong> 将从当前版本移除。历史对话和旧版本仍然保留。</p>{error && <div className="modal-error">删除失败，请重试。</div>}</div><div className="modal-actions"><button className="secondary-button" onClick={onCancel} disabled={pending}>取消</button><button className="danger-button" onClick={onConfirm} disabled={pending}>{pending && <LoaderCircle size={14} className="spin" />}{pending ? "正在删除" : "确认删除"}</button></div></section></div>;
}

function EmptyPage({ title, action, onAction }: { title: string; action: string; onAction?: () => void }) { return <section className="empty-page"><FileText size={24} /><h2>{title}</h2><p>{action}</p>{onAction && <button className="secondary-button" onClick={onAction}>前往材料库 <ChevronRight size={14} /></button>}</section>; }
function StatusPill({ status }: { status: string }) { return <span className={`status-pill ${status}`}>{formatStatus(status)}</span>; }
function formatStatus(status: string) { return ({ processing: "处理中", partial: "部分完成", ready: "已完成", failed: "处理失败" } as Record<string, string>)[status] ?? status; }

export default App;
