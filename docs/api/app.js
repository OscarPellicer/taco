const root = document.documentElement;
const toggle = document.querySelector(".theme-toggle");

function preferredTheme() {
  const saved = localStorage.getItem("taco-docs-theme");
  if (saved === "light" || saved === "dark") return saved;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setTheme(theme) {
  root.dataset.theme = theme;
  const next = theme === "dark" ? "light" : "dark";
  toggle.setAttribute("aria-label", `Use ${next} theme`);
  toggle.title = `Use ${next} theme`;
}

setTheme(preferredTheme());
toggle.addEventListener("click", () => {
  const next = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("taco-docs-theme", next);
  setTheme(next);
});

document.querySelectorAll(".code-bar > button").forEach((button) => {
  button.addEventListener("click", async () => {
    const code = button.closest(".code-block")?.querySelector("pre:not([hidden]) code")?.textContent;
    if (!code) return;
    await navigator.clipboard.writeText(code);
    button.textContent = "Copied";
    window.setTimeout(() => { button.textContent = "Copy"; }, 1200);
  });
});

document.querySelectorAll(".language-code").forEach((block) => {
  const tabs = block.querySelectorAll("[data-language]");
  const panels = block.querySelectorAll("[data-code]");
  tabs.forEach((tab) => tab.addEventListener("click", () => {
    tabs.forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
    panels.forEach((panel) => { panel.hidden = panel.dataset.code !== tab.dataset.language; });
  }));
});
