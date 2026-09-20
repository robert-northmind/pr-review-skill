/** Diff projection and selection independent of the renderer. */
export function visibleRows(file, mode) {
  const rows = file.rows || [];
  return mode
    ? rows.filter((row) =>
        mode === "base" ? row.old !== null : row.new !== null,
      )
    : rows;
}
export function diffEntries(file, mode, extra = new Set()) {
  const rows = visibleRows(file, mode),
    visible = new Set(extra);
  // Linear work, including large files with many changed lines.
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].kind !== "context") {
      for (
        let n = Math.max(0, i - 3);
        n <= Math.min(rows.length - 1, i + 3);
        n++
      )
        visible.add(rows[n].id);
    }
  }
  const result = [];
  for (let i = 0; i < rows.length; ) {
    if (mode || visible.has(rows[i].id)) {
      result.push(rows[i++]);
      continue;
    }
    const start = i;
    while (i < rows.length && !visible.has(rows[i].id)) i++;
    result.push({
      gap: true,
      start: rows[start].id,
      end: rows[i - 1].id,
      count: i - start,
    });
  }
  return result;
}
export function splitPairs(entries) {
  const pairs = [];
  for (let i = 0; i < entries.length; ) {
    const row = entries[i];
    if (row.gap || row.kind === "context") {
      pairs.push([row, row]);
      i++;
      continue;
    }
    const removed = [],
      added = [];
    while (
      i < entries.length &&
      !entries[i].gap &&
      entries[i].kind !== "context"
    ) {
      const changed = entries[i++];
      (changed.kind === "delete" ? removed : added).push(changed);
    }
    for (let n = 0; n < Math.max(removed.length, added.length); n++)
      pairs.push([removed[n], added[n]]);
  }
  return pairs;
}
export function selectionFor(
  comparison,
  fileIndex,
  start,
  end,
  side = "head",
  sideOnly = false,
  mode,
) {
  const file = comparison.files[fileIndex];
  const rows = visibleRows(file, mode).filter(
    (row) =>
      row.id >= Math.min(start, end) &&
      row.id <= Math.max(start, end) &&
      (!sideOnly || (side === "base" ? row.old : row.new) !== null),
  );
  const lines = rows
    .map((row) => (side === "base" ? row.old : row.new))
    .filter((n) => n !== null);
  const other = rows.some(
    (row) => (side === "base" ? row.old : row.new) === null,
  );
  const label =
    (lines.length
      ? `${side === "base" ? "Base" : "Head"} L${lines[0]}${lines.length > 1 ? "–" + lines.at(-1) : ""}`
      : "Changed lines") + (other ? " + opposite-side changes" : "");
  return {
    file: fileIndex,
    ids: rows.map((row) => row.id),
    side,
    label,
    path: file.path,
    head: comparison.head,
    base: comparison.base,
    snippet: rows
      .map(
        (row) =>
          `${row.kind === "add" ? "+" : row.kind === "delete" ? "-" : " "} ${row.text}`,
      )
      .join("\n"),
  };
}
