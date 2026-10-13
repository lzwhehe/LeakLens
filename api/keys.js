const { filterItems, json, parseLimit, parseOffset, readData } = require("./_data");

module.exports = function handler(req, res) {
  const data = readData();
  const query = Object.fromEntries(new URL(req.url, "https://leaklens.local").searchParams);
  const limit = parseLimit(query.limit);
  const offset = parseOffset(query.offset);
  const filtered = filterItems(data.items, query);

  json(res, {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    db_exists: data.db_exists,
    limit,
    offset,
  });
};
