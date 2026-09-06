const STAGES = [
  { id: "linkedin_fetch", label: "LinkedIn fetch" },
  { id: "company_website", label: "Company website" },
  { id: "careers_page", label: "Careers page" },
  { id: "jobs_list", label: "Jobs list" },
];

// ---------- Tabs ----------

const tabResolve = document.getElementById("tab-resolve");
const tabBatch = document.getElementById("tab-batch");
const panelResolve = document.getElementById("panel-resolve");
const panelBatch = document.getElementById("panel-batch");

function activateTab(name) {
  const resolveActive = name === "resolve";
  panelResolve.classList.toggle("hidden", !resolveActive);
  panelBatch.classList.toggle("hidden", resolveActive);
  tabResolve.classList.toggle("border-blue-500", resolveActive);
  tabResolve.classList.toggle("text-slate-100", resolveActive);
  tabResolve.classList.toggle("border-transparent", !resolveActive);
  tabResolve.classList.toggle("text-slate-400", !resolveActive);
  tabBatch.classList.toggle("border-blue-500", !resolveActive);
  tabBatch.classList.toggle("text-slate-100", !resolveActive);
  tabBatch.classList.toggle("border-transparent", resolveActive);
  tabBatch.classList.toggle("text-slate-400", resolveActive);
}

tabResolve.addEventListener("click", () => activateTab("resolve"));
tabBatch.addEventListener("click", () => activateTab("batch"));

// ---------- Resolve tab ----------

const resolveForm = document.getElementById("resolve-form");
const resolveUrlInput = document.getElementById("resolve-url");
const resolveSubmit = document.getElementById("resolve-submit");
const statusBanner = document.getElementById("status-banner");
const stageCardsEl = document.getElementById("stage-cards");

function renderStageCards() {
  stageCardsEl.innerHTML = STAGES.map(
    (stage) => `
    <div id="card-${stage.id}" data-state="idle" class="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="icon w-4 h-4 flex items-center justify-center shrink-0"></span>
          <span class="text-sm font-medium text-slate-200">${stage.label}</span>
        </div>
        <span class="elapsed text-xs text-slate-500"></span>
      </div>
      <div class="value text-sm mt-1 ml-7 text-slate-500">Waiting…</div>
    </div>`
  ).join("");
}

function stageIcon(state) {
  if (state === "running") return '<span class="spinner"></span>';
  if (state === "success") return '<span class="text-emerald-400">✓</span>';
  if (state === "error") return '<span class="text-red-400">✕</span>';
  return '<span class="text-slate-600">•</span>';
}

function setStageState(id, { state, value, error, elapsedMs }) {
  const card = document.getElementById(`card-${id}`);
  if (!card) return;
  card.dataset.state = state;
  card.querySelector(".icon").innerHTML = stageIcon(state);
  card.querySelector(".elapsed").textContent = elapsedMs != null ? `${elapsedMs} ms` : "";

  const valueEl = card.querySelector(".value");
  if (state === "running") {
    valueEl.textContent = "Working…";
    valueEl.className = "value text-sm mt-1 ml-7 text-slate-500";
  } else if (state === "success") {
    valueEl.innerHTML = `<a href="${value}" target="_blank" rel="noopener" class="text-blue-400 hover:underline break-all">${value}</a>`;
    valueEl.className = "value text-sm mt-1 ml-7";
  } else if (state === "error") {
    valueEl.textContent = error || "Failed";
    valueEl.className = "value text-sm mt-1 ml-7 text-red-400";
  } else {
    valueEl.textContent = "Waiting…";
    valueEl.className = "value text-sm mt-1 ml-7 text-slate-500";
  }
}

function resetStages() {
  renderStageCards();
  setStageState(STAGES[0].id, { state: "running" });
}

function showBanner(status, text) {
  statusBanner.classList.remove("hidden");
  statusBanner.textContent = text;
  statusBanner.className =
    "mb-6 rounded-lg px-4 py-3 text-sm " +
    (status === "success"
      ? "bg-emerald-950 text-emerald-300 border border-emerald-900"
      : "bg-red-950 text-red-300 border border-red-900");
}

resolveForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const url = resolveUrlInput.value.trim();
  if (!url) return;

  resolveSubmit.disabled = true;
  statusBanner.classList.add("hidden");
  resetStages();

  const source = new EventSource(`/resolve/stream?url=${encodeURIComponent(url)}`);

  STAGES.forEach((stage, index) => {
    source.addEventListener(stage.id, (event) => {
      const data = JSON.parse(event.data);
      setStageState(stage.id, {
        state: data.status,
        value: data.value,
        error: data.error,
        elapsedMs: data.elapsed_ms,
      });
      const next = STAGES[index + 1];
      if (data.status === "success" && next) {
        setStageState(next.id, { state: "running" });
      }
    });
  });

  source.addEventListener("done", (event) => {
    const data = JSON.parse(event.data);
    showBanner(data.status, data.status === "success" ? `${data.reason} — platform: ${data.ats_platform || "custom careers page"}` : data.reason || "Resolution failed");
    resolveSubmit.disabled = false;
    source.close();
  });

  source.onerror = () => {
    resolveSubmit.disabled = false;
    source.close();
  };
});

// ---------- Batch tab ----------

const batchUrlsInput = document.getElementById("batch-urls");
const batchSubmit = document.getElementById("batch-submit");
const batchSummary = document.getElementById("batch-summary");
const batchTableBody = document.getElementById("batch-table-body");

function statusPill(status) {
  const ok = status === "success";
  return `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
    ok ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"
  }">${ok ? "success" : "failed"}</span>`;
}

batchSubmit.addEventListener("click", async () => {
  const urls = batchUrlsInput.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!urls.length) return;

  batchSubmit.disabled = true;
  batchSubmit.textContent = "Running…";
  batchSummary.classList.add("hidden");
  batchTableBody.innerHTML = "";

  try {
    const response = await fetch("/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
    });
    const data = await response.json();

    const s = data.summary;
    batchSummary.classList.remove("hidden");
    batchSummary.innerHTML = `
      <div class="flex flex-wrap gap-2">
        <span class="px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs">${s.succeeded}/${s.total} succeeded</span>
        <span class="px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs">${s.success_rate}% success rate</span>
        <span class="px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs">avg ${s.avg_elapsed_ms} ms</span>
      </div>`;

    batchTableBody.innerHTML = data.results
      .map(
        (r) => `
      <tr>
        <td class="px-3 py-2 max-w-xs truncate text-slate-400">${r.linkedin_job_url}</td>
        <td class="px-3 py-2">${statusPill(r.status)}</td>
        <td class="px-3 py-2">${r.company_name || "—"}</td>
        <td class="px-3 py-2 max-w-xs truncate">${
          r.jobs_list_url ? `<a href="${r.jobs_list_url}" target="_blank" rel="noopener" class="text-blue-400 hover:underline">${r.jobs_list_url}</a>` : (r.reason || "—")
        }</td>
        <td class="px-3 py-2 text-slate-400">${r.elapsed_ms} ms</td>
      </tr>`
      )
      .join("");
  } finally {
    batchSubmit.disabled = false;
    batchSubmit.textContent = "Run batch";
  }
});

renderStageCards();
