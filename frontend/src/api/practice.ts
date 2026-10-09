import { api } from "./client";
import type { ConversationGroup, PracticeConversation, PracticeState, PracticeMessage, PracticePreference, ResumeSnapshots, PracticeTurn, LlmRun } from "../types/api";
const post = (body?: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
export const practiceApi = {
  conversations: (setId: string, params: { status?: "active" | "archived" | "all"; q?: string; groupId?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.status) search.set("status", params.status);
    if (params.q?.trim()) search.set("q", params.q.trim());
    if (params.groupId) search.set("groupId", params.groupId);
    return api<PracticeConversation[]>(`/api/v1/material-sets/${setId}/conversations${search.size ? `?${search}` : ""}`);
  },
  groups: (setId: string) => api<ConversationGroup[]>(`/api/v1/material-sets/${setId}/conversation-groups`),
  createGroup: (setId: string, name: string) => api<ConversationGroup>(`/api/v1/material-sets/${setId}/conversation-groups`, post({ name })),
  renameGroup: (id: string, name: string) => api<ConversationGroup>(`/api/v1/conversation-groups/${id}`, { ...post({ name }), method: "PATCH" }),
  deleteGroup: (id: string) => api(`/api/v1/conversation-groups/${id}`, { method: "DELETE" }),
  updateConversation: (id: string, patch: { title?: string; isPinned?: boolean; groupId?: string | null; isArchived?: boolean }) => api<PracticeConversation>(`/api/v1/conversations/${id}`, { ...post(patch), method: "PATCH" }),
  deleteConversation: (id: string) => api(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  create: (setId: string) => api<PracticeConversation>(`/api/v1/material-sets/${setId}/conversations`, post({ title: "面试练习" })),
  state: (id: string) => api<PracticeState>(`/api/v1/conversations/${id}/practice-state`),
  messages: async (id: string): Promise<PracticeMessage[]> => {
    const items: PracticeMessage[] = [];
    let after = 0;
    do {
      const page = await api<{ items: PracticeMessage[]; nextAfterSequence: number | null }>(`/api/v1/conversations/${id}/practice-messages?afterSequence=${after}&limit=200`);
      items.push(...page.items);
      if (page.nextAfterSequence === null) break;
      after = page.nextAfterSequence;
    } while (true);
    return items;
  },
  turns: (id: string) => api<{ items: PracticeTurn[] }>(`/api/v1/conversations/${id}/practice-turns`),
  input: (id: string, content: string, clientRequestId: string) => api<{ runId: string }>(`/api/v1/conversations/${id}/input-runs`, post({ content, clientRequestId })),
  next: (id: string) => api<PracticeState>(`/api/v1/conversations/${id}/navigation-events`, post({ action: "nextQuestion", clientRequestId: crypto.randomUUID() })),
  action: (turnId: string, action: "feedback" | "reference-answer" | "follow-up") => api<{ runId: string }>(`/api/v1/practice-turns/${turnId}/${action}-runs`, post()),
  run: (id: string) => api<LlmRun>(`/api/v1/llm-runs/${id}`),
  retry: (id: string) => api<{ runId: string }>(`/api/v1/llm-runs/${id}/retry`, post()),
  cancel: (id: string) => api<LlmRun>(`/api/v1/llm-runs/${id}/cancel`, post()),
  snapshots: (id: string) => api<ResumeSnapshots>(`/api/v1/conversations/${id}/resume-snapshots`),
  preferences: () => api<PracticePreference[]>("/api/v1/practice-preferences"),
  updatePreference: (p: PracticePreference, value: string | number) => api<PracticePreference>(`/api/v1/practice-preferences/${p.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value, expectedRevision: p.revision }) }),
  deletePreference: (id: string) => api(`/api/v1/practice-preferences/${id}`, { method: "DELETE" }),
};
