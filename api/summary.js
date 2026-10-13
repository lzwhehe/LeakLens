const { json, readData } = require("./_data");

module.exports = function handler(req, res) {
  const data = readData();
  const statuses = {};
  const platforms = {};
  let valid = 0;
  let highValue = 0;

  for (const item of data.items) {
    statuses[item.status || "unknown"] = (statuses[item.status || "unknown"] || 0) + 1;
    platforms[item.platform || "unknown"] = (platforms[item.platform || "unknown"] || 0) + 1;
    if (item.status === "valid" || item.status === "quota_exceeded") valid += 1;
    if (item.is_high_value) highValue += 1;
  }

  const trendMap = new Map();
  for (const item of data.items) {
    const date = String(item.found_time || "").slice(0, 10);
    if (date) trendMap.set(date, (trendMap.get(date) || 0) + 1);
  }
  const trend = [...trendMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-14)
    .map(([date, count]) => ({ date, count }));

  json(res, {
    app: "LeakLens",
    db_path: "data/leaklens-results.json",
    db_exists: data.db_exists,
    generated_at: data.generated_at,
    stats: {
      total: data.items.length,
      valid,
      high_value: highValue,
      scanned_blobs: data.scanned_blobs,
      statuses,
      platforms: Object.fromEntries(
        Object.entries(platforms).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      ),
    },
    progress: data.progress,
    recent: data.items.slice(0, 8),
    trend,
  });
};
