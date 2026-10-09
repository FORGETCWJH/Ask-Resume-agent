import { readFile } from "node:fs/promises";

const app = await readFile(new URL("../../src/App.tsx", import.meta.url), "utf8");
const panel = await readFile(new URL("../../src/features/resume-recognition/ResumeRecognitionPanel.tsx", import.meta.url), "utf8");

for (const label of ["总览", "材料库", "简历确认", "面试练习"]) {
  if (!app.includes(label)) throw new Error(`missing OCR navigation: ${label}`);
}
if (!panel.includes('refetchInterval')) throw new Error("recognition status polling is missing");
if (app.includes("生成 8 个问题") || app.includes("generateQuestions")) throw new Error("question generation must stay out of OCR phase");
if (app.includes("/conversations/") || app.includes("sendMessage")) throw new Error("conversation actions must stay out of OCR phase");
if (!app.includes("/api/v1/materials/") || !app.includes("删除材料")) throw new Error("single material delete action is missing");
if (!app.includes("hashchange") || !app.includes("#/")) throw new Error("hash navigation is missing");
if (!app.includes("evidence-pane")) throw new Error("fixed evidence pane is missing");
if (!panel.includes("recognition-nav") || !panel.includes("删除记录")) throw new Error("structured recognition navigation/actions are missing");
if (!panel.includes("完整技能描述") || !panel.includes("经历描述") || !panel.includes("项目描述")) throw new Error("compact description fields are missing");
if (panel.includes("skill-tags") || panel.includes("nested-project") || panel.includes("成果指标") || panel.includes("metrics")) throw new Error("legacy split recognition fields are still rendered");
// 练习交互由 conversation-browser.mjs 在真实浏览器验证，不断言旧表单源码。
console.log("ocr ui contract passed");
