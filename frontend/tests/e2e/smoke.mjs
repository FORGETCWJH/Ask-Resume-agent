const base = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const frontend = process.env.FRONTEND_BASE_URL ?? "http://127.0.0.1:5173";

async function waitForRecognition(materialId, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastBody;
  while (Date.now() < deadline) {
    const response = await fetch(`${base}/api/v1/materials/${materialId}/recognition`);
    if (response.status !== 200) throw new Error(`recognition failed: ${response.status}`);
    lastBody = await response.json();
    if (lastBody.recognitionStatus === "awaitingConfirmation" || lastBody.recognitionStatus === "confirmed") return lastBody;
    if (lastBody.recognitionStatus === "failed") throw new Error(`recognition failed: ${JSON.stringify(lastBody.warnings ?? [])}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`recognition timeout: ${JSON.stringify(lastBody ?? {})}`);
}

async function waitForRun(runId, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastBody;
  while (Date.now() < deadline) {
    const response = await fetch(`${base}/api/v1/llm-runs/${runId}`);
    if (response.status !== 200) throw new Error(`run status failed: ${response.status}`);
    lastBody = await response.json();
    if (["succeeded", "failed", "cancelled"].includes(lastBody.status)) return lastBody;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`run timeout: ${JSON.stringify(lastBody ?? {})}`);
}

function resumePdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    "<< /Length 155 >>\nstream\nBT /F1 14 Tf 50 700 Td (Skills: Python, FastAPI, SQLAlchemy) Tj 0 -24 Td (Project Experience: API platform) Tj 0 -24 Td (Internship: Backend Engineer) Tj ET\nendstream",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(body.length);
    body += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return new TextEncoder().encode(body);
}

const page = await fetch(frontend);
const shell = await page.text();
if (page.status !== 200 || (!shell.includes("/src/main.tsx") && !shell.includes("/assets/"))) throw new Error("frontend server is not serving the app shell");

const create = await fetch(`${base}/api/v1/material-sets`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ title: "端到端临时集合" }),
});
if (create.status !== 201) throw new Error(`create failed: ${create.status}`);
const item = await create.json();
try {
  const health = await fetch(`${base}/api/v1/health`);
  if (health.status !== 200) throw new Error(`health failed: ${health.status}`);
  const list = await fetch(`${base}/api/v1/material-sets`);
  if (list.status !== 200) throw new Error(`list failed: ${list.status}`);
  if (!(await list.json()).some((entry) => entry.id === item.id)) throw new Error("created set missing from list");

  const form = new FormData();
  form.append("file", new Blob([resumePdf()], { type: "application/pdf" }), "resume.pdf");
  const upload = await fetch(`${base}/api/v1/material-sets/${item.id}/materials?kind=resume`, { method: "POST", body: form });
  if (upload.status !== 202) throw new Error(`resume upload failed: ${upload.status}`);
  const uploaded = await upload.json();
  const resume = uploaded.materials.find((material) => material.kind === "resume");
  if (!resume) throw new Error("resume material missing");
  const recognitionBody = await waitForRecognition(resume.id);
  if (!("personalInfo" in recognitionBody.draft && "skills" in recognitionBody.draft && "workExperiences" in recognitionBody.draft && "projects" in recognitionBody.draft)) throw new Error("recognition sections missing");
  if (typeof recognitionBody.draft.skills !== "object" || typeof recognitionBody.draft.skills.content !== "string") throw new Error("skills must be one complete content object");
  if (recognitionBody.draft.workExperiences.some((item) => "projects" in item || "rawText" in item)) throw new Error("legacy nested work fields remain");
  if (recognitionBody.draft.projects.some((item) => "metrics" in item || "contributions" in item)) throw new Error("legacy project split fields remain");
  const editedDraft = { ...recognitionBody.draft, skills: { content: "后端开发：Python、FastAPI", evidenceIds: recognitionBody.draft.skills.evidenceIds ?? [], edited: true } };
  const saved = await fetch(`${base}/api/v1/materials/${resume.id}/recognition`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ draft: editedDraft }) });
  if (saved.status !== 200) throw new Error(`recognition save failed: ${saved.status}`);
  const confirmed = await fetch(`${base}/api/v1/materials/${resume.id}/recognition/confirm`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ section: "skills" }) });
  if (confirmed.status !== 200 || !(await confirmed.json()).confirmedSections.includes("skills")) throw new Error("recognition confirm failed");
  const conversationCreate = await fetch(`${base}/api/v1/material-sets/${item.id}/conversations`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "端到端练习" }) });
  if (conversationCreate.status !== 201) throw new Error(`conversation create failed: ${conversationCreate.status}`);
  const conversation = await conversationCreate.json();
  const questionRunResponse = await fetch(`${base}/api/v1/conversations/${conversation.id}/question-runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ resumeSections: ["skills"], direction: "实现细节", count: 1 }) });
  if (questionRunResponse.status !== 202) throw new Error(`question run failed: ${questionRunResponse.status}`);
  const questionRun = await questionRunResponse.json();
  const questionDone = await waitForRun(questionRun.runId);
  if (questionDone.status !== "succeeded") throw new Error(`question run did not succeed: ${JSON.stringify(questionDone)}`);
  const turnsResponse = await fetch(`${base}/api/v1/conversations/${conversation.id}/practice-turns`);
  const turns = await turnsResponse.json();
  if (!turns.items?.length) throw new Error("practice turns missing");
  const answer = await fetch(`${base}/api/v1/practice-turns/${turns.items[0].id}/answers`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content: "我负责了接口设计。" }) });
  if (answer.status !== 201) throw new Error(`answer save failed: ${answer.status}`);
  const removed = await fetch(`${base}/api/v1/materials/${resume.id}`, { method: "DELETE" });
  if (removed.status !== 204) throw new Error(`single material delete failed: ${removed.status}`);
  const afterRemoval = await fetch(`${base}/api/v1/material-sets/${item.id}`);
  if (afterRemoval.status !== 200 || (await afterRemoval.json()).materials.some((material) => material.id === resume.id)) throw new Error("deleted material remains in active revision");
} finally {
  const deleted = await fetch(`${base}/api/v1/material-sets/${item.id}`, { method: "DELETE" });
  if (deleted.status !== 204) throw new Error(`delete failed: ${deleted.status}`);
}
console.log("e2e smoke passed");
