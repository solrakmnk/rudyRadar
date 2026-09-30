document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-sport-tab]").forEach((tab) => tab.addEventListener("click", () => {
    const sport = tab.dataset.sportTab;
    document.querySelectorAll("[data-sport-tab]").forEach((item) => item.classList.toggle("active", item === tab));
    document.querySelectorAll("[data-sport-panel]").forEach((panel) => panel.hidden = panel.dataset.sportPanel !== sport);
  }));
});
