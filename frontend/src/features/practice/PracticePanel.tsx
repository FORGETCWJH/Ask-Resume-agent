import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleHelp, Code2, LoaderCircle, MessageSquare, Play, Plus, RefreshCw, Save, Sparkles } from "lucide-react";
import { api } from "../../api/client";
import type { LlmRun, Material, PracticeConversation, PracticeTurn, QuestionScope } from "../../types/api";

type Props = { materialSetId?: string; projects: Material[]; conversationId: string | null; onConversationId: (id: string | null) => void };

export function PracticePanel({ materialSetId, projects, conversationId, onConversationId }: Props) {
  const client = useQueryClient();
  const [scope, setScope] = useState<QuestionScope>({ projectIds: [], resumeSections: ["skills", "workExperiences", "projects"], direction: "实现细节与技术取舍", questionType: "implementation", difficulty: "intermediate", count: 5 });
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [showCustomTopic, setShowCustomTopic] = useState(false);

  const conversationsQuery = useQuery({
    queryKey: ["practice-conversations", materialSetId],
    queryFn: () => api<PracticeConversation[]>(`/api/v1/material-sets/${materialSetId}/conversations`),
    enabled: Boolean(materialSetId),
  });
  const conversations = conversationsQuery.data ?? [];
  useEffect(() => {
    if (!materialSetId || conversationId) return;
    const remembered = window.localStorage.getItem(`practice-conversation:${materialSetId}`);
    const candidate = conversations.find((item) => item.id === remembered) ?? conversations[0];
    if (candidate) onConversationId(candidate.id);
  }, [materialSetId, conversationId, conversations, onConversationId]);
  useEffect(() => {
    if (materialSetId && conversationId) window.localStorage.setItem(`practice-conversation:${materialSetId}`, conversationId);
  }, [materialSetId, conversationId]);

  const turnsQuery = useQuery({
    queryKey: ["practice-turns", conversationId],
    queryFn: () => api<{ items: PracticeTurn[] }>(`/api/v1/conversations/${conversationId}/practice-turns`),
    enabled: Boolean(conversationId),
  });
  const runQuery = useQuery({
    queryKey: ["llm-run", activeRunId],
    queryFn: () => api<LlmRun>(`/api/v1/llm-runs/${activeRunId}`),
    enabled: Boolean(activeRunId),
    refetchInterval: (query) => query.state.data && ["succeeded", "failed", "cancelled"].includes(query.state.data.status) ? false : 700,
  });
  useEffect(() => {
    const run = runQuery.data;
    if (!run || !activeRunId || !["succeeded", "failed", "cancelled"].includes(run.status)) return;
    if (run.status === "succeeded") {
      client.invalidateQueries({ queryKey: ["practice-turns", conversationId] });
      client.invalidateQueries({ queryKey: ["practice-conversations", materialSetId] });
      setNotice(run.kind === "reference_answer" ? "参考答案已生成" : run.kind === "feedback" ? "反馈已生成" : run.kind === "follow_up" ? "下一条追问已生成" : "问题已生成");
    } else setNotice(run.error ?? "任务未完成，请重试");
    setActiveRunId(null);
  }, [runQuery.data, activeRunId, client, conversationId, materialSetId]);

  const createQuestion = useMutation<{ runId: string }, Error, boolean>({
    mutationFn: async (newVersion = false) => {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        if (!materialSetId) throw new Error("请先选择材料集合");
        const conversation = await api<{ id: string }>(`/api/v1/material-sets/${materialSetId}/conversations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "面试练习" }) });
        currentConversationId = conversation.id;
        onConversationId(currentConversationId);
      }
      return api<{ runId: string }>(`/api/v1/conversations/${currentConversationId}/question-runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...scope, newVersion }) });
    },
    onSuccess: (run) => { setActiveRunId(run.runId); setNotice("已提交生成任务，正在准备问题"); },
    onError: (error) => setNotice(error instanceof Error ? error.message : "生成任务提交失败"),
  });
  const saveAnswer = useMutation({
    mutationFn: ({ turnId, content }: { turnId: string; content: string }) => api(`/api/v1/practice-turns/${turnId}/answers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) }),
    onSuccess: (_, variables) => { client.invalidateQueries({ queryKey: ["practice-turns", conversationId] }); setNotice("回答已提交，不会触发模型调用"); setAnswers((current) => ({ ...current, [variables.turnId]: "" })); },
  });
  const referenceAnswer = useMutation<{ runId: string }, Error, string>({ mutationFn: (turnId) => api<{ runId: string }>(`/api/v1/practice-turns/${turnId}/reference-answer-runs`, { method: "POST" }), onSuccess: (run, turnId) => { setActiveTurnId(turnId); setActiveRunId(run.runId); setNotice("已提交参考答案任务"); } });
  const feedbackRun = useMutation<{ runId: string }, Error, string>({ mutationFn: (turnId) => api<{ runId: string }>(`/api/v1/practice-turns/${turnId}/feedback-runs`, { method: "POST" }), onSuccess: (run, turnId) => { setActiveTurnId(turnId); setActiveRunId(run.runId); setNotice("已提交反馈任务"); } });
  const followUpRun = useMutation<{ runId: string }, Error, string>({ mutationFn: (turnId) => api<{ runId: string }>(`/api/v1/practice-turns/${turnId}/follow-up-runs`, { method: "POST" }), onSuccess: (run, turnId) => { setActiveTurnId(turnId); setActiveRunId(run.runId); setNotice("已提交继续追问任务"); } });
  const turns = turnsQuery.data?.items ?? [];

  function toggleSection(section: string) {
    setScope((current) => ({ ...current, resumeSections: current.resumeSections.includes(section) ? current.resumeSections.filter((item) => item !== section) : [...current.resumeSections, section] }));
  }

  function selectConversation(id: string) {
    onConversationId(id);
    setActiveRunId(null);
    setActiveTurnId(null);
  }

  return <section className="practice-page page-stack">
    <div className="page-heading compact-heading"><div><span className="eyebrow">INTERVIEW PRACTICE</span><h2>面试练习</h2><p>选择范围后生成问题；回答、反馈、参考答案和追问分别由你主动触发。</p></div><div className="practice-heading-actions"><button className="secondary-button" onClick={() => { onConversationId(null); setNotice("下一次生成会创建新的对话"); }}><Plus size={14} />新建对话</button><button className="primary-button" onClick={() => createQuestion.mutate(false)} disabled={createQuestion.isPending || Boolean(activeRunId)}><Play size={15} />生成问题</button></div></div>
    <div className="practice-layout">
      <aside className="practice-scope">
        <div className="practice-section-label">历史对话</div>
        <div className="conversation-list">{conversations.map((item) => <button key={item.id} className={`conversation-item ${item.id === conversationId ? "active" : ""}`} onClick={() => selectConversation(item.id)}><MessageSquare size={14} /><span>{item.title}</span></button>)}{!conversations.length && <small>生成第一组问题后会自动创建对话</small>}</div>
        <div className="practice-section-label">问题范围</div>
        <div className="scope-block"><span>简历模块</span>{[["skills", "技能掌握"], ["workExperiences", "实习经历"], ["projects", "项目经验"]].map(([value, label]) => <label className="scope-check" key={value}><input type="checkbox" checked={scope.resumeSections.includes(value)} onChange={() => toggleSection(value)} /><span>{label}</span></label>)}</div>
        {projects.length > 0 && <div className="scope-block"><span>绑定项目档案</span>{projects.map((project) => <label className="scope-check" key={project.id}><input type="checkbox" checked={scope.projectIds.includes(project.id)} onChange={() => setScope((current) => ({ ...current, projectIds: current.projectIds.includes(project.id) ? current.projectIds.filter((id) => id !== project.id) : [...current.projectIds, project.id] }))} /><span>{project.filename}</span></label>)}</div>}
        <label className="scope-field"><span>问题类型</span><select value={scope.questionType ?? ""} onChange={(event) => setScope((current) => ({ ...current, questionType: event.target.value || undefined }))}><option value="">不限</option><option value="implementation">实现细节</option><option value="tradeoff">方案权衡</option><option value="troubleshooting">问题排查</option><option value="systemDesign">系统设计</option></select></label>
        <label className="scope-field"><span>难度</span><select value={scope.difficulty ?? ""} onChange={(event) => setScope((current) => ({ ...current, difficulty: event.target.value || undefined }))}><option value="">不限</option><option value="basic">基础</option><option value="intermediate">进阶</option><option value="advanced">高级</option></select></label>
        <label className="scope-field"><span>练习方向</span><input value={scope.direction ?? ""} onChange={(event) => setScope((current) => ({ ...current, direction: event.target.value }))} placeholder="例如：缓存一致性与失败处理" /></label>
        <button className="link-button" onClick={() => setShowCustomTopic((value) => !value)}>{showCustomTopic ? "收起自定义主题" : "添加自定义主题"}</button>
        {showCustomTopic && <label className="scope-field"><span>自定义主题</span><textarea value={scope.topic ?? ""} onChange={(event) => setScope((current) => ({ ...current, topic: event.target.value }))} placeholder="模型会围绕此主题生成问题" /></label>}
        <label className="scope-field"><span>问题数量</span><select value={scope.count} onChange={(event) => setScope((current) => ({ ...current, count: Number(event.target.value) }))}><option value={3}>3 个</option><option value={5}>5 个</option><option value={8}>8 个</option></select></label>
        <div className="scope-note"><Sparkles size={14} />问题文本由模型生成，候选人只能调整范围。</div>
      </aside>
      <div className="practice-turns">{activeRunId && <div className="run-banner"><LoaderCircle size={15} className="spin" /><span>{runQuery.data?.status === "running" ? "模型正在处理" : "任务排队中"}</span><small>长链路不会阻塞当前页面</small></div>}{!conversationId && !turns.length && <div className="practice-empty"><CircleHelp size={24} /><strong>还没有练习问题</strong><span>选好范围后点击“生成问题”，问题生成才会开始。</span></div>}{turns.map((turn, index) => <PracticeTurnCard key={turn.id} turn={turn} index={index} answer={answers[turn.id] ?? turn.answer ?? ""} onAnswer={(content) => setAnswers((current) => ({ ...current, [turn.id]: content }))} onSave={() => saveAnswer.mutate({ turnId: turn.id, content: answers[turn.id] ?? turn.answer ?? "" })} onReference={() => { setActiveTurnId(turn.id); referenceAnswer.mutate(turn.id); }} onFeedback={() => { setActiveTurnId(turn.id); feedbackRun.mutate(turn.id); }} onFollowUp={() => { setActiveTurnId(turn.id); followUpRun.mutate(turn.id); }} referencePending={activeTurnId === turn.id && Boolean(activeRunId)} />)}</div>
    </div>
    {notice && <div className="practice-notice">{notice}</div>}
  </section>;
}

function PracticeTurnCard({ turn, index, answer, onAnswer, onSave, onReference, onFeedback, onFollowUp, referencePending }: { turn: PracticeTurn; index: number; answer: string; onAnswer: (value: string) => void; onSave: () => void; onReference: () => void; onFeedback: () => void; onFollowUp: () => void; referencePending: boolean }) {
  return <article className="practice-turn"><div className="practice-turn-heading"><span className="turn-number">{String(index + 1).padStart(2, "0")}</span><div><span className="eyebrow">QUESTION</span><h3>{turn.question}</h3>{turn.parentTurnId && <small className="follow-up-label">基于上一轮回答的追问</small>}</div></div><label className="answer-field"><span>你的回答</span><textarea value={answer} onChange={(event) => onAnswer(event.target.value)} placeholder="用自己的话回答，尽量说明你亲自负责的部分……" /></label><div className="turn-actions"><button className="secondary-button" onClick={onSave} disabled={!answer.trim()}><Save size={14} />提交回答</button><button className="secondary-button" onClick={onFeedback} disabled={!turn.answer || referencePending}><Sparkles size={14} />查看反馈</button><button className="secondary-button" onClick={onReference} disabled={!turn.answer || referencePending}><Code2 size={14} />{referencePending ? "处理中" : "查看参考答案"}</button><button className="secondary-button" onClick={onFollowUp} disabled={!turn.answer || referencePending}><MessageSquare size={14} />继续追问</button>{turn.answer && <span className="saved-label"><Check size={13} />已提交第 {turn.answerVersion ?? 1} 版</span>}</div>{turn.feedback && <div className="feedback-card"><div className="reference-heading"><Sparkles size={14} /><strong>回答反馈</strong></div><p>{turn.feedback.summary}</p>{turn.feedback.missingPoints?.map((item) => <small key={item}>待补充：{item}</small>)}{turn.feedback.nextPracticeStep && <small>下一步：{turn.feedback.nextPracticeStep}</small>}</div>}{turn.referenceAnswer && <div className="reference-answer"><div className="reference-heading"><MessageSquare size={14} /><strong>参考答案</strong><span className={`evidence-grade ${turn.referenceAnswer.evidenceGrade}`}>{turn.referenceAnswer.evidenceGrade}</span></div><p>{turn.referenceAnswer.answer}</p><small>{turn.referenceAnswer.limitations?.join("；") ?? "当前没有可展示的代码证据"}</small></div>}</article>;
}
