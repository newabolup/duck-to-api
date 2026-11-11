"use strict";

const state = {
  activeTab: "operations",
  pgMode: "generate",
  activePgJobId: null,
  selectedFile: null,
  adapters: [],
  jobs: [],
  lastJobsSignature: "",
  logsPaused: false,
  logEntries: [],
  logSource: null,
  lastModalReturnFocus: null,
};

const els = {
  headerDot: document.getElementById("header-browser-dot"),
  headerLabel: document.getElementById("header-browser-label"),
  themeToggleBtn: document.getElementById("theme-toggle-btn"),
  openApiKeyBtn: document.getElementById("open-apikey-btn"),
  globalAlert: document.getElementById("global-alert"),
  globalAlertTitle: document.getElementById("global-alert-title"),
  globalAlertMsg: document.getElementById("global-alert-message"),
  globalAlertAuthBtn: document.getElementById("global-alert-auth-btn"),
  globalAlertDismissBtn: document.getElementById("global-alert-dismiss-btn"),

  tabBtns: Array.from(document.querySelectorAll('[role="tab"]')),
  tabPanels: Array.from(document.querySelectorAll('[role="tabpanel"]')),

  metaRunning: document.getElementById("meta-running"),
  metaMode: document.getElementById("meta-mode"),
  metaConcurrency: document.getElementById("meta-concurrency"),
  metaProfile: document.getElementById("meta-profile"),
  browserFeedback: document.getElementById("browser-action-feedback"),
  btnManualAuth: document.getElementById("btn-manual-auth"),
  btnToggleHeadless: document.getElementById("btn-toggle-headless"),
  btnCheckSession: document.getElementById("btn-check-session"),
  btnRestartBrowser: document.getElementById("btn-restart-browser"),

  cntQueued: document.getElementById("cnt-queued"),
  cntRunning: document.getElementById("cnt-running"),
  cntCompleted: document.getElementById("cnt-completed"),
  cntNeedsAuth: document.getElementById("cnt-needs-auth"),
  cntFailed: document.getElementById("cnt-failed"),

  jobsFilter: document.getElementById("jobs-status-filter"),
  jobsSearch: document.getElementById("jobs-search-input"),
  btnRefreshJobs: document.getElementById("btn-refresh-jobs"),
  jobsLoading: document.getElementById("jobs-loading-state"),
  jobsError: document.getElementById("jobs-error-state"),
  jobsErrorText: document.getElementById("jobs-error-text"),
  btnRetryLoadJobs: document.getElementById("btn-retry-load-jobs"),
  jobsEmpty: document.getElementById("jobs-empty-state"),
  jobsEmptyText: document.getElementById("jobs-empty-text"),
  btnEmptyGotoPg: document.getElementById("btn-empty-goto-pg"),
  btnResetJobFilters: document.getElementById("btn-reset-job-filters"),
  jobsTableWrap: document.getElementById("jobs-table-wrap"),
  jobsTbody: document.getElementById("jobs-tbody"),

  logsStreamStatus: document.getElementById("logs-stream-status"),
  logsLevelFilter: document.getElementById("logs-level-filter"),
  btnToggleLogsStream: document.getElementById("btn-toggle-logs-stream"),
  btnClearLogs: document.getElementById("btn-clear-logs"),
  logsContainer: document.getElementById("logs-container"),
  logsEmptyState: document.getElementById("logs-empty-state"),

  pgForm: document.getElementById("pg-form"),
  pgModeGenerate: document.getElementById("pg-mode-generate"),
  pgModeEdit: document.getElementById("pg-mode-edit"),
  pgAdapter: document.getElementById("pg-adapter"),
  pgUploadGroup: document.getElementById("pg-upload-group"),
  pgFileInput: document.getElementById("pg-file-input"),
  pgFileName: document.getElementById("pg-file-name"),
  pgClearFileBtn: document.getElementById("pg-clear-file-btn"),
  pgPrompt: document.getElementById("pg-prompt"),
  pgSize: document.getElementById("pg-size"),
  pgResponseFormat: document.getElementById("pg-response-format"),
  pgSubmitBtn: document.getElementById("pg-submit-btn"),
  pgCopyCurlBtn: document.getElementById("pg-copy-curl-btn"),
  pgFormFeedback: document.getElementById("pg-form-feedback"),
  pgCurlPreview: document.getElementById("pg-curl-preview"),

  pgStageSubtitle: document.getElementById("pg-stage-subtitle"),
  pgCancelActiveBtn: document.getElementById("pg-cancel-active-btn"),
  pgSendToEditBtn: document.getElementById("pg-send-to-edit-btn"),
  pgDownloadLink: document.getElementById("pg-download-link"),
  pgStageStatus: document.getElementById("pg-stage-status"),
  pgStageEmpty: document.getElementById("pg-stage-empty"),
  pgStageError: document.getElementById("pg-stage-error"),
  pgStageErrorText: document.getElementById("pg-stage-error-text"),
  pgStageAuthBtn: document.getElementById("pg-stage-auth-btn"),
  pgStageRetryBtn: document.getElementById("pg-stage-retry-btn"),
  pgStageFrames: document.getElementById("pg-stage-frames"),
  pgInputFigure: document.getElementById("pg-input-figure"),
  pgInputImg: document.getElementById("pg-input-img"),
  pgOutputFigure: document.getElementById("pg-output-figure"),
  pgOutputCaption: document.getElementById("pg-output-caption"),
  pgOutputInspectBtn: document.getElementById("pg-output-inspect-btn"),
  pgOutputImg: document.getElementById("pg-output-img"),

  btnRefreshGallery: document.getElementById("btn-refresh-gallery"),
  galleryEmpty: document.getElementById("gallery-empty-state"),
  galleryGrid: document.getElementById("gallery-grid"),

  btnRefreshAdapters: document.getElementById("btn-refresh-adapters"),
  adaptersLoading: document.getElementById("adapters-loading"),
  adaptersError: document.getElementById("adapters-error"),
  adaptersErrorText: document.getElementById("adapters-error-text"),
  adaptersList: document.getElementById("adapters-list"),

  imageModal: document.getElementById("image-modal"),
  closeImageModalBtn: document.getElementById("close-image-modal-btn"),
  modalImagesRow: document.getElementById("modal-images-row"),
  modalDetails: document.getElementById("modal-details"),
  modalDownloadLink: document.getElementById("modal-download-link"),

  apiKeyModal: document.getElementById("apikey-modal"),
  closeApiKeyModalBtn: document.getElementById("close-apikey-modal-btn"),
  apiKeyForm: document.getElementById("apikey-form"),
  apiKeyInput: document.getElementById("apikey-input"),
  clearApiKeyBtn: document.getElementById("clear-apikey-btn"),
};

function getStoredApiKey() {
  try {
    return localStorage.getItem("duck_to_api_key") || "";
  } catch {
    return "";
  }
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const key = getStoredApiKey();
  if (key && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${key}`);
  }
  const resp = await fetch(url, { ...options, headers });
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      els.globalAlert.classList.remove("hidden");
      els.globalAlertTitle.textContent = "API Key Required";
      els.globalAlertMsg.textContent = "This instance is protected by DUCK_API_API_KEY. Click 'API Key' in the top bar to authenticate.";
      els.globalAlertAuthBtn.classList.add("hidden");
    }
    const msg = (data && (data.detail || (data.error && data.error.message))) || `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}

async function syncDashboardSessionCookie() {
  const key = getStoredApiKey();
  if (!key) return;
  try {
    await fetch("/api/v1/auth/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}` },
    });
  } catch {}
}

function setFeedback(el, text, kind = "") {
  if (!text) {
    el.className = "inline-feedback hidden";
    el.textContent = "";
    return;
  }
  el.className = `inline-feedback ${kind}`.trim();
  el.textContent = text;
}

/* Theme toggle */
function syncThemeButton() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const isDark = current === "dark";
  els.themeToggleBtn.textContent = isDark ? "Light theme" : "Dark theme";
  els.themeToggleBtn.setAttribute("aria-pressed", String(isDark));
}

els.themeToggleBtn.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("duck_to_api_theme", next);
  } catch {}
  syncThemeButton();
});

/* Tabs with arrow-key accessibility */
function activateTab(tabName) {
  state.activeTab = tabName;
  for (const btn of els.tabBtns) {
    const selected = btn.dataset.tab === tabName;
    btn.setAttribute("aria-selected", String(selected));
    btn.tabIndex = selected ? 0 : -1;
  }
  for (const panel of els.tabPanels) {
    const match = panel.id === `panel-${tabName}`;
    panel.classList.toggle("hidden", !match);
  }
}

els.tabBtns.forEach((btn, idx) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      const next = (idx + delta + els.tabBtns.length) % els.tabBtns.length;
      els.tabBtns[next].focus();
      activateTab(els.tabBtns[next].dataset.tab);
    }
  });
});

/* Browser status and actions */
let latestBrowserState = null;

async function refreshBrowserStatus() {
  try {
    const data = await apiFetch("/api/v1/browser/status");
    latestBrowserState = data;
    renderBrowserState(data);
  } catch (err) {
    els.headerDot.className = "status-dot err";
    els.headerLabel.textContent = "API Error";
    els.metaRunning.textContent = err.message;
  }
}

function renderBrowserState(data) {
  const needsAuth = (data.needs_auth_adapters || []).length > 0;
  if (!data.running) {
    els.headerDot.className = "status-dot err";
    els.headerLabel.textContent = "Chromium: Stopped";
  } else if (needsAuth || data.manual_auth_mode) {
    els.headerDot.className = "status-dot warn";
    els.headerLabel.textContent = data.manual_auth_mode ? "Chromium: Manual Auth" : "Chromium: Needs Auth";
  } else {
    els.headerDot.className = "status-dot ok";
    els.headerLabel.textContent = data.headless ? "Chromium: Ready (Headless)" : "Chromium: Ready (Headed)";
  }

  els.metaRunning.textContent = data.running ? "Running" : "Stopped";
  els.metaMode.textContent = data.manual_auth_mode
    ? "Headed (Manual Auth)"
    : data.headless
      ? "Headless"
      : "Headed";
  els.metaConcurrency.textContent = `${data.active_jobs} / ${data.max_concurrent_jobs} active`;
  els.metaProfile.textContent = data.profile_dir || "-";
  els.btnToggleHeadless.textContent = data.headless ? "Switch to Headed" : "Switch to Headless";

  if (needsAuth) {
    els.globalAlert.classList.remove("hidden");
    els.globalAlertTitle.textContent = "Manual Verification Required";
    els.globalAlertMsg.textContent = `Adapter(s) paused for human verification: ${data.needs_auth_adapters.join(", ")}.`;
    els.globalAlertAuthBtn.classList.remove("hidden");
  } else {
    els.globalAlert.classList.add("hidden");
  }
}

async function runBrowserAction(btn, actionFn, successMsg) {
  const buttons = [els.btnManualAuth, els.btnToggleHeadless, els.btnCheckSession, els.btnRestartBrowser];
  buttons.forEach((b) => { b.disabled = true; });
  setFeedback(els.browserFeedback, "Applying browser action...", "");
  try {
    const res = await actionFn();
    await refreshBrowserStatus();
    const message = typeof successMsg === "function" ? successMsg(res) : successMsg;
    const kind = res && res.status === "needs_auth" ? "warn" : res && res.status === "error" ? "err" : "ok";
    setFeedback(els.browserFeedback, message, kind);
  } catch (err) {
    setFeedback(els.browserFeedback, err.message, "err");
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

els.btnManualAuth.addEventListener("click", () =>
  runBrowserAction(
    els.btnManualAuth,
    () => apiFetch("/api/v1/browser/open-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adapter: els.pgAdapter.value || "duck-ai" }),
    }),
    "Visible Chromium window opened. Complete any login or verification there; cookies persist across restarts."
  )
);

els.globalAlertAuthBtn.addEventListener("click", () => els.btnManualAuth.click());
els.pgStageAuthBtn.addEventListener("click", () => {
  activateTab("operations");
  els.btnManualAuth.click();
});

els.globalAlertDismissBtn.addEventListener("click", () => {
  els.globalAlert.classList.add("hidden");
});

els.btnToggleHeadless.addEventListener("click", () => {
  const targetHeadless = latestBrowserState ? !latestBrowserState.headless : false;
  return runBrowserAction(
    els.btnToggleHeadless,
    () => apiFetch("/api/v1/browser/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headless: targetHeadless }),
    }),
    `Browser restarted in ${targetHeadless ? "headless" : "headed"} mode.`
  );
});

els.btnCheckSession.addEventListener("click", () =>
  runBrowserAction(
    els.btnCheckSession,
    () => apiFetch("/api/v1/browser/check-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adapter: els.pgAdapter.value || "duck-ai" }),
    }),
    (res) => `Session check (${res.status}): ${res.message}`
  )
);

els.btnRestartBrowser.addEventListener("click", () =>
  runBrowserAction(
    els.btnRestartBrowser,
    () => apiFetch("/api/v1/browser/restart", { method: "POST" }),
    "Persistent Chromium context restarted."
  )
);

/* Jobs & Gallery */
async function refreshJobs(showLoading = false) {
  if (showLoading) {
    els.jobsLoading.classList.remove("hidden");
    els.jobsError.classList.add("hidden");
    els.jobsEmpty.classList.add("hidden");
    els.jobsTableWrap.classList.add("hidden");
  }
  const statusFilter = els.jobsFilter.value;
  try {
    const data = await apiFetch(`/api/v1/jobs?status=${encodeURIComponent(statusFilter)}&limit=100`);
    state.jobs = data.jobs || [];
    const q = data.queue || {};
    els.cntQueued.textContent = String(q.queued ?? 0);
    els.cntRunning.textContent = String(q.running ?? 0);
    els.cntCompleted.textContent = String(q.completed ?? 0);
    els.cntNeedsAuth.textContent = String(q.needs_auth ?? 0);
    els.cntFailed.textContent = String(q.failed ?? 0);

    els.jobsLoading.classList.add("hidden");
    els.jobsError.classList.add("hidden");
    const sig = JSON.stringify(
      state.jobs.map((j) => [j.id, j.status, j.output_urls, j.error, j.duration_ms])
    );
    if (showLoading || sig !== state.lastJobsSignature) {
      state.lastJobsSignature = sig;
      renderJobsTable();
      renderGallery();
    }
    syncActivePlaygroundJob();
  } catch (err) {
    els.jobsLoading.classList.add("hidden");
    els.jobsTableWrap.classList.add("hidden");
    els.jobsEmpty.classList.add("hidden");
    els.jobsError.classList.remove("hidden");
    els.jobsErrorText.textContent = `Could not load jobs: ${err.message}`;
  }
}

function getFilteredJobs() {
  const query = (els.jobsSearch.value || "").trim().toLowerCase();
  if (!query) return state.jobs;
  return state.jobs.filter((j) =>
    j.id.toLowerCase().includes(query) ||
    j.prompt.toLowerCase().includes(query) ||
    j.adapter.toLowerCase().includes(query)
  );
}

function renderJobsTable() {
  const filtered = getFilteredJobs();
  const hasActiveFilter = els.jobsFilter.value !== "all" || Boolean(els.jobsSearch.value.trim());

  if (filtered.length === 0) {
    els.jobsTableWrap.classList.add("hidden");
    els.jobsEmpty.classList.remove("hidden");
    els.jobsEmptyText.textContent = hasActiveFilter
      ? "No jobs match the selected status or search filter."
      : "No jobs yet. Submit a prompt in Playground to run your first image job.";
    els.btnEmptyGotoPg.classList.toggle("hidden", hasActiveFilter);
    els.btnResetJobFilters.classList.toggle("hidden", !hasActiveFilter);
    return;
  }

  els.jobsEmpty.classList.add("hidden");
  els.jobsTableWrap.classList.remove("hidden");
  els.jobsTbody.replaceChildren();

  for (const job of filtered) {
    const tr = document.createElement("tr");

    const tdId = document.createElement("td");
    const idBox = document.createElement("div");
    idBox.className = "job-id-cell";
    const idStrong = document.createElement("span");
    idStrong.className = "mono";
    idStrong.textContent = job.id;
    const sub = document.createElement("span");
    sub.className = "job-submeta";
    sub.textContent = `${job.job_type} | ${job.adapter}`;
    idBox.append(idStrong, sub);
    tdId.appendChild(idBox);

    const tdPreview = document.createElement("td");
    const previewUrl = (job.output_urls && job.output_urls[0]) || job.input_url;
    if (previewUrl) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "thumb-btn";
      btn.setAttribute("aria-label", `Inspect images for ${job.id}`);
      const img = document.createElement("img");
      img.src = previewUrl;
      img.alt = `Preview for ${job.id}`;
      img.width = 52;
      img.height = 52;
      btn.appendChild(img);
      btn.addEventListener("click", () => openImageModal(job, btn));
      tdPreview.appendChild(btn);
    } else {
      tdPreview.textContent = "-";
    }

    const tdPrompt = document.createElement("td");
    const pCell = document.createElement("div");
    pCell.className = "prompt-cell";
    const pText = document.createElement("p");
    pText.className = "prompt-text";
    pText.dir = "auto";
    pText.textContent = job.prompt;
    pCell.appendChild(pText);
    if (job.error) {
      const errNote = document.createElement("p");
      errNote.className = "job-error-note";
      errNote.textContent = job.error;
      pCell.appendChild(errNote);
    }
    tdPrompt.appendChild(pCell);

    const tdStatus = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge badge-${job.status}`;
    badge.textContent = job.status;
    tdStatus.appendChild(badge);

    const tdTiming = document.createElement("td");
    const dur = job.duration_ms != null ? `${(job.duration_ms / 1000).toFixed(1)}s` : "-";
    tdTiming.innerHTML = `<div class="job-submeta">${escapeHtml(job.created_at)}</div><div class="mono">${dur}</div>`;

    const tdActions = document.createElement("td");
    const actGroup = document.createElement("div");
    actGroup.className = "btn-group";
    if (job.status === "queued" || job.status === "running") {
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-danger btn-compact";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", () => handleCancelJob(job.id));
      actGroup.appendChild(cancelBtn);
    }
    if (["failed", "cancelled", "needs_auth"].includes(job.status)) {
      const retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "btn btn-secondary btn-compact";
      retryBtn.textContent = "Retry";
      retryBtn.addEventListener("click", () => handleRetryJob(job.id));
      actGroup.appendChild(retryBtn);
    }
    if (job.output_urls && job.output_urls.length > 0) {
      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "btn btn-secondary btn-compact";
      viewBtn.textContent = "Inspect";
      viewBtn.addEventListener("click", () => openImageModal(job, viewBtn));
      actGroup.appendChild(viewBtn);
    }
    tdActions.appendChild(actGroup);

    tr.append(tdId, tdPreview, tdPrompt, tdStatus, tdTiming, tdActions);
    els.jobsTbody.appendChild(tr);
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function handleCancelJob(jobId) {
  try {
    await apiFetch(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });
    await refreshJobs();
  } catch (err) {
    setFeedback(els.browserFeedback, `Cancel failed: ${err.message}`, "err");
  }
}

async function handleRetryJob(jobId) {
  try {
    const newJob = await apiFetch(`/api/v1/jobs/${jobId}/retry`, { method: "POST" });
    state.activePgJobId = newJob.id;
    await refreshJobs();
  } catch (err) {
    setFeedback(els.browserFeedback, `Retry failed: ${err.message}`, "err");
  }
}

els.jobsFilter.addEventListener("change", () => refreshJobs(true));
els.jobsSearch.addEventListener("input", () => renderJobsTable());
els.btnRefreshJobs.addEventListener("click", () => refreshJobs(true));
els.btnRetryLoadJobs.addEventListener("click", () => refreshJobs(true));
els.btnEmptyGotoPg.addEventListener("click", () => activateTab("playground"));
els.btnResetJobFilters.addEventListener("click", () => {
  els.jobsFilter.value = "all";
  els.jobsSearch.value = "";
  refreshJobs(true);
});

/* Gallery */
function renderGallery() {
  const completed = state.jobs.filter((j) => j.status === "completed" && j.output_urls && j.output_urls.length > 0);
  if (completed.length === 0) {
    els.galleryEmpty.classList.remove("hidden");
    els.galleryGrid.classList.add("hidden");
    els.galleryGrid.replaceChildren();
    return;
  }

  els.galleryEmpty.classList.add("hidden");
  els.galleryGrid.classList.remove("hidden");
  els.galleryGrid.replaceChildren();

  for (const job of completed) {
    const card = document.createElement("article");
    card.className = "gallery-card";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "gallery-thumb-btn";
    btn.setAttribute("aria-label", `Inspect output for ${job.id}`);
    const img = document.createElement("img");
    img.src = job.output_urls[0];
    img.alt = job.prompt.slice(0, 80);
    img.width = 240;
    img.height = 240;
    btn.appendChild(img);
    btn.addEventListener("click", () => openImageModal(job, btn));

    const meta = document.createElement("div");
    meta.className = "gallery-meta";
    const promptEl = document.createElement("p");
    promptEl.className = "gallery-prompt";
    promptEl.dir = "auto";
    promptEl.textContent = job.prompt;

    const sub = document.createElement("div");
    sub.className = "gallery-sub";
    const left = document.createElement("span");
    left.textContent = `${job.adapter} (${job.job_type})`;
    const right = document.createElement("span");
    right.className = "mono";
    right.textContent = job.duration_ms != null ? `${(job.duration_ms / 1000).toFixed(1)}s` : "";
    sub.append(left, right);

    meta.append(promptEl, sub);
    card.append(btn, meta);
    els.galleryGrid.appendChild(card);
  }
}

els.btnRefreshGallery.addEventListener("click", () => refreshJobs());

/* Playground */
function setPlaygroundMode(mode) {
  state.pgMode = mode;
  const isEdit = mode === "edit";
  els.pgModeGenerate.classList.toggle("active", !isEdit);
  els.pgModeGenerate.setAttribute("aria-pressed", String(!isEdit));
  els.pgModeEdit.classList.toggle("active", isEdit);
  els.pgModeEdit.setAttribute("aria-pressed", String(isEdit));
  els.pgUploadGroup.classList.toggle("hidden", !isEdit);
  els.pgSubmitBtn.textContent = isEdit ? "Run Edit Job" : "Run Image Job";
  updateCurlPreview();
}

els.pgModeGenerate.addEventListener("click", () => setPlaygroundMode("generate"));
els.pgModeEdit.addEventListener("click", () => setPlaygroundMode("edit"));

els.pgFileInput.addEventListener("change", () => {
  const file = els.pgFileInput.files && els.pgFileInput.files[0];
  state.selectedFile = file || null;
  if (file) {
    els.pgFileName.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;
    els.pgClearFileBtn.classList.remove("hidden");
    const reader = new FileReader();
    reader.onload = () => {
      els.pgStageEmpty.classList.add("hidden");
      els.pgStageFrames.classList.remove("hidden");
      els.pgInputFigure.classList.remove("hidden");
      els.pgInputImg.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  } else {
    els.pgFileName.textContent = "No file selected";
    els.pgClearFileBtn.classList.add("hidden");
  }
});

els.pgClearFileBtn.addEventListener("click", () => {
  els.pgFileInput.value = "";
  state.selectedFile = null;
  els.pgFileName.textContent = "No file selected";
  els.pgClearFileBtn.classList.add("hidden");
  els.pgInputFigure.classList.add("hidden");
  els.pgInputImg.src = "";
});

function updateCurlPreview() {
  const origin = window.location.origin;
  const model = els.pgAdapter.value || "duck-ai";
  const prompt = (els.pgPrompt.value || "A geometric fox in warm daylight").replace(/"/g, '\\"');
  const size = els.pgSize.value;
  const fmt = els.pgResponseFormat.value;
  const keyHeader = getStoredApiKey() ? ` \\\n  -H "Authorization: Bearer YOUR_API_KEY"` : "";

  if (state.pgMode === "generate") {
    els.pgCurlPreview.textContent =
      `curl -X POST "${origin}/v1/images/generations" \\\n` +
      `  -H "Content-Type: application/json"${keyHeader} \\\n` +
      `  -d '{"model":"${model}","prompt":"${prompt}","size":"${size}","response_format":"${fmt}"}'`;
  } else {
    els.pgCurlPreview.textContent =
      `curl -X POST "${origin}/v1/images/edits"${keyHeader} \\\n` +
      `  -F "image=@input.png" \\\n` +
      `  -F "model=${model}" \\\n` +
      `  -F "prompt=${prompt}" \\\n` +
      `  -F "size=${size}" \\\n` +
      `  -F "response_format=${fmt}"`;
  }
}

[els.pgAdapter, els.pgPrompt, els.pgSize, els.pgResponseFormat].forEach((el) => {
  el.addEventListener("input", updateCurlPreview);
  el.addEventListener("change", updateCurlPreview);
});

els.pgCopyCurlBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(els.pgCurlPreview.textContent);
    setFeedback(els.pgFormFeedback, "Copied curl command to clipboard.", "ok");
  } catch {
    setFeedback(els.pgFormFeedback, "Clipboard permission denied. Copy directly from the preview box.", "warn");
  }
});

els.pgForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const prompt = els.pgPrompt.value.trim();
  if (!prompt) {
    setFeedback(els.pgFormFeedback, "Prompt cannot be empty.", "err");
    return;
  }
  if (state.pgMode === "edit" && !state.selectedFile) {
    setFeedback(els.pgFormFeedback, "Select a source image before running an edit job.", "err");
    return;
  }

  els.pgSubmitBtn.disabled = true;
  setFeedback(els.pgFormFeedback, "Queueing job...", "");
  try {
    let job;
    if (state.pgMode === "generate") {
      job = await apiFetch("/api/v1/jobs/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          adapter: els.pgAdapter.value || "duck-ai",
          size: els.pgSize.value,
        }),
      });
    } else {
      const fd = new FormData();
      fd.append("image", state.selectedFile);
      fd.append("prompt", prompt);
      fd.append("adapter", els.pgAdapter.value || "duck-ai");
      fd.append("size", els.pgSize.value);
      job = await apiFetch("/api/v1/jobs/edit", {
        method: "POST",
        body: fd,
      });
    }
    state.activePgJobId = job.id;
    setFeedback(els.pgFormFeedback, `Queued job ${job.id}`, "ok");
    renderPlaygroundStage(job);
    await refreshJobs();
  } catch (err) {
    setFeedback(els.pgFormFeedback, err.message, "err");
  } finally {
    els.pgSubmitBtn.disabled = false;
  }
});

function syncActivePlaygroundJob() {
  if (!state.activePgJobId) return;
  const found = state.jobs.find((j) => j.id === state.activePgJobId);
  if (found) {
    renderPlaygroundStage(found);
  }
}

function renderPlaygroundStage(job) {
  els.pgStageSubtitle.textContent = `${job.id} (${job.job_type} via ${job.adapter})`;
  els.pgStageEmpty.classList.add("hidden");

  const isActive = job.status === "queued" || job.status === "running";
  els.pgCancelActiveBtn.classList.toggle("hidden", !isActive);

  if (job.status === "queued" || job.status === "running") {
    setFeedback(
      els.pgStageStatus,
      job.status === "queued" ? `Job ${job.id} is queued...` : `Running ${job.id} in Chromium...`,
      "warn"
    );
    els.pgStageError.classList.add("hidden");
  } else if (job.status === "completed") {
    const secs = job.duration_ms != null ? `${(job.duration_ms / 1000).toFixed(1)}s` : "";
    setFeedback(els.pgStageStatus, `Completed ${job.id} ${secs}`.trim(), "ok");
    els.pgStageError.classList.add("hidden");
  } else {
    setFeedback(els.pgStageStatus, "", "");
    els.pgStageError.classList.remove("hidden");
    els.pgStageErrorText.textContent = job.error || `Job ended with status '${job.status}'.`;
    els.pgStageAuthBtn.classList.toggle("hidden", job.status !== "needs_auth");
    els.pgStageRetryBtn.classList.remove("hidden");
  }

  const hasInput = Boolean(job.input_url);
  const hasOutput = Boolean(job.output_urls && job.output_urls[0]);
  els.pgStageFrames.classList.toggle("hidden", !hasInput && !hasOutput);

  if (hasInput) {
    els.pgInputFigure.classList.remove("hidden");
    els.pgInputImg.src = job.input_url;
  } else if (state.pgMode !== "edit" || !state.selectedFile) {
    els.pgInputFigure.classList.add("hidden");
  }

  if (hasOutput) {
    els.pgOutputFigure.classList.remove("hidden");
    els.pgOutputImg.src = job.output_urls[0];
    els.pgOutputCaption.textContent = `Output (${job.adapter})`;
    els.pgDownloadLink.href = job.output_urls[0];
    els.pgDownloadLink.classList.remove("hidden");
    els.pgSendToEditBtn.classList.remove("hidden");
    els.pgOutputInspectBtn.onclick = () => openImageModal(job, els.pgOutputInspectBtn);
  } else {
    els.pgOutputFigure.classList.add("hidden");
    els.pgDownloadLink.classList.add("hidden");
    els.pgSendToEditBtn.classList.add("hidden");
  }
}

els.pgCancelActiveBtn.addEventListener("click", async () => {
  if (state.activePgJobId) {
    await handleCancelJob(state.activePgJobId);
  }
});

els.pgStageRetryBtn.addEventListener("click", async () => {
  if (state.activePgJobId) {
    await handleRetryJob(state.activePgJobId);
  }
});

els.pgSendToEditBtn.addEventListener("click", async () => {
  const src = els.pgOutputImg.src;
  if (!src) return;
  try {
    const resp = await fetch(src);
    const blob = await resp.blob();
    const file = new File([blob], "previous_output.png", { type: blob.type || "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    els.pgFileInput.files = dt.files;
    els.pgFileInput.dispatchEvent(new Event("change"));
    setPlaygroundMode("edit");
    els.pgPrompt.focus();
  } catch (err) {
    setFeedback(els.pgFormFeedback, `Could not load image into edit mode: ${err.message}`, "err");
  }
});

/* Adapters */
async function refreshAdapters() {
  els.adaptersLoading.classList.remove("hidden");
  els.adaptersError.classList.add("hidden");
  els.adaptersList.classList.add("hidden");
  try {
    const data = await apiFetch("/api/v1/adapters");
    state.adapters = data.adapters || [];
    els.adaptersLoading.classList.add("hidden");

    const currentVal = els.pgAdapter.value;
    els.pgAdapter.replaceChildren();
    els.adaptersList.replaceChildren();

    for (const adapter of state.adapters) {
      const opt = document.createElement("option");
      opt.value = adapter.name;
      opt.textContent = adapter.is_default ? `${adapter.display_name} (Default)` : adapter.display_name;
      els.pgAdapter.appendChild(opt);

      const card = document.createElement("article");
      card.className = "adapter-card";
      const h3 = document.createElement("h3");
      h3.textContent = adapter.display_name;
      const meta = document.createElement("p");
      meta.className = "panel-subtitle mono";
      meta.textContent = `id: ${adapter.name} | ${adapter.home_url}`;
      const caps = document.createElement("div");
      caps.className = "btn-group";
      const t2i = document.createElement("span");
      t2i.className = "badge";
      t2i.textContent = adapter.capabilities.text_to_image ? "Text-to-Image: Yes" : "Text-to-Image: No";
      const edit = document.createElement("span");
      edit.className = "badge";
      edit.textContent = adapter.capabilities.image_edit ? "Image Edit: Yes" : "Image Edit: No";
      caps.append(t2i, edit);

      const aliases = document.createElement("p");
      aliases.className = "panel-subtitle";
      aliases.textContent = `Model aliases: ${(adapter.model_aliases || []).join(", ")}`;

      card.append(h3, meta, caps, aliases);
      els.adaptersList.appendChild(card);
    }

    if (currentVal && state.adapters.some((a) => a.name === currentVal)) {
      els.pgAdapter.value = currentVal;
    } else {
      const defAdapter = state.adapters.find((a) => a.is_default);
      if (defAdapter) {
        els.pgAdapter.value = defAdapter.name;
      }
    }
    els.adaptersList.classList.remove("hidden");
    updateCurlPreview();
  } catch (err) {
    els.adaptersLoading.classList.add("hidden");
    els.adaptersError.classList.remove("hidden");
    els.adaptersErrorText.textContent = `Could not load adapters: ${err.message}`;
  }
}

els.btnRefreshAdapters.addEventListener("click", () => refreshAdapters());

/* Live Logs via SSE */
function renderLogs() {
  const level = els.logsLevelFilter.value;
  const visible = state.logEntries.filter((entry) => level === "ALL" || entry.level === level);
  els.logsContainer.replaceChildren();
  if (visible.length === 0) {
    const empty = document.createElement("div");
    empty.className = "logs-empty";
    empty.textContent = state.logEntries.length === 0
      ? "Waiting for runtime log events..."
      : `No log lines at level ${level}.`;
    els.logsContainer.appendChild(empty);
    return;
  }

  for (const entry of visible) {
    const row = document.createElement("div");
    row.className = "log-line";
    const ts = document.createElement("span");
    ts.className = "log-ts";
    ts.textContent = entry.timestamp;
    const lvl = document.createElement("span");
    lvl.className = `log-lvl-${entry.level}`;
    lvl.textContent = `[${entry.level}]`;
    const msg = document.createElement("span");
    msg.textContent = entry.job_id ? `(${entry.job_id}) ${entry.message}` : entry.message;
    row.append(ts, lvl, msg);
    els.logsContainer.appendChild(row);
  }
  els.logsContainer.scrollTop = els.logsContainer.scrollHeight;
}

function connectLogStream() {
  if (state.logSource) {
    state.logSource.close();
    state.logSource = null;
  }
  if (state.logsPaused) {
    els.logsStreamStatus.textContent = "Stream: Paused";
    return;
  }
  const es = new EventSource("/api/v1/logs/stream");
  state.logSource = es;

  es.onopen = () => {
    els.logsStreamStatus.textContent = "Stream: Connected";
  };

  es.onmessage = (evt) => {
    if (state.logsPaused) return;
    try {
      const entry = JSON.parse(evt.data);
      if (!state.logEntries.some((x) => x.id === entry.id)) {
        state.logEntries.push(entry);
        if (state.logEntries.length > 300) {
          state.logEntries.shift();
        }
        renderLogs();
      }
    } catch {}
  };

  es.onerror = () => {
    els.logsStreamStatus.textContent = "Stream: Reconnecting...";
  };
}

els.logsLevelFilter.addEventListener("change", renderLogs);
els.btnClearLogs.addEventListener("click", () => {
  state.logEntries = [];
  renderLogs();
});
els.btnToggleLogsStream.addEventListener("click", () => {
  state.logsPaused = !state.logsPaused;
  els.btnToggleLogsStream.textContent = state.logsPaused ? "Resume stream" : "Pause stream";
  els.btnToggleLogsStream.setAttribute("aria-pressed", String(state.logsPaused));
  connectLogStream();
});

/* Modals */
function openImageModal(job, triggerEl) {
  state.lastModalReturnFocus = triggerEl || document.activeElement;
  els.modalImagesRow.replaceChildren();
  if (job.input_url) {
    const imgIn = document.createElement("img");
    imgIn.src = job.input_url;
    imgIn.alt = "Uploaded input image";
    imgIn.width = 400;
    imgIn.height = 400;
    els.modalImagesRow.appendChild(imgIn);
  }
  if (job.output_urls && job.output_urls[0]) {
    const imgOut = document.createElement("img");
    imgOut.src = job.output_urls[0];
    imgOut.alt = "Generated output image";
    imgOut.width = 400;
    imgOut.height = 400;
    els.modalImagesRow.appendChild(imgOut);
    els.modalDownloadLink.href = job.output_urls[0];
    els.modalDownloadLink.classList.remove("hidden");
  } else {
    els.modalDownloadLink.classList.add("hidden");
  }

  els.modalDetails.replaceChildren();
  const rows = [
    ["Job ID", job.id],
    ["Type / Adapter", `${job.job_type} via ${job.adapter}`],
    ["Status", job.status],
    ["Duration", job.duration_ms != null ? `${(job.duration_ms / 1000).toFixed(2)}s` : "-"],
    ["Created", job.created_at],
    ["Prompt", job.prompt],
  ];
  if (job.error) rows.push(["Error", job.error]);
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.dir = "auto";
    dd.textContent = v;
    els.modalDetails.append(dt, dd);
  }

  els.imageModal.showModal();
  els.closeImageModalBtn.focus();
}

function closeImageModal() {
  if (els.imageModal.open) {
    els.imageModal.close();
  }
  if (state.lastModalReturnFocus && typeof state.lastModalReturnFocus.focus === "function") {
    state.lastModalReturnFocus.focus();
  }
}

els.closeImageModalBtn.addEventListener("click", closeImageModal);
els.imageModal.addEventListener("click", (e) => {
  if (e.target === els.imageModal) closeImageModal();
});
els.imageModal.addEventListener("cancel", (e) => {
  e.preventDefault();
  closeImageModal();
});

els.openApiKeyBtn.addEventListener("click", () => {
  state.lastModalReturnFocus = els.openApiKeyBtn;
  els.apiKeyInput.value = getStoredApiKey();
  els.apiKeyModal.showModal();
  els.apiKeyInput.focus();
});

function closeApiKeyModal() {
  if (els.apiKeyModal.open) {
    els.apiKeyModal.close();
  }
  els.openApiKeyBtn.focus();
}

els.closeApiKeyModalBtn.addEventListener("click", closeApiKeyModal);
els.apiKeyModal.addEventListener("click", (e) => {
  if (e.target === els.apiKeyModal) closeApiKeyModal();
});
els.apiKeyModal.addEventListener("cancel", (e) => {
  e.preventDefault();
  closeApiKeyModal();
});

els.clearApiKeyBtn.addEventListener("click", async () => {
  try {
    localStorage.removeItem("duck_to_api_key");
    await fetch("/api/v1/auth/session", { method: "DELETE" });
  } catch {}
  els.apiKeyInput.value = "";
  updateCurlPreview();
  closeApiKeyModal();
  connectLogStream();
});

els.apiKeyForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const val = els.apiKeyInput.value.trim();
  try {
    if (val) {
      localStorage.setItem("duck_to_api_key", val);
      await syncDashboardSessionCookie();
    } else {
      localStorage.removeItem("duck_to_api_key");
      await fetch("/api/v1/auth/session", { method: "DELETE" });
    }
  } catch {}
  updateCurlPreview();
  closeApiKeyModal();
  connectLogStream();
  await Promise.all([refreshBrowserStatus(), refreshAdapters(), refreshJobs(true)]);
});

/* Boot */
async function init() {
  syncThemeButton();
  setPlaygroundMode("generate");
  await syncDashboardSessionCookie();
  await Promise.all([refreshAdapters(), refreshBrowserStatus(), refreshJobs(true)]);
  connectLogStream();
  setInterval(() => {
    refreshBrowserStatus();
    refreshJobs(false);
  }, 3000);
}

init();
