const colors = ["#16845b", "#2868b7", "#b7791f", "#c24135", "#6d4baf", "#0f766e", "#805ad5", "#4a5568"];
const statusLabels = {
  valid: "Valid",
  quota_exceeded: "Quota",
  invalid: "Invalid",
  connection_error: "Connection",
  pending: "Pending",
  unverified: "Unverified",
  unknown: "Unknown"
};

const els = {
  dbState: document.querySelector("#dbState"),
  scanState: document.querySelector("#scanState"),
  scanMeta: document.querySelector("#scanMeta"),
  scanForm: document.querySelector("#scanForm"),
  githubTokens: document.querySelector("#githubTokens"),
  scanMode: document.querySelector("#scanMode"),
  dbPath: document.querySelector("#dbPath"),
  proxyUrl: document.querySelector("#proxyUrl"),
  pastebinKey: document.querySelector("#pastebinKey"),
  sourceGist: document.querySelector("#sourceGist"),
  sourceGitlab: document.querySelector("#sourceGitlab"),
  sourcePastebin: document.querySelector("#sourcePastebin"),
  sourceSearchcode: document.querySelector("#sourceSearchcode"),
  sourceRealtime: document.querySelector("#sourceRealtime"),
  sourceAll: document.querySelector("#sourceAll"),
  noCache: document.querySelector("#noCache"),
  startScan: document.querySelector("#startScan"),
  stopScan: document.querySelector("#stopScan"),
  scanLogs: document.querySelector("#scanLogs"),
  generatedAt: document.querySelector("#generatedAt"),
  progressText: document.querySelector("#progressText"),
  progressBar: document.querySelector("#progressBar"),
  metricTotal: document.querySelector("#metricTotal"),
  metricValid: document.querySelector("#metricValid"),
  metricHigh: document.querySelector("#metricHigh"),
  metricBlobs: document.querySelector("#metricBlobs"),
  statusChart: document.querySelector("#statusChart"),
  platformChart: document.querySelector("#platformChart"),
  statusLegend: document.querySelector("#statusLegend"),
  statusFilter: document.querySelector("#statusFilter"),
  platformFilter: document.querySelector("#platformFilter"),
  searchBox: document.querySelector("#searchBox"),
  keysTable: document.querySelector("#keysTable"),
  refreshButton: document.querySelector("#refreshButton"),
  exportLink: document.querySelector("#exportLink")
};

function compactNumber(value) {
  return new Intl.NumberFormat("en", { notation: value >= 10000 ? "compact" : "standard" }).format(value || 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function chartSize(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(Number(canvas.getAttribute("height")) * ratio));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: Number(canvas.getAttribute("height")) };
}

function drawDoughnut(canvas, data) {
  const { ctx, width, height } = chartSize(canvas);
  ctx.clearRect(0, 0, width, height);
  const entries = Object.entries(data || {}).filter(([, value]) => value > 0);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.38;
  const inner = radius * 0.58;

  if (!total) {
    ctx.fillStyle = "#637083";
    ctx.textAlign = "center";
    ctx.font = "600 14px system-ui";
    ctx.fillText("No data", cx, cy);
    return;
  }

  let start = -Math.PI / 2;
  entries.forEach(([label, value], index) => {
    const angle = (value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, start, start + angle);
    ctx.closePath();
    ctx.fillStyle = colors[index % colors.length];
    ctx.fill();
    start += angle;
  });

  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.arc(cx, cy, inner, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalCompositeOperation = "source-over";

  ctx.fillStyle = "#182230";
  ctx.textAlign = "center";
  ctx.font = "750 28px system-ui";
  ctx.fillText(compactNumber(total), cx, cy - 2);
  ctx.fillStyle = "#637083";
  ctx.font = "700 12px system-ui";
  ctx.fillText("keys", cx, cy + 18);
}

function drawBars(canvas, data) {
  const { ctx, width, height } = chartSize(canvas);
  ctx.clearRect(0, 0, width, height);
  const entries = Object.entries(data || {}).slice(0, 8);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  const left = 96;
  const right = 18;
  const barHeight = 18;
  const gap = 10;
  let y = 20;

  if (!entries.length) {
    ctx.fillStyle = "#637083";
    ctx.textAlign = "center";
    ctx.font = "600 14px system-ui";
    ctx.fillText("No data", width / 2, height / 2);
    return;
  }

  entries.forEach(([label, value], index) => {
    const barWidth = ((width - left - right) * value) / max;
    ctx.fillStyle = "#637083";
    ctx.textAlign = "right";
    ctx.font = "700 12px system-ui";
    ctx.fillText(label, left - 12, y + 13);
    ctx.fillStyle = colors[index % colors.length];
    ctx.fillRect(left, y, Math.max(2, barWidth), barHeight);
    ctx.fillStyle = "#182230";
    ctx.textAlign = "left";
    ctx.fillText(compactNumber(value), left + barWidth + 8, y + 13);
    y += barHeight + gap;
  });
}

function renderLegend(data) {
  const entries = Object.entries(data || {}).filter(([, value]) => value > 0);
  els.statusLegend.innerHTML = entries
    .map(([label, value], index) => `
      <span class="legend-item">
        <i class="legend-dot" style="background:${colors[index % colors.length]}"></i>
        ${escapeHtml(statusLabels[label] || label)} ${compactNumber(value)}
      </span>
    `)
    .join("");
}

function updatePlatformOptions(platforms) {
  const selected = els.platformFilter.value;
  const names = Object.keys(platforms || {});
  els.platformFilter.innerHTML = '<option value="">All</option>' + names.map((name) => {
    return `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`;
  }).join("");
  if (names.includes(selected)) {
    els.platformFilter.value = selected;
  }
}

function currentParams() {
  const params = new URLSearchParams();
  if (els.statusFilter.value) params.set("status", els.statusFilter.value);
  if (els.platformFilter.value) params.set("platform", els.platformFilter.value);
  if (els.searchBox.value.trim()) params.set("q", els.searchBox.value.trim());
  params.set("limit", "100");
  return params;
}

function sourceCell(item) {
  if (!item.source_url) return "";
  const label = item.source_host || item.source_url;
  return `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function renderRows(items) {
  if (!items.length) {
    els.keysTable.innerHTML = '<tr><td colspan="7" class="empty">No matching records</td></tr>';
    return;
  }
  els.keysTable.innerHTML = items.map((item) => {
    const high = item.is_high_value ? " high" : "";
    return `
      <tr>
        <td><span class="platform${high}">${escapeHtml(item.platform || "-")}</span></td>
        <td><span class="badge status-${escapeHtml(item.status)}">${escapeHtml(statusLabels[item.status] || item.status || "-")}</span></td>
        <td><code>${escapeHtml(item.api_key || "-")}</code></td>
        <td>${escapeHtml(item.model_tier || "-")}</td>
        <td>${escapeHtml(item.rpm || "-")}</td>
        <td class="source">${sourceCell(item)}</td>
        <td>${escapeHtml(item.found_time || "-")}</td>
      </tr>
    `;
  }).join("");
}

async function loadSummary() {
  const response = await fetch("/api/summary", { cache: "no-store" });
  const data = await response.json();
  els.dbState.textContent = data.db_exists ? "Database online" : "Waiting for database";
  els.dbState.className = `state-pill ${data.db_exists ? "ok" : "warn"}`;
  els.generatedAt.textContent = new Date(data.generated_at).toLocaleTimeString();
  els.metricTotal.textContent = compactNumber(data.stats.total);
  els.metricValid.textContent = compactNumber(data.stats.valid);
  els.metricHigh.textContent = compactNumber(data.stats.high_value);
  els.metricBlobs.textContent = compactNumber(data.stats.scanned_blobs);

  const progressTotal = data.progress.total || 0;
  const progressCurrent = data.progress.current_index || 0;
  const percent = progressTotal ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100)) : 0;
  els.progressText.textContent = progressTotal ? `${progressCurrent}/${progressTotal}` : "No active scan";
  els.progressBar.style.width = `${percent}%`;

  updatePlatformOptions(data.stats.platforms);
  drawDoughnut(els.statusChart, data.stats.statuses);
  drawBars(els.platformChart, data.stats.platforms);
  renderLegend(data.stats.statuses);
}

async function loadKeys() {
  const params = currentParams();
  els.exportLink.href = `/api/export.csv?${params.toString()}`;
  const response = await fetch(`/api/keys?${params.toString()}`, { cache: "no-store" });
  const data = await response.json();
  renderRows(data.items || []);
}

async function refreshAll() {
  await loadSummary();
  await loadKeys();
}

function scanPayload() {
  return {
    github_tokens: els.githubTokens.value,
    mode: els.scanMode.value,
    db_path: els.dbPath.value,
    proxy_url: els.proxyUrl.value,
    pastebin_key: els.pastebinKey.value,
    gist: els.sourceGist.checked,
    gitlab: els.sourceGitlab.checked,
    pastebin: els.sourcePastebin.checked,
    searchcode: els.sourceSearchcode.checked,
    realtime: els.sourceRealtime.checked,
    all_sources: els.sourceAll.checked,
    no_cache: els.noCache.checked
  };
}

async function startScan(event) {
  event.preventDefault();
  els.startScan.disabled = true;
  try {
    const response = await fetch("/api/scan/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scanPayload())
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to start scanner");
    renderScanStatus(data);
  } catch (error) {
    els.scanLogs.textContent = error.message;
  } finally {
    els.startScan.disabled = false;
  }
}

async function stopScan() {
  els.stopScan.disabled = true;
  try {
    const response = await fetch("/api/scan/stop", { method: "POST" });
    renderScanStatus(await response.json());
  } catch (error) {
    els.scanLogs.textContent = error.message;
  } finally {
    els.stopScan.disabled = false;
  }
}

async function loadScanStatus() {
  try {
    const response = await fetch("/api/scan/status", { cache: "no-store" });
    if (!response.ok) return;
    renderScanStatus(await response.json());
  } catch {
    // The Vercel-only static view does not expose scanner control endpoints.
  }
}

function renderScanStatus(data) {
  const running = Boolean(data.running);
  els.scanState.textContent = running ? "Scanner running" : "Scanner idle";
  els.scanState.className = `state-pill ${running ? "ok" : ""}`;
  els.scanMeta.textContent = running
    ? `PID ${data.pid || "-"}`
    : data.returncode === null || data.returncode === undefined
      ? "Idle"
      : `Exited ${data.returncode}`;
  els.stopScan.disabled = !running;
  els.dbPath.value = data.db_path || els.dbPath.value;
  els.scanLogs.textContent = (data.logs || []).join("\n") || "Waiting for scanner...";
  els.scanLogs.scrollTop = els.scanLogs.scrollHeight;
}

let searchTimer = 0;
els.scanForm.addEventListener("submit", startScan);
els.stopScan.addEventListener("click", stopScan);
els.refreshButton.addEventListener("click", refreshAll);
els.statusFilter.addEventListener("change", loadKeys);
els.platformFilter.addEventListener("change", loadKeys);
els.searchBox.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadKeys, 180);
});
window.addEventListener("resize", () => loadSummary());

refreshAll().catch((error) => {
  els.dbState.textContent = "Dashboard error";
  els.dbState.className = "state-pill warn";
  els.keysTable.innerHTML = `<tr><td colspan="7" class="empty">${escapeHtml(error.message)}</td></tr>`;
});
loadScanStatus();
setInterval(refreshAll, 5000);
setInterval(loadScanStatus, 2000);
