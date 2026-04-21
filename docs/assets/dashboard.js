// Reads the embedded JSON payload, builds the page, instantiates every chart.
(function () {
  var payload = JSON.parse(document.getElementById('payload').textContent);
  var root = document.getElementById('root');

  var container = document.createElement('div');
  container.className = 'container';

  // Banner
  if (payload.sample_mode) {
    var banner = document.createElement('div');
    banner.className = 'banner';
    banner.textContent = 'SAMPLE MODE -- reduced data, not final results';
    container.appendChild(banner);
  }

  // Header
  var header = document.createElement('div');
  header.className = 'header';
  var h1 = document.createElement('h1');
  h1.textContent = payload.title;
  header.appendChild(h1);
  if (payload.subtitle) {
    var sub = document.createElement('p');
    sub.className = 'subtitle';
    sub.textContent = payload.subtitle;
    header.appendChild(sub);
  }
  container.appendChild(header);

  // KPIs
  if (payload.kpis && payload.kpis.length) {
    var row = document.createElement('div');
    row.className = 'kpi-row';
    payload.kpis.forEach(function (k) {
      var card = document.createElement('div');
      card.className = 'kpi';
      card.innerHTML = '<div class="label">' + k.label + '</div>' +
        '<div class="value">' + k.value + '</div>' +
        (k.caption ? '<div class="caption">' + k.caption + '</div>' : '');
      row.appendChild(card);
    });
    container.appendChild(row);
  }

  // Tabs? If any section has a `tab` property, render a tab bar.
  var hasTabs = payload.sections.some(function (s) { return s.tab; });
  var tabNames = [];
  if (hasTabs) {
    payload.sections.forEach(function (s) { if (tabNames.indexOf(s.tab) === -1) tabNames.push(s.tab || 'default'); });
    var bar = document.createElement('div');
    bar.className = 'tab-bar';
    tabNames.forEach(function (name, i) {
      var btn = document.createElement('button');
      btn.className = 'tab' + (i === 0 ? ' active' : '');
      btn.textContent = name;
      btn.dataset.tab = name;
      btn.addEventListener('click', function () {
        document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
        btn.classList.add('active');
        document.querySelectorAll('.tab-panel').forEach(function (p) {
          p.classList.toggle('active', p.dataset.tab === name);
        });
      });
      bar.appendChild(btn);
    });
    container.appendChild(bar);
  }

  // Sections
  payload.sections.forEach(function (section, i) {
    var block = document.createElement('div');
    block.className = hasTabs ? 'tab-panel' : '';
    if (hasTabs) {
      block.dataset.tab = section.tab || tabNames[0];
      if (section.tab === tabNames[0] || (!section.tab && i === 0)) block.classList.add('active');
    }
    var sec = document.createElement('div');
    sec.className = 'section';
    var h2 = document.createElement('h2');
    h2.textContent = section.title;
    sec.appendChild(h2);
    if (section.description) {
      var desc = document.createElement('p');
      desc.className = 'section-desc';
      desc.textContent = section.description;
      sec.appendChild(desc);
    }
    var grid = document.createElement('div');
    grid.className = 'chart-grid';
    (section.charts || []).forEach(function (chart) { grid.appendChild(buildChartCard(chart)); });
    sec.appendChild(grid);
    block.appendChild(sec);
    container.appendChild(block);
  });

  root.appendChild(container);

  function buildChartCard(spec) {
    var card = document.createElement('div');
    card.className = 'chart-card' + (spec.wide ? ' wide' : '') + (spec.tall ? ' tall' : '');
    var h3 = document.createElement('h3');
    h3.textContent = (spec.id ? spec.id + ' -- ' : '') + spec.title;
    card.appendChild(h3);
    if (spec.description) {
      var p = document.createElement('p');
      p.className = 'chart-desc';
      p.textContent = spec.description;
      card.appendChild(p);
    }

    if (spec.type === 'placeholder') {
      var ph = document.createElement('div');
      ph.className = 'placeholder';
      ph.textContent = spec.message || 'Graph requires data not yet ingested.';
      card.appendChild(ph);
      return card;
    }

    if (spec.type === 'table') {
      var tbl = document.createElement('table');
      tbl.className = 'data-table';
      var thead = document.createElement('thead');
      var tr = document.createElement('tr');
      spec.columns.forEach(function (c) {
        var th = document.createElement('th');
        th.textContent = c;
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      tbl.appendChild(thead);
      var tb = document.createElement('tbody');
      spec.rows.forEach(function (r) {
        var trr = document.createElement('tr');
        r.forEach(function (v) {
          var td = document.createElement('td');
          td.innerHTML = v == null ? '--' : v;
          trr.appendChild(td);
        });
        tb.appendChild(trr);
      });
      tbl.appendChild(tb);
      card.appendChild(tbl);
      if (spec.footnote) {
        var fn = document.createElement('div');
        fn.className = 'chart-footnote';
        fn.textContent = spec.footnote;
        card.appendChild(fn);
      }
      return card;
    }

    if (spec.type === 'text') {
      var wrap = document.createElement('div');
      wrap.innerHTML = spec.html || (spec.text || '').replace(/\n/g, '<br>');
      card.appendChild(wrap);
      return card;
    }

    var w = document.createElement('div');
    w.className = 'chart-wrap';
    var canvas = document.createElement('canvas');
    w.appendChild(canvas);
    card.appendChild(w);

    // Make Chart after DOM attach
    setTimeout(function () {
      try {
        switch (spec.type) {
          case 'line': makeLine(canvas, spec); break;
          case 'bar': makeBar(canvas, spec); break;
          case 'scatter':
            if (spec.autoTrend && spec.datasets && spec.datasets[0]) {
              spec.trendline = computeTrend(spec.datasets[0].data);
            }
            makeScatter(canvas, spec);
            break;
          case 'heatmap': makeHeatmap(canvas, spec); break;
          case 'forest': makeForest(canvas, spec); break;
          default:
            canvas.parentNode.textContent = '[unknown chart type: ' + spec.type + ']';
        }
      } catch (e) {
        canvas.parentNode.textContent = '[render error: ' + e.message + ']';
      }
    }, 0);

    if (spec.footnote) {
      var fn2 = document.createElement('div');
      fn2.className = 'chart-footnote';
      fn2.textContent = spec.footnote;
      card.appendChild(fn2);
    }
    return card;
  }
})();
