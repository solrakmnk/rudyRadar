const formatMetric = (metric, value) => {
  if (metric === "distance") return `${value.toFixed(1)} km`;
  if (metric === "activities") return `${Math.round(value)} sesiones`;
  const minutes = Math.round(value);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m` : `${minutes}m`;
};

const renderComparison = (chart, metric) => {
  const current = Number(chart.dataset[`current${metric[0].toUpperCase()}${metric.slice(1)}`] || 0);
  const previous = Number(chart.dataset[`previous${metric[0].toUpperCase()}${metric.slice(1)}`] || 0);
  const maximum = Math.max(current, previous, 1);
  chart.querySelector('[data-bar="current"]').style.width = `${Math.max(current / maximum * 100, current ? 5 : 0)}%`;
  chart.querySelector('[data-bar="previous"]').style.width = `${Math.max(previous / maximum * 100, previous ? 5 : 0)}%`;
  chart.querySelector('[data-value="current"]').textContent = formatMetric(metric, current);
  chart.querySelector('[data-value="previous"]').textContent = formatMetric(metric, previous);
  const insight = chart.parentElement.querySelector("[data-chart-insight]");
  if (!previous && current) insight.textContent = "Nuevo punto de partida. Ya tienes una marca para superar.";
  else if (!previous && !current) insight.textContent = "Tu próxima sesión abre esta comparación.";
  else {
    const change = Math.round((current - previous) / previous * 100);
    insight.textContent = change > 0 ? `Vas ${change}% arriba del periodo anterior.` : change < 0 ? `Estás ${Math.abs(change)}% abajo. Todavía hay tiempo para responder.` : "Vas exactamente al ritmo del periodo anterior.";
  }
};

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-sport-tab]").forEach((tab) => tab.addEventListener("click", () => {
    const sport = tab.dataset.sportTab;
    document.querySelectorAll("[data-sport-tab]").forEach((item) => {
      const selected = item === tab;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-selected", String(selected));
    });
    document.querySelectorAll("[data-sport-panel]").forEach((panel) => panel.hidden = panel.dataset.sportPanel !== sport);
    document.querySelectorAll("[data-period-link]").forEach((link) => {
      const url = new URL(link.href);
      url.searchParams.set("sport", sport);
      link.href = url.pathname + url.search;
    });
    const currentUrl = new URL(window.location.href);
    currentUrl.searchParams.set("sport", sport);
    window.history.replaceState({}, "", currentUrl.pathname + currentUrl.search);
  }));

  document.querySelectorAll("[data-comparison-chart]").forEach((chart) => renderComparison(chart, chart.dataset.defaultMetric));

  document.querySelectorAll("[data-metric-switch]").forEach((group) => group.querySelectorAll("[data-metric]").forEach((button) => button.addEventListener("click", () => {
    group.querySelectorAll("[data-metric]").forEach((item) => item.classList.toggle("active", item === button));
    renderComparison(group.closest(".progress-card").querySelector("[data-comparison-chart]"), button.dataset.metric);
  })));

  document.querySelectorAll("[data-board-switch]").forEach((group) => group.querySelectorAll("[data-board-metric]").forEach((button) => button.addEventListener("click", () => {
    group.querySelectorAll("[data-board-metric]").forEach((item) => item.classList.toggle("active", item === button));
    const card = group.closest(".competition-card");
    card.querySelectorAll("[data-board-list]").forEach((list) => list.hidden = list.dataset.boardList !== button.dataset.boardMetric);
    card.querySelectorAll("[data-board-more]").forEach((more) => more.hidden = more.dataset.boardMore !== button.dataset.boardMetric);
  })));

  document.querySelectorAll("[data-board-more]").forEach((button) => button.addEventListener("click", () => {
    const list = button.closest(".competition-card").querySelector(`[data-board-list="${button.dataset.boardMore}"]`);
    const expanded = button.getAttribute("aria-expanded") === "true";
    list.querySelectorAll("[data-board-extra]").forEach((row) => row.hidden = expanded);
    button.setAttribute("aria-expanded", String(!expanded));
    button.textContent = expanded ? `Ver todos (${button.dataset.total})` : "Ver menos";
  }));
});
