// Chart.js global defaults matching the CSS. Chart.js does NOT inherit from CSS so this is mandatory.

(function () {
  var styles = getComputedStyle(document.documentElement);
  var textColor = styles.getPropertyValue('--text').trim() || '#e7ecf3';
  var textDim = styles.getPropertyValue('--text-dim').trim() || '#9aa4b2';
  var border = styles.getPropertyValue('--border').trim() || '#262d3a';

  if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = '"DM Sans", "Wix Madefor Display", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    Chart.defaults.font.size = 11;
    Chart.defaults.color = textDim;
    Chart.defaults.borderColor = border;
    Chart.defaults.plugins.legend.labels.color = textDim;
    Chart.defaults.plugins.legend.position = 'bottom';
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.boxHeight = 12;
    Chart.defaults.plugins.legend.labels.padding = 12;
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(22, 26, 34, 0.96)';
    Chart.defaults.plugins.tooltip.titleColor = textColor;
    Chart.defaults.plugins.tooltip.bodyColor = textColor;
    Chart.defaults.plugins.tooltip.borderColor = border;
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 4;
    Chart.defaults.scale.grid.color = border;
    Chart.defaults.scale.ticks.color = textDim;
  }

  window.CHART_PALETTE = [
    styles.getPropertyValue('--chart-1').trim(),
    styles.getPropertyValue('--chart-2').trim(),
    styles.getPropertyValue('--chart-3').trim(),
    styles.getPropertyValue('--chart-4').trim(),
    styles.getPropertyValue('--chart-5').trim(),
    styles.getPropertyValue('--chart-6').trim(),
    styles.getPropertyValue('--chart-7').trim(),
    styles.getPropertyValue('--chart-8').trim(),
  ].filter(Boolean);
})();
