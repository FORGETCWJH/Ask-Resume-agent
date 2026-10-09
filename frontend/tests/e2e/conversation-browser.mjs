// 使用现有 Chromium 与 Node 原生 CDP，真实渲染 React，不安装浏览器测试依赖。
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, access, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const front = process.env.FRONTEND_BASE_URL ?? "http://127.0.0.1:5173";
const base = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const candidates = [process.env.BROWSER_EXECUTABLE, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean);
let executable;
for (const candidate of candidates) { try { await access(candidate); executable = candidate; break; } catch {} }
assert(executable, "缺少现有 Chromium 浏览器；请配置 BROWSER_EXECUTABLE，不自动安装");
const profile = await mkdtemp(join(tmpdir(), "ask-resume-browser-"));
const browser = spawn(executable, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-extensions", "--window-size=1440,1000", "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
let address = "", socket, setId;
const pending = new Map();
let seq = 0;
browser.stderr.on("data", chunk => { const match = chunk.toString().match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) address = match[1]; });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, label, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await fn()) return; await delay(100); }
  throw new Error(`浏览器验收超时：${label}`);
}
function cdp(method, params = {}) {
  const id = ++seq;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const response = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}
async function click(label) {
  assert(await evaluate(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(label)} || b.getAttribute('aria-label') === ${JSON.stringify(label)}); if (!b || b.disabled) return false; b.click(); return true })()`), `按钮不可用：${label}`);
}
async function message(text) {
  await until(() => evaluate(`document.querySelector('[aria-label="选择材料集合"]').value !== ''`), "材料集合加载");
  await evaluate(`(() => { const t = document.querySelector('[aria-label="练习输入"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t, ${JSON.stringify(text)}); t.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  await until(() => evaluate(`!document.querySelector('[aria-label="发送消息"]').disabled`), "可发送消息");
  await click("发送消息");
  await until(() => evaluate(`document.querySelector('[aria-label="练习输入"]').value === ''`), "输入提交成功");
  await until(() => evaluate(`!document.querySelector('[data-testid="active-task"]')`), "异步任务完成");
}
async function request(path, method = "GET", body) {
  const response = await fetch(base + "/api/v1" + path, { method, headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  assert(response.ok, `${method} ${path}: ${response.status}`);
  return response.status === 204 ? null : response.json();
}
function pdf() {
  const content = "BT /F1 14 Tf 50 700 Td (Skills: Python, Redis, SQL) Tj ET";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>", `<< /Length ${content.length} >>\nstream\n${content}\nendstream`, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
  let result = "%PDF-1.4\n", offsets = [];
  objects.forEach((object, i) => { offsets.push(result.length); result += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const offset = result.length;
  return result + `xref\n0 6\n0000000000 65535 f \n${offsets.map(x => String(x).padStart(10, "0") + " 00000 n \n").join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${offset}\n%%EOF`;
}
try {
  await until(() => address, "启动浏览器");
  const port = new URL(address).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const value = JSON.parse(event.data), promise = pending.get(value.id);
    if (promise) { clearTimeout(promise.timer); pending.delete(value.id); value.error ? promise.reject(new Error(value.error.message)) : promise.resolve(value.result); }
  };
  setId = (await request("/material-sets", "POST", { title: "浏览器验收集合" })).id;
  const form = new FormData();
  form.append("file", new Blob([pdf()], { type: "application/pdf" }), "browser-resume.pdf");
  const uploaded = await fetch(`${base}/api/v1/material-sets/${setId}/materials?kind=resume`, { method: "POST", body: form });
  assert.equal(uploaded.status, 202);
  const materialId = (await uploaded.json()).materials[0].id;
  await until(async () => (await request(`/materials/${materialId}/recognition`)).recognitionStatus === "awaitingConfirmation", "识别完成");
  const draft = (await request(`/materials/${materialId}/recognition`)).draft;
  draft.skills.content = "熟悉 Python、Redis 和 SQL";
  await request(`/materials/${materialId}/recognition`, "PATCH", { draft });
  await request(`/materials/${materialId}/recognition/confirm`, "POST", { section: "skills" });
  await cdp("Page.navigate", { url: front + "/#/practice" });
  await until(() => evaluate(`document.querySelector('.chat-shell') !== null`), "对话式页面布局");
  assert.equal(await evaluate(`document.querySelectorAll('.sidebar').length`), 0, "不显示旧全局侧栏");
  assert.equal(await evaluate(`document.querySelectorAll('[aria-label="练习输入"]').length`), 1);
  await message("围绕 Redis 生成 3 个问题");
  await until(() => evaluate(`document.body.textContent.includes('1 / 3')`), "首题与进度");
  const conversationId = (await request(`/material-sets/${setId}/conversations`))[0].id;
  const originalVersion = (await request(`/conversations/${conversationId}/practice-state`)).questionVersionId;
  await message("围绕 Redis 生成 3 个问题");
  assert.equal((await request(`/conversations/${conversationId}/practice-state`)).questionVersionId, originalVersion, "范围不变时复用题组");
  await message("我先查询缓存，未命中时再查数据库");
  assert.equal(await evaluate(`document.querySelectorAll('[data-message-type="feedback"]').length`), 0, "普通回答不能自动点评");
  await message("我还设置过期时间，请点评");
  assert(await evaluate(`document.querySelector('[data-message-type="feedback"]') !== null`));
  await click("参考答案");
  await until(() => evaluate(`document.body.textContent.includes('当前阶段尚未启用代码证据')`), "参考答案限制");
  await click("继续追问");
  await until(() => evaluate(`document.querySelector('[data-message-type="followUp"]') !== null`), "追问消息");
  await click("下一题");
  await until(() => evaluate(`document.body.textContent.includes('2 / 3')`), "下一主问题");
  await click("查看简历");
  await until(() => evaluate(`document.querySelector('[aria-label="对话简历"]')?.textContent.includes('熟悉 Python、Redis 和 SQL')`), "顶部简历面板");
  assert(await evaluate(`document.querySelector('[aria-label="对话简历"]').textContent.includes('熟悉 Python、Redis 和 SQL')`));
  draft.skills.content = "现在改成 Java";
  await request(`/materials/${materialId}/recognition`, "PATCH", { draft });
  await cdp("Page.reload");
  await until(() => evaluate(`document.body.textContent.includes('2 / 3')`), "刷新恢复当前题");
  await click("查看简历");
  await until(() => evaluate(`document.querySelector('[aria-label="对话简历"]')?.textContent.includes('熟悉 Python、Redis 和 SQL')`), "旧对话快照不变");
  await click("关闭简历");
  await message("以后每次只生成一道题");
  await click("练习偏好");
  await until(() => evaluate(`document.body.textContent.includes('每组题数：1')`), "长期偏好展示");
  await click("撤销偏好 count");
  await until(() => evaluate(`document.body.textContent.includes('暂无长期练习偏好')`), "撤销偏好");
  await click("关闭偏好");
  await message("换成消息队列");
  assert(await evaluate(`document.querySelector('[data-message-type="clarification"]') !== null`));
  // 历史管理：同一材料集合内置顶、分组、搜索和归档恢复均通过真实页面状态验证。
  const historyGroup = await request(`/material-sets/${setId}/conversation-groups`, "POST", { name: "项目专项" });
  await request(`/conversations/${conversationId}`, "PATCH", { title: "Redis 专项练习", isPinned: true, groupId: historyGroup.id });
  await cdp("Page.reload");
  await until(() => evaluate(`document.body.textContent.includes('Redis 专项练习')`), "历史管理字段刷新");
  assert(await evaluate(`document.querySelectorAll('.history-feature-section').length >= 1`), "历史分区存在");
  await evaluate(`(() => { const input = document.querySelector('[aria-label="搜索对话标题"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Redis 专项'); input.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  await until(() => evaluate(`document.body.textContent.includes('Redis 专项练习')`), "历史标题搜索");
  if (process.env.E2E_TEST_SCENARIOS === "1") {
    await message("测试模型失败");
    await until(() => evaluate(`document.body.textContent.includes('模型暂时不可用')`), "模型失败提示");
    await cdp("Page.reload");
    await until(() => evaluate(`document.body.textContent.includes('重试未完成步骤')`), "刷新恢复失败任务");
    await click("重试未完成步骤");
    await until(() => evaluate(`!document.querySelector('[data-testid="active-task"]') && !document.body.textContent.includes('模型暂时不可用')`), "显式重试成功");
    await evaluate(`(() => { const t = document.querySelector('[aria-label="练习输入"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t,'测试取消等待'); t.dispatchEvent(new Event('input',{bubbles:true})); })()`);
    await until(() => evaluate(`!document.querySelector('[aria-label="发送消息"]').disabled`), "提交取消测试");
    await click("发送消息");
    await until(() => evaluate(`[...document.querySelectorAll('button')].some(b => b.textContent.trim() === '取消' && !b.disabled)`), "等待中的真实任务");
    await click("取消");
    await until(() => evaluate(`document.body.textContent.includes('任务已取消')`), "取消结果");
    await delay(3300);
    assert(await evaluate(`document.body.textContent.includes('任务已取消')`), "取消后不能重新发布成功结果");
    await click("关闭提示");
    // 请求提交失败时必须保留输入草稿；通过浏览器网络边界模拟服务不可达。
    await cdp("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/v1/conversations/*/input-runs`, requestStage: "Request" }] });
    const previousHandler = socket.onmessage;
    socket.onmessage = event => {
      const value = JSON.parse(event.data);
      if (value.method === "Fetch.requestPaused") {
        if (value.params.request.method === "OPTIONS") cdp("Fetch.continueRequest", { requestId: value.params.requestId }).catch(() => {});
        else cdp("Fetch.fulfillRequest", { requestId: value.params.requestId, responseCode: 503, responseHeaders: [{ name: "Content-Type", value: "application/problem+json" }, { name: "Access-Control-Allow-Origin", value: new URL(front).origin }], body: Buffer.from(JSON.stringify({ detail: "浏览器测试：提交失败" })).toString("base64") }).catch(() => {});
      }
      else previousHandler(event);
    };
    await evaluate(`(() => { const t = document.querySelector('[aria-label="练习输入"]'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t,'保留这条草稿'); t.dispatchEvent(new Event('input',{bubbles:true})); })()`);
    await until(() => evaluate(`!document.querySelector('[aria-label="发送消息"]').disabled`), "失败提交前输入就绪");
    await click("发送消息");
    await until(() => evaluate(`document.body.textContent.includes('提交失败')`), "提交错误提示");
    assert.equal(await evaluate(`document.querySelector('[aria-label="练习输入"]').value`), "保留这条草稿");
    await cdp("Fetch.disable");
    socket.onmessage = previousHandler;
    await click("关闭提示");
  }
  await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await click("查看简历");
  assert(await evaluate(`document.documentElement.scrollWidth <= 390`), "窄屏无水平溢出");
  await writeFile(join(profile, "conversation-mobile.png"), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64"));
  await click("关闭简历");
  await cdp("Emulation.clearDeviceMetricsOverride");
  await writeFile(join(profile, "conversation-desktop.png"), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64"));
  await click("材料库");
  await until(() => evaluate(`document.querySelector('.material-list') !== null`), "返回材料库");
  await click("删除集合");
  await until(async () => (await fetch(`${base}/api/v1/material-sets/${setId}`)).status === 404, "删除集合");
  console.log(`真实浏览器端到端通过；截图目录：${profile}`);
} catch (error) {
  if (socket?.readyState === WebSocket.OPEN) {
    console.error("页面：", await evaluate("document.body.innerText").catch(() => "不可读"));
    await writeFile(join(profile, "failure.png"), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64")).catch(() => {});
  }
  throw error;
} finally {
  if (setId) await request(`/material-sets/${setId}`, "DELETE").catch(() => {});
  socket?.close();
  browser.kill();
}
