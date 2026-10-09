import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, ChevronRight, FileText, FolderOpen, List, LoaderCircle, Menu, MessageSquare, Plus, Settings2, X } from "lucide-react";
import { practiceApi } from "../../api/practice";
import type { MaterialSet, PracticeMessage, PracticePreference, ResumeSnapshot } from "../../types/api";
import { ConversationHistory } from "../history/ConversationHistory";

type Props = { materialSetId?: string; materialSets: MaterialSet[]; conversationId: string | null; onConversationId: (id: string | null) => void; onMaterials: () => void; onSelectSet: (id: string) => void; onEditResume: () => void };
const sectionNames: Record<string, string> = { personalInfo: "个人信息", skills: "技能掌握", workExperiences: "工作 / 实习经历", projects: "项目经验" };

export function PracticePanel({ materialSetId, materialSets, conversationId, onConversationId, onMaterials, onSelectSet, onEditResume }: Props) {
  const client = useQueryClient();
  const [draft, setDraft] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [panel, setPanel] = useState<"resume" | "preferences" | null>(null);
  const [menu, setMenu] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const processedRun = useRef<string | null>(null);
  const retryInput = useRef<{ id: string; content: string } | null>(null);
  const draftKey = `practice-draft:${conversationId ?? materialSetId ?? "new"}`;
  const history = useQuery({ queryKey: ["practice-conversations", materialSetId], queryFn: () => practiceApi.conversations(materialSetId!, { status: "all" }), enabled: Boolean(materialSetId) });
  const conversations = history.data ?? [];
  useEffect(() => {
    if (!conversationId && materialSetId) {
      const remembered = localStorage.getItem(`practice-conversation:${materialSetId}`);
      const candidate = conversations.find(c => c.id === remembered) ?? conversations.find(c => !c.isArchived);
      if (candidate) onConversationId(candidate.id);
    }
  }, [conversations, conversationId, materialSetId, onConversationId]);
  useEffect(() => {
    setDraft(localStorage.getItem(draftKey) ?? "");
    setRunId(null); setFailedId(null); setNotice(""); retryInput.current = null;
    nearBottom.current = true;
    processedRun.current = null;
    if (materialSetId && conversationId) localStorage.setItem(`practice-conversation:${materialSetId}`, conversationId);
  }, [draftKey, materialSetId, conversationId]);
  const state = useQuery({ queryKey: ["chat-state", conversationId], queryFn: () => practiceApi.state(conversationId!), enabled: Boolean(conversationId), refetchInterval: q => q.state.data?.activeRunId ? 700 : false });
  const messages = useQuery({ queryKey: ["chat-messages", conversationId], queryFn: () => practiceApi.messages(conversationId!), enabled: Boolean(conversationId) });
  const turns = useQuery({ queryKey: ["practice-turns", conversationId], queryFn: () => practiceApi.turns(conversationId!), enabled: Boolean(conversationId) });
  const snapshots = useQuery({ queryKey: ["resume-snapshots", conversationId], queryFn: () => practiceApi.snapshots(conversationId!), enabled: Boolean(conversationId) && panel === "resume" });
  const preferences = useQuery({ queryKey: ["practice-preferences"], queryFn: practiceApi.preferences, enabled: panel === "preferences" });
  const activeId = runId ?? state.data?.activeRunId ?? null;
  const lookupId = activeId ?? state.data?.lastRunId ?? null;
  const run = useQuery({ queryKey: ["llm-run", lookupId], queryFn: () => practiceApi.run(lookupId!), enabled: Boolean(lookupId), refetchInterval: q => q.state.data && ["succeeded", "failed", "cancelled"].includes(q.state.data.status) ? false : 500 });
  function refresh() {
    for (const key of ["chat-state", "chat-messages", "practice-turns"]) client.invalidateQueries({ queryKey: [key, conversationId] });
    client.invalidateQueries({ queryKey: ["practice-conversations", materialSetId] });
    client.invalidateQueries({ queryKey: ["practice-preferences"] });
  }
  useEffect(() => {
    const value = run.data;
    if (!value || !["succeeded", "failed", "cancelled"].includes(value.status) || processedRun.current === value.id) return;
    processedRun.current = value.id;
    setRunId(null);
    if (value.status !== "succeeded") { setFailedId(value.id); setNotice(value.error ?? "任务已取消，可重试未完成步骤。"); }
    else { setFailedId(null); setNotice(""); }
    refresh();
  }, [run.data]);
  useEffect(() => { if (nearBottom.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [messages.data, activeId]);
  const create = useMutation({ mutationFn: () => practiceApi.create(materialSetId!), onSuccess: c => { onConversationId(c.id); setMenu(false); client.invalidateQueries({ queryKey: ["practice-conversations", materialSetId] }); }, onError: e => setNotice(e.message) });
  const send = useMutation({
    mutationFn: async (content: string) => {
      let cid = conversationId;
      if (!cid) { const c = await practiceApi.create(materialSetId!); cid = c.id; onConversationId(cid); }
      const previous = retryInput.current;
      const request = previous?.content === content ? previous : { id: crypto.randomUUID(), content };
      retryInput.current = request;
      return practiceApi.input(cid, content, request.id);
    },
    onSuccess: result => { retryInput.current = null; localStorage.removeItem(draftKey); setDraft(""); setRunId(result.runId); setFailedId(null); setNotice(""); nearBottom.current = true; refresh(); },
    onError: e => setNotice(e.message),
  });
  const action = useMutation({ mutationFn: (kind: "feedback" | "reference-answer" | "follow-up") => practiceApi.action(state.data!.currentTurnId!, kind), onSuccess: r => { setRunId(r.runId); setFailedId(null); }, onError: e => setNotice(e.message) });
  const next = useMutation({ mutationFn: () => practiceApi.next(conversationId!), onSuccess: refresh, onError: e => setNotice(e.message) });
  const retry = useMutation({ mutationFn: () => practiceApi.retry(failedId!), onSuccess: r => { setRunId(r.runId); setFailedId(null); setNotice(""); }, onError: e => setNotice(e.message) });
  const cancel = useMutation({ mutationFn: () => practiceApi.cancel(activeId!), onSuccess: refresh, onError: e => setNotice(e.message) });
  const removePreference = useMutation({ mutationFn: practiceApi.deletePreference, onSuccess: () => client.invalidateQueries({ queryKey: ["practice-preferences"] }), onError: e => setNotice(e.message) });
  const editPreference = useMutation({ mutationFn: ({ preference, value }: { preference: PracticePreference; value: string | number }) => practiceApi.updatePreference(preference, value), onSuccess: () => client.invalidateQueries({ queryKey: ["practice-preferences"] }), onError: e => setNotice(e.message) });
  const currentTurn = turns.data?.items.find(t => t.id === state.data?.currentTurnId);
  const selectedConversation = conversations.find(item => item.id === conversationId);
  const archivedReadOnly = Boolean(selectedConversation?.isArchived);
  const busy = Boolean(activeId) || send.isPending || action.isPending;
  function updateDraft(text: string) { setDraft(text); localStorage.setItem(draftKey, text); }
  function submit() { if (draft.trim() && !busy && materialSetId) send.mutate(draft.trim()); }
  return <section className={`chat-shell ${menu ? "show-chat-menu" : ""}`}>
    <aside className="chat-sidebar" aria-label="对话导航">
      <div className="chat-brand"><span>/</span><b>问简历</b><button aria-label="关闭导航" className="chat-mobile" onClick={() => setMenu(false)}><X size={18} /></button></div>
      <button className="chat-new" onClick={() => materialSetId ? create.mutate() : onMaterials()} disabled={create.isPending}><Plus size={16} />新建对话</button>
      <label className="chat-set-picker">当前材料集合<select value={materialSetId ?? ""} onChange={e => onSelectSet(e.target.value)} aria-label="选择材料集合">{materialSets.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}{!materialSets.length && <option value="">尚未创建</option>}</select></label>
      <span className="chat-sidebar-label">历史对话</span>
      <ConversationHistory materialSetId={materialSetId} selectedId={conversationId} compact onOpen={id => { if (id) onConversationId(id); setMenu(false); }} />
      <div className="chat-sidebar-bottom"><button onClick={onMaterials}><FolderOpen size={16} />材料库</button><button onClick={() => { setMenu(false); setPanel("preferences"); }}><Settings2 size={16} />练习偏好</button><small>基于你的经历，练习自己的解释。</small></div>
    </aside>
    <div className="chat-main">
      <header className="chat-topbar"><div><button className="chat-mobile" aria-label="打开导航" onClick={() => setMenu(true)}><Menu size={19} /></button><strong>{selectedConversation?.title ?? "面试练习"}</strong><span>{archivedReadOnly ? "已归档 · 只读" : state.data?.mainTurnIds.length ? `${state.data.currentIndex + 1} / ${state.data.mainTurnIds.length}${state.data.completed ? " · 已完成" : ""}` : "准备开始"}</span></div><button className="chat-resume-button" onClick={() => setPanel(panel === "resume" ? null : "resume")} disabled={!conversationId}><FileText size={15} />查看简历</button></header>
      <div className="chat-scroll" ref={scroll} onScroll={() => { if (scroll.current) nearBottom.current = scroll.current.scrollHeight - scroll.current.scrollTop - scroll.current.clientHeight < 100; }}>
        <div className="chat-thread">
          {!messages.data?.length && <div className="chat-welcome"><span className="chat-welcome-mark">/</span><small>你的经历，是练习的起点</small><h1>把项目讲清楚，<br />从一个问题开始。</h1><p>{materialSetId ? "告诉我想练习什么。我会结合已确认的简历，为你准备问题。" : "请先在材料库上传并确认一份简历。"}</p><div className="chat-suggestions">{["根据我的简历生成 5 个问题", "重点练习项目中的技术取舍"].map(text => <button key={text} onClick={() => updateDraft(text)} disabled={!materialSetId}>{text}<ChevronRight size={14} /></button>)}</div></div>}
          {messages.data?.map(m => <MessageBubble key={m.id} message={m} />)}
          {!messages.data?.length && currentTurn && <article className="chat-message assistant"><span>当前问题</span><p>{currentTurn.question}</p></article>}
          {(activeId || send.isPending) && <div className="chat-task" data-testid="active-task" role="status"><LoaderCircle className="spin" size={15} /><span>{send.isPending ? "正在提交输入" : run.data?.status === "running" ? "正在理解你的输入并处理" : "任务已提交，正在排队"}</span>{activeId && <button onClick={() => cancel.mutate()} disabled={cancel.isPending}>取消</button>}</div>}
          {messages.isError && <p role="alert">消息加载失败，请刷新重试。</p>}
        </div>
      </div>
      <div className="chat-composer-area">
        {archivedReadOnly && <div className="chat-archived-banner">此对话已归档，只读查看。请从历史菜单恢复后继续练习。</div>}
        {state.data?.mainTurnIds.length ? <div className="chat-actions"><button onClick={() => action.mutate("feedback")} disabled={busy || archivedReadOnly || !currentTurn?.answer}>查看反馈</button><button onClick={() => action.mutate("reference-answer")} disabled={busy || archivedReadOnly || !currentTurn?.answer}>参考答案</button><button onClick={() => action.mutate("follow-up")} disabled={busy || archivedReadOnly || !currentTurn?.answer}>继续追问</button><button onClick={() => next.mutate()} disabled={busy || archivedReadOnly || next.isPending || state.data.completed}>下一题</button><details><summary><List size={13} />问题目录</summary><ol>{state.data.mainTurnIds.map((id, i) => <li key={id} aria-current={i === state.data!.currentIndex ? "step" : undefined}>{turns.data?.items.find(t => t.id === id)?.question ?? `第 ${i + 1} 题`}</li>)}</ol></details></div> : null}
        {notice && <div className="chat-notice" role="alert"><span>{notice}</span>{failedId && <button onClick={() => retry.mutate()} disabled={retry.isPending}>重试未完成步骤</button>}<button aria-label="关闭提示" onClick={() => setNotice("")}><X size={13} /></button></div>}
        <form className="chat-composer" onSubmit={e => { e.preventDefault(); submit(); }}><textarea aria-label="练习输入" placeholder={archivedReadOnly ? "归档对话只读，请先恢复" : currentTurn ? "回答当前问题，或告诉我下一步想做什么…" : "例如：围绕我的实习项目，生成 5 个问题…"} value={draft} onChange={e => updateDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} readOnly={archivedReadOnly} /><button aria-label="发送消息" type="submit" disabled={archivedReadOnly || !draft.trim() || busy || !materialSetId}><ArrowUp size={20} /></button></form><small className="chat-composer-hint">Enter 发送 · Shift + Enter 换行<span>普通回答只保存，请求点评后才反馈</span></small>
      </div>
    </div>
    {panel === "resume" && <aside className="chat-detail-panel" role="region" aria-label="对话简历"><header><div><small>对话绑定版本</small><h2>简历与原文依据</h2></div><button aria-label="关闭简历" onClick={() => setPanel(null)}><X size={18} /></button></header><div className="chat-detail-scroll">{snapshots.isPending && <p>正在读取简历…</p>}{snapshots.isError && <p role="alert">简历读取失败，请重试。</p>}{snapshots.data && <><small className="snapshot-version">材料版本 {snapshots.data.revisionId.slice(0, 8)}</small>{!snapshots.data.resumes.length && <p>此历史对话缺少可恢复的简历快照，不以最新简历代替。</p>}<ResumeReader resumes={snapshots.data.resumes} /><div className="snapshot-edit"><p>修改当前简历不会改变这个对话的历史快照。</p><button onClick={onEditResume}>编辑当前简历 <ChevronRight size={13} /></button></div></>}</div></aside>}
    {panel === "preferences" && <aside className="chat-detail-panel" role="region" aria-label="练习偏好"><header><div><small>跨对话沿用</small><h2>练习偏好</h2></div><button aria-label="关闭偏好" onClick={() => setPanel(null)}><X size={18} /></button></header><div className="chat-detail-scroll"><p className="preference-intro">仅保存你明确要求长期沿用的练习方式。当前指令和本轮要求优先。</p>{preferences.isPending && <p>正在读取偏好…</p>}{preferences.data?.map(p => <PreferenceEditor key={`${p.id}:${p.revision}`} preference={p} onSave={value => editPreference.mutate({ preference: p, value })} onRemove={() => removePreference.mutate(p.id)} pending={removePreference.isPending || editPreference.isPending} />)}{preferences.data?.length === 0 && <p>暂无长期练习偏好</p>}</div></aside>}
  </section>;
}

function MessageBubble({ message: m }: { message: PracticeMessage }) {
  if (m.messageType === "answer") return <div className="chat-answer-record" data-message-type="answer">已保存为回答 v{m.answerVersion ?? 1}</div>;
  const labels: Record<string, string> = { question: "面试问题", feedback: "回答反馈", referenceAnswer: "参考答案", followUp: "继续追问", clarification: "需要你确认" };
  return <article className={`chat-message ${m.role === "user" ? "candidate" : "assistant"} ${m.messageType === "status" ? "system-note" : ""}`} data-message-type={m.messageType}>{m.role !== "user" && <span className="chat-message-label">{labels[m.messageType] ?? "练习助手"}</span>}<p>{m.content}</p>{m.result?.missingPoints?.length ? <div className="chat-feedback-points"><b>可以补充</b><ul>{m.result.missingPoints.map((p, i) => <li key={i}>{p}</li>)}</ul>{m.result.nextPracticeStep && <p>{m.result.nextPracticeStep}</p>}</div> : null}{m.result?.limitations?.map((l, i) => <small className="chat-limitation" key={i}>{l}</small>)}</article>;
}
function ResumeReader({ resumes }: { resumes: ResumeSnapshot[] }) {
  const [selected, setSelected] = useState("");
  const resume = resumes.find(r => r.materialId === selected) ?? resumes[0];
  if (!resume) return null;
  return <><label className="snapshot-file">简历文件<select value={resume.materialId} onChange={e => setSelected(e.target.value)}>{resumes.map(r => <option key={r.materialId} value={r.materialId}>{r.filename}</option>)}</select></label>{Object.entries(sectionNames).map(([key, name]) => <section className="snapshot-section" key={key}><h3>{name}</h3>{resume.sections[key as keyof typeof resume.sections] ? <SectionContent value={resume.sections[key as keyof typeof resume.sections]} /> : <p className="snapshot-unconfirmed">创建此对话时未确认该章节</p>}</section>)}<details className="snapshot-evidence"><summary>查看只读原文依据</summary>{resume.evidence.map(e => <section key={e.id}><small>{e.pageNumber ? `第 ${e.pageNumber} 页` : "段落原文"}</small><p>{e.content}</p></section>)}</details></>;
}
function SectionContent({ value }: { value: unknown }) {
  if (Array.isArray(value)) return <>{value.map((v, i) => <div className="snapshot-entry" key={i}><b>{v.company || v.name}</b><small>{[v.role, v.timeRange, v.startDate, v.endDate].filter(Boolean).join(" · ")}</small><p>{v.description}</p></div>)}</>;
  if (value && typeof value === "object") { const data = value as Record<string, unknown>; if (typeof data.content === "string") return <p>{data.content}</p>; return <dl>{Object.entries(data).filter(([key]) => !["confidence", "evidenceIds", "edited"].includes(key)).map(([key, v]) => v ? <div key={key}><dt>{({ name: "姓名", phone: "手机号", email: "邮箱", city: "城市", targetRole: "求职方向", links: "外部链接" } as Record<string, string>)[key] ?? key}</dt><dd>{Array.isArray(v) ? v.join("、") : String(v)}</dd></div> : null)}</dl>; }
  return null;
}
function PreferenceEditor({ preference: p, onSave, onRemove, pending }: { preference: PracticePreference; onSave: (value: string | number) => void; onRemove: () => void; pending: boolean }) {
  const [value, setValue] = useState(String(p.value));
  const label = ({ count: "每组题数", topic: "练习主题", questionType: "问题类型", direction: "练习方向" } as Record<string, string>)[p.key] ?? p.key;
  return <section className="preference-item"><b>{label}：{p.value}</b><input aria-label={`修改偏好 ${p.key}`} value={value} onChange={e => setValue(e.target.value)} type={p.key === "count" ? "number" : "text"} min={1} max={20} /><div><button onClick={() => onSave(p.key === "count" ? Number(value) : value)} disabled={pending || value === String(p.value)}>保存修改</button><button aria-label={`撤销偏好 ${p.key}`} onClick={onRemove} disabled={pending}>撤销偏好</button></div></section>;
}
