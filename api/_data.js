const fs = require("fs");
const path = require("path");

const DATA_PATH = path.join(process.cwd(), "data", "leaklens-results.json");
const VALID_STATUSES = new Set([
  "pending",
  "valid",
  "invalid",
  "quota_exceeded",
  "connection_error",
  "unverified",
]);

function readData() {
  try {
    const raw = fs.readFileSync(DATA_PATH, "utf8");
    const parsed = JSON.parse(raw);
    const items = Array.isArray(parsed.items) ? parsed.items : [];
    return {
      generated_at: parsed.generated_at || new Date().toISOString(),
      progress: parsed.progress || { current_index: 0, total: 0, is_completed: false },
      scanned_blobs: Number(parsed.scanned_blobs || 0),
      items: items.map(normalizeItem),
      db_exists: true,
    };
  } catch (error) {
    return {
      generated_at: new Date().toISOString(),
      progress: { current_index: 0, total: 0, is_completed: false },
      scanned_blobs: 0,
      items: [],
      db_exists: false,
    };
  }
}

function normalizeItem(item, index) {
  const apiKey = String(item.api_key || "");
  return {
    id: item.id || index + 1,
    platform: String(item.platform || ""),
    status: String(item.status || "pending"),
    api_key: item.api_key_masked || maskSecret(apiKey),
    base_url: String(item.base_url || ""),
    balance: String(item.balance || ""),
    source_url: String(item.source_url || ""),
    source_host: sourceHost(item.source_url || ""),
    model_tier: String(item.model_tier || ""),
    rpm: Number(item.rpm || 0),
    is_high_value: Boolean(item.is_high_value),
    found_time: formatTime(item.found_time || ""),
  };
}

function maskSecret(value) {
  if (!value) return "";
  if (value.length <= 10) {
    return value.slice(0, 2) + "*".repeat(Math.max(value.length - 4, 0)) + value.slice(-2);
  }
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function sourceHost(value) {
  try {
    return new URL(value).host;
  } catch {
    return "";
  }
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const hh = String(date.getHours()).padStart(2, "0");
    const mi = String(date.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  }
  return String(value).slice(0, 16).replace("T", " ");
}

function filterItems(items, query) {
  const status = String(query.status || "").trim();
  const platform = String(query.platform || "").trim();
  const q = String(query.q || "").trim().toLowerCase();

  return items.filter((item) => {
    if (status && VALID_STATUSES.has(status) && item.status !== status) return false;
    if (platform && item.platform !== platform) return false;
    if (!q) return true;
    return [
      item.platform,
      item.status,
      item.base_url,
      item.balance,
      item.source_url,
      item.model_tier,
    ].some((field) => String(field || "").toLowerCase().includes(q));
  });
}

function parseLimit(value, fallback = 100) {
  const parsed = Number.parseInt(value || fallback, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(500, Math.max(1, parsed));
}

function parseOffset(value) {
  const parsed = Number.parseInt(value || 0, 10);
  if (Number.isNaN(parsed)) return 0;
  return Math.min(1000000, Math.max(0, parsed));
}

function json(res, payload, status = 200) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "s-maxage=30, stale-while-revalidate=300");
  res.end(JSON.stringify(payload));
}

module.exports = {
  filterItems,
  json,
  parseLimit,
  parseOffset,
  readData,
};
