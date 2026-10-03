import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ChevronRight, FileSearch, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import type { Evidence, RecognitionDraft, RecognitionResponse, RecognitionSection } from "../../types/api";

const sections: { id: RecognitionSection; label: string; number: string }[] = [
  { id: "personalInfo", label: "个人信息", number: "01" },
  { id: "skills", label: "技能掌握", number: "02" },
  { id: "workExperiences", label: "工作 / 实习经历", number: "03" },
  { id: "projects", label: "项目经验", number: "04" },
];

function splitItems(value: string) {
  return value.split(/[、,，/;；|]/).map((item) => item.trim()).filter(Boolean);
}

export function ResumeRecognitionPanel({ materialId, evidence, onSelectEvidence }: { materialId: string; evidence?: Evidence[]; onSelectEvidence?: (evidence: Evidence) => void }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<RecognitionDraft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [activeSection, setActiveSection] = useState<RecognitionSection>("personalInfo");
  const loadedRef = useRef(false);
  const query = useQuery({
    queryKey: ["recognition", materialId],
    queryFn: () => api<RecognitionResponse>(`/api/v1/materials/${materialId}/recognition`),
    refetchInterval: (current) => ["pending", "processing"].includes(current.state.data?.recognitionStatus ?? "") ? 1500 : false,
  });
  useEffect(() => {
    if (query.data && !dirty) { setDraft(query.data.draft); loadedRef.current = true; }
  }, [query.data, dirty]);
  const save = useMutation({
    mutationFn: (value: RecognitionDraft) => api<RecognitionResponse>(`/api/v1/materials/${materialId}/recognition`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft: value }) }),
    onSuccess: (value) => { setDraft(value.draft); setDirty(false); client.setQueryData(["recognition", materialId], value); client.invalidateQueries({ queryKey: ["evidence"] }); },
  });
  const confirm = useMutation({
    mutationFn: (section: RecognitionSection | "all") => api<RecognitionResponse>(`/api/v1/materials/${materialId}/recognition/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section }) }),
    onSuccess: (value) => { setDraft(value.draft); setDirty(false); client.setQueryData(["recognition", materialId], value); client.invalidateQueries({ queryKey: ["evidence"] }); },
  });
  const retry = useMutation({
    mutationFn: () => api<RecognitionResponse>(`/api/v1/materials/${materialId}/recognition/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope: "recognition" }) }),
    onSuccess: (value) => { setDraft(value.draft); setDirty(false); client.setQueryData(["recognition", materialId], value); client.invalidateQueries({ queryKey: ["evidence"] }); },
  });
  useEffect(() => {
    if (!dirty || !draft || !loadedRef.current) return;
    const timer = window.setTimeout(() => save.mutate(draft), 700);
    return () => window.clearTimeout(timer);
  }, [dirty, draft, save]);
  const confirmed = useMemo(() => new Set(query.data?.confirmedSections ?? []), [query.data?.confirmedSections]);
  const update = (next: RecognitionDraft) => { setDraft(next); setDirty(true); };
  const updatePersonal = (field: keyof RecognitionDraft["personalInfo"], value: string | string[]) => { if (draft) update({ ...draft, personalInfo: { ...draft.personalInfo, [field]: value } }); };
  const updateSkill = (value: string) => { if (!draft) return; update({ ...draft, skills: { ...draft.skills, content: value, edited: true } }); };
  const updateWork = (index: number, field: "company" | "role" | "startDate" | "endDate" | "description", value: string) => { if (!draft) return; update({ ...draft, workExperiences: draft.workExperiences.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value, edited: true } : item) }); };
  const updateProject = (index: number, field: "name" | "role" | "timeRange" | "description" | "technologies", value: string | string[]) => { if (!draft) return; update({ ...draft, projects: draft.projects.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value, edited: true } : item) }); };
  const addWork = () => draft && update({ ...draft, workExperiences: [...draft.workExperiences, { company: "", role: "", startDate: "", endDate: "", experienceType: "work", description: "", evidenceIds: [], edited: true }] });
  const addProject = () => draft && update({ ...draft, projects: [...draft.projects, { name: "", timeRange: "", role: "", technologies: [], description: "", links: [], projectArchiveId: null, evidenceIds: [], edited: true }] });
  const removeWork = (index: number) => draft && update({ ...draft, workExperiences: draft.workExperiences.filter((_, itemIndex) => itemIndex !== index) });
  const removeProject = (index: number) => draft && update({ ...draft, projects: draft.projects.filter((_, itemIndex) => itemIndex !== index) });
  const selectEvidence = (ids: string[] | undefined) => { const source = evidence?.find((item) => ids?.includes(item.id)); if (source && onSelectEvidence) onSelectEvidence(source); };
  if (query.isLoading) return <section className="recognition-panel panel"><div className="recognition-loading"><RefreshCw size={17} className="spin" />正在读取简历识别结果</div></section>;
  if (query.isError) return <section className="recognition-panel panel"><div className="recognition-loading"><AlertTriangle size={17} />识别结果暂不可用，请稍后重试</div></section>;
  if (!draft || !query.data) return null;
  const statusLabel = query.data.recognitionStatus === "awaitingConfirmation" ? "待确认" : query.data.recognitionStatus === "confirmed" ? "已确认" : query.data.recognitionStatus === "processing" ? "识别中" : query.data.recognitionStatus === "pending" ? "排队中" : "需要处理";
  const confirmDisabled = confirm.isPending || save.isPending || dirty;
  return <section className="recognition-panel panel">
    <div className="recognition-heading"><div><span className="eyebrow">RESUME EXTRACTION</span><h2>简历识别确认</h2><p>按章节核对结构化草稿，原文依据只读保留。</p></div><div className="recognition-actions"><span className={`recognition-status ${query.data.recognitionStatus}`}>{statusLabel}</span><button className="icon-button light" onClick={() => retry.mutate()} disabled={retry.isPending} aria-label="重试识别" title="重试识别"><RefreshCw size={15} /></button><button className="confirm-all" onClick={() => confirm.mutate("all")} disabled={confirmDisabled}><Check size={15} />确认全部</button></div></div>
    {query.data.warnings.length > 0 && <div className="recognition-warning"><AlertTriangle size={15} />{query.data.warnings.map((warning) => warning.message).filter(Boolean).join("；")}</div>}
    <div className="recognition-workspace"><nav className="recognition-nav" aria-label="简历章节"><span className="recognition-nav-label">FORM SECTIONS</span>{sections.map((section) => <button key={section.id} className={activeSection === section.id ? "active" : ""} onClick={() => setActiveSection(section.id)}><span className="recognition-nav-number">{section.number}</span><span className="recognition-nav-copy"><b>{section.label}</b><small>{section.id === "personalInfo" ? `${filledPersonalCount(draft)} 项已填写` : section.id === "skills" ? (draft.skills.content ? "1 段完整描述" : "待补填") : section.id === "workExperiences" ? `${draft.workExperiences.length} 段经历` : `${draft.projects.length} 个项目`}</small></span><SectionState confirmed={confirmed.has(section.id)} /></button>)}</nav><div className="recognition-form">
      {activeSection === "personalInfo" && <PersonalSection draft={draft} update={updatePersonal} ids={draft.personalInfo.evidenceIds} evidence={evidence} onEvidence={selectEvidence} confirmed={confirmed.has("personalInfo")} onConfirm={() => confirm.mutate("personalInfo")} disabled={confirmDisabled} />}
      {activeSection === "skills" && <SkillsSection skill={draft.skills} update={updateSkill} evidence={evidence} onEvidence={selectEvidence} confirmed={confirmed.has("skills")} onConfirm={() => confirm.mutate("skills")} disabled={confirmDisabled} />}
      {activeSection === "workExperiences" && <WorkSection items={draft.workExperiences} update={updateWork} add={addWork} remove={removeWork} evidence={evidence} onEvidence={selectEvidence} confirmed={confirmed.has("workExperiences")} onConfirm={() => confirm.mutate("workExperiences")} disabled={confirmDisabled} />}
      {activeSection === "projects" && <ProjectsSection items={draft.projects} update={updateProject} add={addProject} remove={removeProject} evidence={evidence} onEvidence={selectEvidence} confirmed={confirmed.has("projects")} onConfirm={() => confirm.mutate("projects")} disabled={confirmDisabled} />}
    </div></div>
    <div className="recognition-footer"><span><Save size={14} />{save.isPending ? "正在保存草稿" : dirty ? "修改会自动保存" : "草稿已保存"}</span>{save.isError && <span className="error-note">保存失败，请重试</span>}<button className="manual-save" onClick={() => draft && save.mutate(draft)} disabled={!dirty || save.isPending}><Save size={13} />立即保存</button></div>
  </section>;
}

function PersonalSection({ draft, update, ids, evidence, onEvidence, confirmed, onConfirm, disabled }: { draft: RecognitionDraft; update: (field: keyof RecognitionDraft["personalInfo"], value: string | string[]) => void; ids?: string[]; evidence?: Evidence[]; onEvidence: (ids?: string[]) => void; confirmed: boolean; onConfirm: () => void; disabled: boolean }) {
  return <SectionFrame eyebrow="PROFILE" title="个人信息" description="姓名、联系方式和求职方向只保留简历中明确出现的内容."><div className="profile-summary"><div className="profile-initial">{draft.personalInfo.name?.slice(0, 1) || "候"}</div><div><strong>{draft.personalInfo.name || "未识别姓名"}</strong><span>{draft.personalInfo.targetRole || "未填写求职方向"}</span></div></div><div className="personal-grid">{(["name", "phone", "email", "city", "targetRole"] as const).map((field) => <label key={field}>{({ name: "姓名", phone: "手机号", email: "邮箱", city: "所在城市", targetRole: "求职方向" } as Record<string, string>)[field]}<input value={draft.personalInfo[field]} onChange={(event) => update(field, event.target.value)} /></label>)}<label className="wide-field">个人链接<input value={draft.personalInfo.links.join(", ")} onChange={(event) => update("links", splitItems(event.target.value))} placeholder="GitHub、博客或个人主页" /></label></div><SourceHint ids={ids} evidence={evidence} onSelect={onEvidence} /><SectionConfirm section="personalInfo" confirmed={confirmed} onConfirm={onConfirm} disabled={disabled} /></SectionFrame>;
}

function SkillsSection({ skill, update, evidence, onEvidence, confirmed, onConfirm, disabled }: { skill: RecognitionDraft["skills"]; update: (value: string) => void; evidence?: Evidence[]; onEvidence: (ids?: string[]) => void; confirmed: boolean; onConfirm: () => void; disabled: boolean }) {
  return <SectionFrame eyebrow="CAPABILITIES" title="技能掌握" description="保留简历中的完整技能描述，不拆分分类、技能标签或熟练度。"><article className="skill-card compact-skill-card"><div className="record-heading"><div><span className="record-index">01</span><strong>技能掌握</strong></div></div><label>完整技能描述<textarea value={skill.content} onChange={(event) => update(event.target.value)} rows={10} placeholder="保留简历中的完整技能描述" /></label><SourceHint ids={skill.evidenceIds} evidence={evidence} onSelect={onEvidence} /></article>{!skill.content && <EmptySection text="未识别到技能描述，可手动补填。" />}<SectionConfirm section="skills" confirmed={confirmed} onConfirm={onConfirm} disabled={disabled} /></SectionFrame>;
}

function WorkSection({ items, update, add, remove, evidence, onEvidence, confirmed, onConfirm, disabled }: { items: RecognitionDraft["workExperiences"]; update: (index: number, field: "company" | "role" | "startDate" | "endDate" | "description", value: string) => void; add: () => void; remove: (index: number) => void; evidence?: Evidence[]; onEvidence: (ids?: string[]) => void; confirmed: boolean; onConfirm: () => void; disabled: boolean }) {
  return <SectionFrame eyebrow="EXPERIENCE" title="工作 / 实习经历" description="按单位保留基础信息，并用一段完整描述整理实际经历。"><div className="timeline">{items.map((work, index) => <article className="experience-card timeline-card" key={`${index}-${work.company}`}><span className="timeline-marker" /><div className="record-heading"><div><span className="record-index">{String(index + 1).padStart(2, "0")}</span><strong>{work.company || "未命名经历"}</strong></div><button className="icon-button danger-light" onClick={() => remove(index)} aria-label="删除记录" title="删除记录"><Trash2 size={14} /></button></div><div className="field-grid"><label>公司<input value={work.company} onChange={(event) => update(index, "company", event.target.value)} /></label><label>职位<input value={work.role} onChange={(event) => update(index, "role", event.target.value)} /></label><label>开始时间<input value={work.startDate} onChange={(event) => update(index, "startDate", event.target.value)} /></label><label>结束时间<input value={work.endDate} onChange={(event) => update(index, "endDate", event.target.value)} /></label></div><label>经历描述<textarea value={work.description} onChange={(event) => update(index, "description", event.target.value)} rows={7} placeholder="整理这段工作或实习经历的完整描述" /></label><SourceHint ids={work.evidenceIds} evidence={evidence} onSelect={onEvidence} /></article>)}</div><button className="add-row" onClick={add}><Plus size={14} />添加工作经历</button>{!items.length && <EmptySection text="未识别到工作或实习经历，可手动添加。" />}<SectionConfirm section="workExperiences" confirmed={confirmed} onConfirm={onConfirm} disabled={disabled} /></SectionFrame>;
}

function ProjectsSection({ items, update, add, remove, evidence, onEvidence, confirmed, onConfirm, disabled }: { items: RecognitionDraft["projects"]; update: (index: number, field: "name" | "role" | "timeRange" | "description" | "technologies", value: string | string[]) => void; add: () => void; remove: (index: number) => void; evidence?: Evidence[]; onEvidence: (ids?: string[]) => void; confirmed: boolean; onConfirm: () => void; disabled: boolean }) {
  return <SectionFrame eyebrow="PROJECTS" title="项目经验" description="保留项目定位信息，用一段完整描述整理项目背景、实现过程和个人贡献。"><div className="project-stack">{items.map((project, index) => <article className="experience-card project-card" key={`${index}-${project.name}`}><div className="record-heading"><div><span className="record-index">{String(index + 1).padStart(2, "0")}</span><strong>{project.name || "未命名项目"}</strong></div><button className="icon-button danger-light" onClick={() => remove(index)} aria-label="删除记录" title="删除记录"><Trash2 size={14} /></button></div><div className="field-grid"><label>项目名称<input value={project.name} onChange={(event) => update(index, "name", event.target.value)} /></label><label>角色<input value={project.role} onChange={(event) => update(index, "role", event.target.value)} /></label><label>时间范围<input value={project.timeRange} onChange={(event) => update(index, "timeRange", event.target.value)} /></label><label>技术栈<input value={project.technologies.join("、")} onChange={(event) => update(index, "technologies", splitItems(event.target.value))} /></label></div><label>项目描述<textarea value={project.description} onChange={(event) => update(index, "description", event.target.value)} rows={9} placeholder="整理这段项目经验的完整描述" /></label><SourceHint ids={project.evidenceIds} evidence={evidence} onSelect={onEvidence} /></article>)}</div><button className="add-row" onClick={add}><Plus size={14} />添加项目经验</button>{!items.length && <EmptySection text="未识别到个人项目，可手动添加。" />}<SectionConfirm section="projects" confirmed={confirmed} onConfirm={onConfirm} disabled={disabled} /></SectionFrame>;
}

function SectionFrame({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: React.ReactNode }) { return <div className="section-frame"><div className="section-frame-heading"><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3><p>{description}</p></div></div>{children}</div>; }
function filledPersonalCount(draft: RecognitionDraft) { return Object.values(draft.personalInfo).filter((value) => Array.isArray(value) ? value.length > 0 : Boolean(value)).length; }
function SectionState({ confirmed }: { confirmed: boolean }) { return <span className={`section-state ${confirmed ? "confirmed" : "pending"}`}>{confirmed ? "已确认" : "待确认"}</span>; }
function SectionConfirm({ section, confirmed, onConfirm, disabled }: { section: RecognitionSection; confirmed: boolean; onConfirm: () => void; disabled: boolean }) { return <div className="section-confirm"><span>{confirmed ? "该模块已进入简历事实库" : disabled ? "保存完成后才可确认本模块" : "确认后才会进入简历事实库"}</span>{!confirmed && <button onClick={onConfirm} disabled={disabled}><Check size={13} />确认本模块</button>}<span className="section-name">{section === "personalInfo" ? "PROFILE" : section.toUpperCase()}</span></div>; }
function EmptySection({ text }: { text: string }) { return <div className="empty-recognition"><AlertTriangle size={15} />{text}</div>; }
function SourceHint({ ids, evidence, onSelect }: { ids?: string[]; evidence?: Evidence[]; onSelect: (ids?: string[]) => void }) { const count = ids?.filter((id) => evidence?.some((item) => item.id === id)).length ?? 0; return <button className="source-hint" onClick={() => onSelect(ids)} disabled={!count} type="button"><FileSearch size={13} />{count ? `${count} 条原文依据` : "暂无原文依据"}<ChevronRight size={12} /></button>; }
