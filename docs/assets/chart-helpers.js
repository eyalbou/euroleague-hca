// Reusable Chart.js factories for our specific chart types.
// Each helper takes a canvas element + spec and returns a Chart instance.

function colorForTeam(team, idx) {
  if (!window._teamColors) window._teamColors = {};
  if (window._teamColors[team]) return window._teamColors[team];
  var c = window.CHART_PALETTE[(idx == null ? Object.keys(window._teamColors).length : idx) % window.CHART_PALETTE.length];
  window._teamColors[team] = c;
  return c;
}

function makeLine(canvas, spec) {
  // spec = { labels, datasets: [{ label, data }], yTitle, xTitle, annotations: [{value, label, color}] }
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels: spec.labels,
      datasets: spec.datasets.map(function (d, i) {
        return Object.assign({
          borderColor: d.color || window.CHART_PALETTE[i % window.CHART_PALETTE.length],
          backgroundColor: (d.color || window.CHART_PALETTE[i % window.CHART_PALETTE.length]) + '33',
          borderWidth: d.width || 2,
          borderDash: d.dash || [],
          pointRadius: d.pointRadius == null ? 2 : d.pointRadius,
          tension: 0.25,
          spanGaps: true,
        }, d);
      }),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: { legend: { display: spec.legend !== false } },
      scales: {
        x: { title: { display: !!spec.xTitle, text: spec.xTitle || '' } },
        y: { title: { display: !!spec.yTitle, text: spec.yTitle || '' }, beginAtZero: spec.yBeginAtZero || false },
      },
    },
  });
}

function makeBar(canvas, spec) {
  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: spec.labels,
      datasets: spec.datasets.map(function (d, i) {
        return Object.assign({
          backgroundColor: d.colors || (d.color || window.CHART_PALETTE[i % window.CHART_PALETTE.length]),
          borderColor: 'transparent',
        }, d);
      }),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: spec.horizontal ? 'y' : 'x',
      plugins: { legend: { display: spec.legend !== false } },
      scales: {
        x: { title: { display: !!spec.xTitle, text: spec.xTitle || '' }, stacked: !!spec.stacked },
        y: { title: { display: !!spec.yTitle, text: spec.yTitle || '' }, stacked: !!spec.stacked },
      },
    },
  });
}

function makeScatter(canvas, spec) {
  // spec = { datasets: [{label, data: [{x,y,r?,team?}]}], trendline: [{x,y}], xTitle, yTitle, annotation }
  var datasets = spec.datasets.map(function (d, i) {
    return Object.assign({
      backgroundColor: (d.color || window.CHART_PALETTE[i % window.CHART_PALETTE.length]) + 'cc',
      borderColor: d.color || window.CHART_PALETTE[i % window.CHART_PALETTE.length],
      pointRadius: d.pointRadius || 4,
    }, d);
  });
  if (spec.trendline && spec.trendline.length) {
    datasets.push({
      type: 'line', label: spec.trendlineLabel || 'trend',
      data: spec.trendline, borderColor: '#9aa4b2', borderDash: [5, 5],
      borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0,
    });
  }
  return new Chart(canvas, {
    type: 'scatter',
    data: { datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: spec.legend !== false },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              var p = ctx.raw;
              var parts = [];
              if (p.label) parts.push(p.label);
              parts.push('x=' + (typeof p.x === 'number' ? p.x.toFixed(2) : p.x));
              parts.push('y=' + (typeof p.y === 'number' ? p.y.toFixed(2) : p.y));
              if (p.n != null) parts.push('n=' + p.n);
              return parts.join(' | ');
            },
          },
        },
      },
      scales: {
        x: { title: { display: !!spec.xTitle, text: spec.xTitle || '' } },
        y: { title: { display: !!spec.yTitle, text: spec.yTitle || '' } },
      },
    },
  });
}

function makeHeatmap(canvas, spec) {
  // spec = { xs, ys, values: [[..]], valueLabel }
  var data = [];
  for (var yi = 0; yi < spec.ys.length; yi++) {
    for (var xi = 0; xi < spec.xs.length; xi++) {
      var v = spec.values[yi][xi];
      data.push({ x: spec.xs[xi], y: spec.ys[yi], v: v });
    }
  }
  var vals = data.map(function (d) { return d.v; }).filter(function (v) { return v != null && !Number.isNaN(v); });
  var vmin = Math.min.apply(null, vals), vmax = Math.max.apply(null, vals);
  var vabs = Math.max(Math.abs(vmin), Math.abs(vmax)) || 1;

  return new Chart(canvas, {
    type: 'matrix',
    data: {
      datasets: [{
        label: spec.valueLabel || '',
        data: data,
        backgroundColor: function (ctx) {
          var v = ctx.raw.v;
          if (v == null || Number.isNaN(v)) return '#1e242f';
          var t = v / vabs;
          if (t >= 0) return 'rgba(79,140,255,' + Math.min(1, Math.max(0.15, t)) + ')';
          return 'rgba(240,107,107,' + Math.min(1, Math.max(0.15, -t)) + ')';
        },
        borderColor: '#262d3a',
        borderWidth: 1,
        width: function (ctx) {
          var a = ctx.chart.chartArea;
          return a ? (a.right - a.left) / spec.xs.length - 2 : 10;
        },
        height: function (ctx) {
          var a = ctx.chart.chartArea;
          return a ? (a.bottom - a.top) / spec.ys.length - 2 : 10;
        },
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function () { return ''; },
            label: function (ctx) {
              var r = ctx.raw;
              return r.y + ' @ ' + r.x + ': ' + (r.v == null ? 'n/a' : fmtSigned(r.v));
            },
          },
        },
      },
      scales: {
        x: { type: 'category', labels: spec.xs, offset: true, grid: { display: false } },
        y: { type: 'category', labels: spec.ys, offset: true, grid: { display: false }, reverse: true },
      },
    },
  });
}

function makeForest(canvas, spec) {
  // Forest plot: horizontal lines with center dot per team.
  // spec = { teams: [{label, mean, lo, hi, color?}], xTitle, zeroLine }
  var labels = spec.teams.map(function (t) { return t.label; });
  var points = spec.teams.map(function (t) { return t.mean; });
  var errBars = spec.teams.map(function (t) { return [t.lo, t.hi]; });
  var palette = window.CHART_PALETTE;
  var dataset = {
    label: spec.label || 'estimate',
    data: points,
    backgroundColor: spec.teams.map(function (t, i) { return t.color || palette[i % palette.length]; }),
    borderColor: 'transparent',
    barPercentage: 0.05,
    borderWidth: 0,
  };

  // Draw CI lines via an auxiliary scatter dataset so Chart.js v4 renders them
  var ciPoints = [];
  spec.teams.forEach(function (t, i) {
    ciPoints.push({ x: t.lo, y: i });
    ciPoints.push({ x: t.hi, y: i });
    ciPoints.push({ x: null, y: null });
  });

  return new Chart(canvas, {
    type: 'scatter',
    data: {
      datasets: [
        {
          type: 'line',
          label: '95% CI',
          data: ciPoints,
          borderColor: '#9aa4b2',
          borderWidth: 1.5,
          pointRadius: 0,
          showLine: true,
          spanGaps: false,
        },
        {
          type: 'scatter',
          label: spec.label || 'estimate',
          data: spec.teams.map(function (t, i) { return { x: t.mean, y: i, label: t.label }; }),
          backgroundColor: spec.teams.map(function (t, i) { return t.color || palette[i % palette.length]; }),
          pointRadius: 6,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              var i = ctx.raw.y;
              if (i == null) return '';
              var t = spec.teams[i];
              return t.label + ': ' + fmtSigned(t.mean) + ' [' + fmtSigned(t.lo) + ', ' + fmtSigned(t.hi) + ']';
            },
          },
        },
      },
      scales: {
        x: { title: { display: !!spec.xTitle, text: spec.xTitle || '' } },
        y: { type: 'linear', ticks: {
          callback: function (v) { return labels[v] || ''; },
          stepSize: 1, autoSkip: false,
        }, min: -0.5, max: labels.length - 0.5, grid: { display: false }, reverse: true },
      },
    },
  });
}

function fmtSigned(n) {
  if (n == null || Number.isNaN(n)) return '--';
  return (n >= 0 ? '+' : '') + n.toFixed(2);
}

function computeTrend(points) {
  // Simple OLS for scatter trendline
  if (!points || points.length < 2) return [];
  var n = points.length;
  var sx = 0, sy = 0, sxy = 0, sx2 = 0;
  for (var i = 0; i < n; i++) { sx += points[i].x; sy += points[i].y; sxy += points[i].x * points[i].y; sx2 += points[i].x * points[i].x; }
  var slope = (n * sxy - sx * sy) / (n * sx2 - sx * sx);
  var intercept = (sy - slope * sx) / n;
  var xs = points.map(function (p) { return p.x; });
  var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
  return [{ x: xmin, y: slope * xmin + intercept }, { x: xmax, y: slope * xmax + intercept }];
}

function pearsonR(points) {
  if (!points || points.length < 2) return null;
  var n = points.length;
  var mx = 0, my = 0;
  for (var i = 0; i < n; i++) { mx += points[i].x; my += points[i].y; }
  mx /= n; my /= n;
  var num = 0, dx2 = 0, dy2 = 0;
  for (var j = 0; j < n; j++) {
    var dx = points[j].x - mx, dy = points[j].y - my;
    num += dx * dy; dx2 += dx * dx; dy2 += dy * dy;
  }
  var denom = Math.sqrt(dx2 * dy2);
  return denom === 0 ? null : num / denom;
}
