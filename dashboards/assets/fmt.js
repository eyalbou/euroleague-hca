// Number formatters. Deterministic, NaN-safe. Never use toLocaleString().
function fmtNum(n, digits) {
  if (n === null || n === undefined || Number.isNaN(n)) return "--";
  var d = digits == null ? 1 : digits;
  var abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(d) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(d) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(d) + "K";
  if (abs >= 10) return n.toFixed(0);
  if (abs >= 1) return n.toFixed(d);
  return n.toFixed(Math.max(d, 2));
}

function fmtPct(n, digits) {
  if (n === null || n === undefined || Number.isNaN(n)) return "--";
  var d = digits == null ? 1 : digits;
  return (n * 100).toFixed(d) + "%";
}

function fmtSigned(n, digits) {
  if (n === null || n === undefined || Number.isNaN(n)) return "--";
  var d = digits == null ? 2 : digits;
  var s = n.toFixed(d);
  return n >= 0 ? "+" + s : s;
}

function fmtPVal(p) {
  if (p === null || p === undefined || Number.isNaN(p)) return "--";
  if (p < 0.001) return "<0.001";
  if (p < 0.01) return p.toFixed(3);
  return p.toFixed(3);
}
