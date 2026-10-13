const { filterItems, readData } = require("./_data");

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

module.exports = function handler(req, res) {
  const data = readData();
  const query = Object.fromEntries(new URL(req.url, "https://leaklens.local").searchParams);
  const items = filterItems(data.items, query).slice(0, 500);
  const fields = [
    "id",
    "platform",
    "status",
    "api_key_masked",
    "base_url",
    "balance",
    "source_url",
    "model_tier",
    "rpm",
    "is_high_value",
    "found_time",
  ];
  const rows = [fields.join(",")];

  for (const item of items) {
    rows.push(
      [
        item.id,
        item.platform,
        item.status,
        item.api_key,
        item.base_url,
        item.balance,
        item.source_url,
        item.model_tier,
        item.rpm,
        item.is_high_value ? 1 : 0,
        item.found_time,
      ].map(csvEscape).join(",")
    );
  }

  const body = rows.join("\n") + "\n";
  res.statusCode = 200;
  res.setHeader("Content-Type", "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", 'attachment; filename="leaklens-results.csv"');
  res.setHeader("Cache-Control", "s-maxage=30, stale-while-revalidate=300");
  res.end(body);
};
