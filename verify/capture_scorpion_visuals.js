#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const crypto = require("crypto");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const BIN = path.join(ROOT, "bin");
const phase = process.argv[2];
const outputRoot = path.resolve(process.argv[3] || path.join(__dirname, "visual-evidence"));
const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};

if (!["before", "after", "contact"].includes(phase)) {
  console.error("usage: capture_scorpion_visuals.js <before|after|contact> <output-root>");
  process.exit(2);
}

const agents = [
  {
    agent_id: "forge/main:Boss",
    boss_id: "",
    is_master: true,
    target: "mc-main:Boss",
    tmux_target: "mc-main:Boss",
    state: "working",
    status: "working",
    backend: "codex",
    summary: "Coordinates verified delivery",
    spawn_cmd: "mp spawn forge/main:Boss",
    host: "forge",
    read_port: 0,
    write_port: 0,
  },
  {
    agent_id: "forge/main:eng-3",
    boss_id: "forge/main:Boss",
    is_master: false,
    target: "mc-main:eng-3",
    tmux_target: "mc-main:eng-3",
    state: "working",
    status: "working",
    backend: "codex",
    summary: "Premium Scorpion interface",
    spawn_cmd: "mp spawn forge/main:eng-3",
    host: "forge",
    read_port: 0,
    write_port: 0,
  },
  {
    agent_id: "forge/nightwatch:Nightwatch",
    boss_id: "forge/main:Boss",
    is_master: false,
    target: "mc-nightwatch:Nightwatch",
    tmux_target: "mc-nightwatch:Nightwatch",
    state: "idle",
    status: "idle",
    backend: "codex",
    summary: "Monitors task health",
    spawn_cmd: "mp spawn forge/nightwatch:Nightwatch",
    host: "forge",
    read_port: 0,
    write_port: 0,
  },
];

const tasks = {
  "visual-alpha": {
    id: "visual-alpha",
    text: "Ship premium Scorpion operator interface",
    state: "working",
    assignee: "forge/main:eng-3",
    doneCondition: "Paired captures and verification attached",
    projectSlug: "project-factory",
    contextQuestion: "",
    evidencePolicy: "required",
    workToDone: false,
    comments: [
      { id: "c1", by: "CEO", body: "Preserve Scorpion and every API contract.", kind: "comment", ts: 1785104000 },
      { id: "c2", by: "forge/main:eng-3", body: "Isolated implementation is active.", kind: "comment", ts: 1785104300 },
    ],
    proofs: [
      {
        id: "p1",
        by: "forge/main:eng-3",
        kind: "file",
        filename: "verification-report.txt",
        mime: "text/plain",
        bytes: 2048,
        sha256: "22c3879b542f7b37be6e51cbe14c53d987f05de25ef17cb8db94654473a5b836",
        url: "/fixture-proof",
        ts: 1785104400,
      },
    ],
    unread: 0,
    verified: false,
    pingsToBoss: 0,
    pinned: true,
    pinRank: 1,
    ownerHistory: [],
    updated: 1785104400,
  },
  "visual-beta": {
    id: "visual-beta",
    text: "Harden isolated publication controls",
    state: "review",
    assignee: "forge/main:Boss",
    doneCondition: "Independent verification complete",
    evidencePolicy: "required",
    comments: [],
    proofs: [],
    pinned: false,
    ownerHistory: [],
    updated: 1785104200,
  },
  "visual-gamma": {
    id: "visual-gamma",
    text: "Investigate stale provider telemetry",
    state: "blocked",
    assignee: "forge/nightwatch:Nightwatch",
    doneCondition: "Provider health is current",
    evidencePolicy: "optional",
    comments: [],
    proofs: [],
    pinned: false,
    ownerHistory: [],
    updated: 1785104100,
  },
  "visual-delta": {
    id: "visual-delta",
    text: "Archive completed recovery evidence",
    state: "done",
    assignee: "",
    doneCondition: "Evidence retained",
    evidencePolicy: "optional",
    comments: [],
    proofs: [],
    pinned: false,
    ownerHistory: [],
    updated: 1785103900,
  },
};

function board() {
  return {
    version: 2,
    order: Object.keys(tasks),
    displayOrder: Object.keys(tasks),
    pinSeq: 1,
    tasks,
    projectSlugs: ["project-factory"],
  };
}

function graph() {
  const graphAgents = agents.map((agent) => ({
    ...agent,
    read_port: server.address().port,
    write_port: server.address().port,
  }));
  return {
    agents: graphAgents,
    edges: [
      { parent: "forge/main:Boss", child: "forge/main:eng-3" },
      { parent: "forge/main:Boss", child: "forge/nightwatch:Nightwatch" },
    ],
    tasks: Object.values(tasks).map((task) => ({
      id: task.id,
      title: task.text,
      state: task.state,
      assignee: task.assignee,
      owner_live: agents.some((agent) => agent.agent_id === task.assignee),
      archived: ["done", "cancelled"].includes(task.state),
      pinned: task.pinned,
      updated: task.updated,
      href: `/terminal-graph?task=${task.id}`,
    })),
    states: ["needs_brainstorm", "working", "review", "blocked", "recurring", "done", "cancelled"],
  };
}

function terminalFixture() {
  return `<!doctype html><html><head><style>
  html,body{margin:0;height:100%;background:#050504;color:#d7d1bd;font:14px/1.55 "Cascadia Mono",monospace}
  body{padding:22px;box-sizing:border-box}.gold{color:#f2c230}.muted{color:#777266}.ok{color:#67b279}
  </style></head><body><div class="gold">MYPeople // SANITIZED TERMINAL</div>
  <div class="muted">fixture session · no transcript · no credentials</div><br>
  <div><span class="ok">●</span> agent ready</div><div>$ awaiting verified instruction<span class="gold">_</span></div>
  </body></html>`;
}

function send(res, status, type, body) {
  const bytes = Buffer.from(body);
  res.writeHead(status, {
    "Content-Type": type,
    "Content-Length": bytes.length,
    "Cache-Control": "no-store",
  });
  res.end(bytes);
}

function json(res, value) {
  send(res, 200, "application/json; charset=utf-8", JSON.stringify(value));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  const pages = {
    "/": "todos.html",
    "/todos": "todos.html",
    "/terminal-graph": "terminal-graph.html",
    "/dashboard": "dashboard.html",
    "/terminal": "terminal.html",
    "/todo/terminal": "terminal.html",
  };
  if (pages[url.pathname]) {
    return send(res, 200, "text/html; charset=utf-8", fs.readFileSync(path.join(BIN, pages[url.pathname])));
  }
  if (url.pathname === "/assets/mypeople-ui.css") {
    return send(res, 200, "text/css; charset=utf-8", fs.readFileSync(path.join(BIN, "mypeople-ui.css")));
  }
  if (url.pathname === "/assets/board-polling.js" || url.pathname === "/assets/visual-viewport.js") {
    return send(res, 200, "application/javascript; charset=utf-8", fs.readFileSync(path.join(BIN, path.basename(url.pathname))));
  }
  if (url.pathname === "/assets/voice-dock.js") {
    return send(res, 200, "application/javascript; charset=utf-8", fs.readFileSync(path.join(BIN, "voice-dock.js")));
  }
  if (url.pathname === "/terminal-frame") return send(res, 200, "text/html; charset=utf-8", terminalFixture());
  if (url.pathname === "/health") return json(res, { status: "ok", build: "visual-fixture" });
  if (url.pathname === "/agents") return json(res, agents);
  if (url.pathname === "/roster") return json(res, [...agents, {
    agent_id: "forge/main:eng-1",
    retired: true,
    summary: "Previous verified owner",
    spawn_cmd: "mp spawn forge/main:eng-1",
    revive_cmd: "mp revive forge/main:eng-1",
  }]);
  if (url.pathname === "/todo/board") return json(res, board());
  if (url.pathname === "/todo/status") return json(res, { ok: true });
  if (url.pathname === "/todo/terminal-graph") return json(res, graph());
  if (url.pathname === "/todo/attach") {
    return json(res, {
      ok: true,
      agent: url.searchParams.get("agent"),
      target: "sanitized",
      direct: `http://127.0.0.1:${server.address().port}/terminal-frame`,
    });
  }
  if (url.pathname === "/fixture-proof") return send(res, 200, "text/plain", "sanitized evidence");
  if (req.method === "POST" && url.pathname.startsWith("/todo/")) return json(res, { ok: true });
  send(res, 404, "application/json", '{"error":"not_found"}');
});

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

async function settle(page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}" });
  await page.waitForTimeout(700);
}

async function capturePhase() {
  const out = path.join(outputRoot, phase);
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const base = `http://127.0.0.1:${server.address().port}`;
  const targets = [
    { name: "priorities-list", route: "/" },
    { name: "priorities-detail", route: "/", prepare: async (page) => {
      await page.locator('li.task[data-id="visual-alpha"] .task-text').click();
      await page.waitForSelector("body.modal-open");
    }},
    { name: "hud-healthy", route: "/dashboard", ready: "#telemetryCards .combat-card" },
    { name: "hud-stale", route: "/dashboard", ready: "#telemetryCards .combat-card", prepare: async (page) => {
      await page.evaluate(() => { document.querySelector("#live").textContent = "stale"; });
    }},
    { name: "terminal-graph", route: "/terminal-graph", ready: ".node" },
    { name: "terminal-graph-detail", route: "/terminal-graph", ready: ".task-node", prepare: async (page) => {
      await page.locator('.task-node[data-task-id="visual-alpha"]').click();
      await page.waitForSelector("#taskModal.open");
    }},
    { name: "terminal", route: "/terminal?agent=forge%2Fmain%3Aeng-3", ready: "#terminalFrame[src]" },
  ];
  const manifest = [];
  for (const [viewportName, viewport] of Object.entries(viewports)) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: "dark" });
    for (const target of targets) {
      const page = await context.newPage();
      const external = [];
      page.on("request", (request) => {
        const requestUrl = new URL(request.url());
        if (!["127.0.0.1", "localhost"].includes(requestUrl.hostname) && requestUrl.protocol !== "data:") {
          external.push(request.url());
        }
      });
      await page.goto(base + target.route, { waitUntil: "domcontentloaded" });
      if (target.ready) await page.waitForSelector(target.ready);
      if (target.prepare) await target.prepare(page);
      await settle(page);
      if (target.name === "priorities-detail") {
        const mobileContract = await page.evaluate(() => {
          const selectors = ["#modalTitle", "#modalId", "#ownerLine", "#thread", "#commentInput", "#postComment"];
          const boxes = Object.fromEntries(selectors.map((selector) => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return [selector, { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }];
          }));
          const intersects = (r) => r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.x < innerWidth && r.y < innerHeight;
          const shell = document.querySelector("#modalShell");
          return { boxes, intersects: selectors.every((selector) => intersects(boxes[selector])), detailsHidden: document.querySelector("#detailsPanel").hidden, overflowX: shell.scrollWidth - shell.clientWidth, overflowY: shell.scrollHeight - shell.clientHeight, threadHeight: boxes["#thread"].height };
        });
        if (viewportName === "mobile") {
          if (!mobileContract.intersects || !mobileContract.detailsHidden || mobileContract.overflowX > 1 || mobileContract.overflowY > 1 || mobileContract.threadHeight < 120) throw new Error(`mobile modal contract failed: ${JSON.stringify(mobileContract)}`);
          const trigger = page.locator('li.task[data-id="visual-alpha"] .task-text');
          await page.click("#closeModal");
          await page.waitForFunction(() => !document.body.classList.contains("modal-open"));
          await trigger.focus();
          await trigger.click();
          await page.waitForSelector("body.modal-open");
          await page.click("#detailsToggle");
          await page.waitForFunction(() => !document.querySelector("#detailsPanel").hidden && document.querySelector("#detailsPanel").scrollHeight >= document.querySelector("#detailsPanel").clientHeight);
          await trigger.focus();
          await page.click("#closeModal");
          await page.waitForFunction(() => !document.body.classList.contains("modal-open"));
          if (!(await trigger.evaluate((node) => document.activeElement === node))) throw new Error("mobile modal did not restore focus");
          await trigger.focus();
          await trigger.click();
          await page.waitForSelector("body.modal-open");
          await page.keyboard.press("Escape");
          await page.waitForFunction(() => !document.body.classList.contains("modal-open"));
          if (!(await trigger.evaluate((node) => document.activeElement === node))) throw new Error("mobile ESC did not restore focus");
          await trigger.focus();
          await trigger.click();
          await page.waitForSelector("body.modal-open");
          await settle(page);
        }
      }
      const audit = await page.evaluate(() => {
        const visible = (element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        };
        const controls = [...document.querySelectorAll("button,a,input,textarea,select,[tabindex]")].filter(visible);
        const unnamed = controls.filter((element) => {
          const name = element.getAttribute("aria-label")
            || element.getAttribute("title")
            || element.textContent
            || (element.labels && [...element.labels].map((label) => label.textContent).join(" "))
            || element.getAttribute("placeholder")
            || element.getAttribute("value");
          return !String(name || "").trim();
        });
        const undersized = controls.filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width < 24 || rect.height < 24;
        });
        return {
          documentLang: document.documentElement.lang,
          horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - innerWidth),
          visibleControls: controls.length,
          unnamedControls: unnamed.length,
          undersizedControls: undersized.length,
          reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        };
      });
      const file = path.join(out, `${target.name}-${viewportName}.png`);
      await page.screenshot({ path: file, fullPage: false });
      manifest.push({
        phase,
        surface: target.name,
        route: target.route,
        viewport: viewportName,
        width: viewport.width,
        height: viewport.height,
        file: path.basename(file),
        bytes: fs.statSync(file).size,
        sha256: sha256(file),
        externalRequests: [...new Set(external)],
        audit,
      });
      await page.close();
    }
    await context.close();
  }
  fs.writeFileSync(path.join(out, "manifest.json"), JSON.stringify({
    fixture: "sanitized-scorpion-v1",
    sourceCommit: "039a62988625369f3f86c055cd476b0080395daa",
    phase,
    captures: manifest,
  }, null, 2) + "\n");
  await browser.close();
  console.log(`${phase}: ${manifest.length} captures; ${manifest.filter((item) => item.externalRequests.length).length} with external requests`);
}

function imageData(file) {
  return `data:image/png;base64,${fs.readFileSync(file).toString("base64")}`;
}

async function captureContactSheet() {
  const before = JSON.parse(fs.readFileSync(path.join(outputRoot, "before", "manifest.json")));
  const after = JSON.parse(fs.readFileSync(path.join(outputRoot, "after", "manifest.json")));
  const rows = before.captures.map((item, index) => {
    const paired = after.captures[index];
    return `<section><h2>${item.surface} · ${item.viewport} · ${item.width}×${item.height}</h2>
      <div><figure><figcaption>BEFORE</figcaption><img src="${imageData(path.join(outputRoot, "before", item.file))}"></figure>
      <figure><figcaption>AFTER</figcaption><img src="${imageData(path.join(outputRoot, "after", paired.file))}"></figure></div></section>`;
  }).join("");
  const html = `<!doctype html><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;padding:32px;background:#080807;color:#f4f0df;font:14px system-ui}
    header{margin-bottom:28px;border-left:5px solid #f2c230;padding-left:16px}h1{margin:0;font-size:30px}p{color:#9d9788}
    section{margin:0 0 30px;padding:18px;background:#12110e;border:1px solid rgba(244,240,223,.14);break-inside:avoid}
    h2{margin:0 0 14px;color:#f2c230;font-size:16px}section>div{display:grid;grid-template-columns:1fr 1fr;gap:18px}
    figure{margin:0;min-width:0}figcaption{margin-bottom:8px;font:700 11px monospace;letter-spacing:.12em;color:#ff8a1f}
    img{display:block;width:100%;height:auto;border:1px solid rgba(242,194,48,.3)}
  </style><body><header><h1>MyPeople · Scorpion Command Atelier</h1>
  <p>Sanitized paired visual evidence · exact base and stable viewports</p></header>${rows}</body>`;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1800, height: 1200 }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "load" });
  const sheet = path.join(outputRoot, "scorpion-before-after-contact-sheet.png");
  await page.screenshot({ path: sheet, fullPage: true });
  await browser.close();
  fs.writeFileSync(path.join(outputRoot, "contact-sheet.sha256"), `${sha256(sheet)}  ${path.basename(sheet)}\n`);
  console.log(`contact: ${sheet}`);
}

server.listen(0, "127.0.0.1", async () => {
  try {
    if (phase === "contact") await captureContactSheet();
    else await capturePhase();
  } finally {
    server.close();
  }
});
