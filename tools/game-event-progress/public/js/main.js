import { $ } from "./util.js";
import {
  CAT_ORDER,
  DEFAULT_ENABLED,
  allGames,
  exportConfig,
  importConfig,
  loadCustomGames,
  persist,
  saveCustomGames,
  state,
} from "./state.js";
import { loadGamesMeta, loadRemoteConfig, loadStatus } from "./data.js";
import {
  applyFilterUI,
  expandAndLoad,
  moveEnabled,
  observeGameRows,
  render,
  renderPicker,
  renderSkeleton,
  visibleGames,
} from "./render.js";
import { closeDetail, openDetail, tryOpenFromHash } from "./detail.js";

async function boot() {
  $("#meta").textContent = "加载中…";
  document.body.classList.add("is-loading");
  renderSkeleton();
  await loadRemoteConfig();
  await Promise.all([loadGamesMeta(), loadStatus()]);
  document.body.classList.remove("is-loading");
  applyFilterUI();
  renderPicker();
  render();
}

$("#games").addEventListener("click", (e) => {
  if (e.target.closest("[data-tool], [data-tools] a, [data-jump]")) return;
  const card = e.target.closest("[data-event-id]");
  if (card) {
    openDetail(card.dataset.gameId, card.dataset.eventId);
    return;
  }
  const btn = e.target.closest("[data-toggle]");
  if (!btn) return;
  const id = btn.dataset.toggle;
  const willOpen = Boolean(state.collapsed[id]);
  if (willOpen) {
    expandAndLoad(id);
  } else {
    state.collapsed[id] = true;
    persist();
    const row = btn.closest(".game-row");
    row?.classList.add("collapsed");
    btn.setAttribute("aria-expanded", "false");
  }
});

$("#games").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const card = e.target.closest("[data-event-id]");
  if (!card) return;
  e.preventDefault();
  openDetail(card.dataset.gameId, card.dataset.eventId);
});

$("#detail").addEventListener("click", (e) => {
  if (e.target.closest("[data-close-detail]")) closeDetail();
  const copyBtn = e.target.closest("[data-copy-link]");
  if (copyBtn) {
    const url = location.href.split("#")[0] + location.hash;
    const done = () => {
      const prev = copyBtn.textContent;
      copyBtn.textContent = "已复制";
      setTimeout(() => {
        copyBtn.textContent = prev;
      }, 1200);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(() => prompt("复制链接", url));
    } else {
      prompt("复制链接", url);
    }
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#detail").classList.contains("hidden")) closeDetail();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    const search = $("#search");
    if (!search) return;
    e.preventDefault();
    search.focus();
    search.select();
  }
  if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable) return;
    const search = $("#search");
    if (!search) return;
    e.preventDefault();
    search.focus();
    search.select();
  }
});

window.addEventListener("hashchange", () => {
  if (location.hash.startsWith("#/event/")) tryOpenFromHash();
  else if (!$("#detail").classList.contains("hidden")) {
    $("#detail").classList.add("hidden");
    $("#detail").setAttribute("aria-hidden", "true");
  }
});

$("#filters").addEventListener("change", (e) => {
  if (e.target.id === "hideEmpty") {
    state.hideEmpty = e.target.checked;
    persist();
    render();
    return;
  }
  const input = e.target.closest("[data-cat]");
  if (!input) return;
  state.cats[input.dataset.cat] = input.checked;
  if (!CAT_ORDER.some((k) => state.cats[k])) {
    state.cats.combat = true;
    applyFilterUI();
  }
  persist();
  render();
});

$("#btnGames").addEventListener("click", () => {
  $("#gamePicker").classList.toggle("hidden");
  if (!$("#gamePicker").classList.contains("hidden")) renderPicker();
});

$("#gamePicker").addEventListener("change", (e) => {
  const file = e.target.closest("[data-import-cfg]");
  if (file?.files?.[0]) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        importConfig(JSON.parse(String(reader.result || "{}")));
        renderPicker();
        render();
      } catch (err) {
        alert("导入失败：" + (err.message || err));
      }
    };
    reader.readAsText(file.files[0]);
    file.value = "";
    return;
  }
  const input = e.target.closest("input[data-game]");
  if (!input) return;
  const id = input.dataset.game;
  if (input.checked) {
    if (!state.enabled.includes(id)) state.enabled.push(id);
  } else {
    state.enabled = state.enabled.filter((x) => x !== id);
    if (state.enabled.length === 0) {
      state.enabled = [id];
      input.checked = true;
    }
  }
  persist();
  renderPicker();
  render();
});

$("#gamePicker").addEventListener("click", (e) => {
  if (e.target.closest("[data-export-cfg]")) {
    e.preventDefault();
    const blob = new Blob([JSON.stringify(exportConfig(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `game-event-config-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    return;
  }
  if (e.target.closest("[data-pick-all]")) {
    e.preventDefault();
    state.enabled = allGames().map((g) => g.id);
    persist();
    renderPicker();
    render();
    return;
  }
  if (e.target.closest("[data-pick-none]")) {
    e.preventDefault();
    const keep = state.enabled[0] || DEFAULT_ENABLED[0];
    state.enabled = [keep];
    persist();
    renderPicker();
    render();
    return;
  }
  const move = e.target.closest("[data-move]");
  if (move) {
    e.preventDefault();
    e.stopPropagation();
    moveEnabled(move.dataset.game, move.dataset.move === "up" ? -1 : 1);
    persist();
    renderPicker();
    render();
    return;
  }
  const rm = e.target.closest("[data-rm]");
  if (!rm) return;
  e.preventDefault();
  const id = rm.dataset.rm;
  saveCustomGames(loadCustomGames().filter((g) => g.id !== id));
  state.enabled = state.enabled.filter((x) => x !== id);
  persist();
  renderPicker();
  render();
});

$("#gamePicker").addEventListener("submit", (e) => {
  const addGame = e.target.closest("#customAdd");
  const addEv = e.target.closest("#customEventAdd");
  if (addGame) {
    e.preventDefault();
    const fd = new FormData(addGame);
    const name = String(fd.get("name") || "").trim();
    if (!name) return;
    const icon = String(fd.get("icon") || "").trim();
    const id = "custom-" + Date.now().toString(36);
    const list = loadCustomGames();
    list.push({
      id,
      name,
      en: "CUSTOM",
      icon: icon || "./icons/custom.svg",
      events: [],
    });
    saveCustomGames(list);
    if (!state.enabled.includes(id)) state.enabled.push(id);
    persist();
    addGame.reset();
    renderPicker();
    render();
    return;
  }
  if (addEv) {
    e.preventDefault();
    const fd = new FormData(addEv);
    const gameId = String(fd.get("gameId") || "");
    const title = String(fd.get("title") || "").trim();
    const start = String(fd.get("start") || "");
    const end = String(fd.get("end") || "");
    if (!gameId || !title || !start || !end) return;
    const startIso = new Date(start).toISOString();
    const endIso = new Date(end).toISOString();
    if (!(new Date(endIso) > new Date(startIso))) {
      alert("结束时间需晚于开始时间");
      return;
    }
    const list = loadCustomGames();
    const g = list.find((x) => x.id === gameId);
    if (!g) return;
    g.events = g.events || [];
    g.events.push({
      id: `${gameId}-${Date.now()}`,
      title,
      header: title,
      banner: "",
      start: startIso,
      end: endIso,
      hasSchedule: true,
      category: "combat",
      fuzzy: false,
    });
    saveCustomGames(list);
    state.loadState[gameId] = "idle";
    addEv.reset();
    renderPicker();
    expandAndLoad(gameId);
  }
});

$("#btnRefresh").addEventListener("click", () => {
  for (const id of Object.keys(state.loadState)) {
    delete state.loadState[id];
    delete state.byGame[id];
  }
  boot().catch((err) => {
    $("#meta").textContent = String(err.message || err);
  });
});

const searchInput = $("#search");
if (searchInput) {
  let searchTimer = 0;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = searchInput.value || "";
      render();
    }, 120);
  });
}

$("#btnFoldAll")?.addEventListener("click", () => {
  for (const g of visibleGames()) state.collapsed[g.id] = true;
  persist();
  render();
});
$("#btnExpandAll")?.addEventListener("click", () => {
  for (const g of visibleGames()) state.collapsed[g.id] = false;
  persist();
  render();
  observeGameRows();
});

const toTop = $("#toTop");
const topSticky = document.querySelector(".top-sticky");
window.addEventListener(
  "scroll",
  () => {
    const y = window.scrollY || 0;
    if (toTop) toTop.classList.toggle("hidden", y < 420);
    if (topSticky) topSticky.classList.toggle("is-scrolled", y > 8);
  },
  { passive: true }
);
toTop?.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}

boot().catch((err) => {
  $("#meta").textContent = String(err.message || err);
});