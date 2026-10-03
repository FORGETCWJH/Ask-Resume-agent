export type Material = { id: string; kind: string; filename: string; status: string; sizeBytes: number; errorMessage?: string | null };
export type MaterialSet = { id: string; title: string; activeRevisionId: string | null; materials: Material[] };
export type Evidence = { id: string; content: string; materialId?: string | null; sourcePath?: string | null; pageNumber?: number | null; lineStart?: number | null; lineEnd?: number | null };
export type ResponseShape = {
  answer: string;
  questions: { text: string; type?: string; evidenceIds?: string[] }[];
  evidence: { evidenceId: string; quote: string; location: string }[];
  inferenceDrafts: { text: string; reason?: string; requiresConfirmation?: boolean }[];
  evidenceGaps: { question: string; missingDetail?: string; supplementId?: string }[];
  feedback?: { strengths?: string[]; missingPoints?: string[]; nextPracticeStep?: string } | null;
};
export type ChatMessage = { id: string; role: "user" | "assistant"; content: string; response?: ResponseShape | null };
export type Conversation = { id: string; revisionId: string; title: string; summary: string; messages: ChatMessage[] };

export type RecognitionSection = "personalInfo" | "skills" | "workExperiences" | "projects";
export type PersonalInfoDraft = { name: string; phone: string; email: string; city: string; targetRole: string; links: string[]; evidenceIds?: string[]; confidence?: number };
export type SkillDraft = { content: string; evidenceIds: string[]; confidence?: number; edited?: boolean };
export type WorkExperienceDraft = { company: string; role: string; startDate: string; endDate: string; experienceType: string; description: string; evidenceIds: string[]; confidence?: number; edited?: boolean };
export type ResumeProjectDraft = { name: string; timeRange: string; role: string; technologies: string[]; description: string; links: string[]; projectArchiveId: string | null; evidenceIds: string[]; confidence?: number; edited?: boolean };
export type RecognitionDraft = { personalInfo: PersonalInfoDraft; skills: SkillDraft; workExperiences: WorkExperienceDraft[]; projects: ResumeProjectDraft[] };
export type RecognitionResponse = {
  materialId: string;
  revisionId: string;
  materialStatus: string;
  recognitionStatus: string;
  draft: RecognitionDraft;
  warnings: { code?: string; message?: string }[];
  confirmedSections: RecognitionSection[];
  evidenceLinks: Record<string, string[]>;
};
