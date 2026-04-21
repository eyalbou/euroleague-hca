// Minimal filter state store -- charts subscribe via callbacks.
window.FilterStore = {
  selectedTeams: null,   // null = all; otherwise Set of team_ids
  seasonRange: null,     // null = all
  phase: 'all',
  subscribers: [],
  setTeams: function (teams) { this.selectedTeams = teams; this.emit(); },
  setSeasonRange: function (lo, hi) { this.seasonRange = [lo, hi]; this.emit(); },
  setPhase: function (p) { this.phase = p; this.emit(); },
  subscribe: function (fn) { this.subscribers.push(fn); },
  emit: function () { this.subscribers.forEach(function (fn) { fn(); }); },
};
