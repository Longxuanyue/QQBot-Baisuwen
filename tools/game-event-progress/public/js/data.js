import { DATA_BASES, gamesMeta, remoteConfigUrl, state, importConfig, allGames } from "./state.js";

let bust = () => "t=" + Date.now();

export function setCacheTag(tag) {
  state.cacheTag = tag || "";
  if (tag) bust = () => "v=" + encodeURIComponent(tag);
}

export async function fetchFirstOk(paths) {
  for (const p of paths) {
    try {
      const url = p + (p.includes("?") ? "&" : "?") + bust();
      const res = await fetch(url);
      if (res.ok) return { res, path: p };
    } catch {
      /* try next */
    }
  }
  return null;
}

export async function loadGamesMeta() {
  const hit = await fetchFirstOk(DATA_BASES.map((b) => b + "games-meta.json"));
  if (!hit) return;
  try {
    const data = await hit.res.json();
    gamesMeta.byId = data.games || {};
  } catch {
    /* ignore */
  }
}

export async function loadStatus() {
  const hit = await fetchFirstOk(DATA_BASES.map((b) => b + "status.json"));
  if (!hit) return;
  try {
    state.status = await hit.res.json();
    if (state.status?.updatedAt) setCacheTag(String(state.status.updatedAt).slice(0, 19));
  } catch {
    state.status = null;
  }
}

export async function loadRemoteConfig() {
  const url = remoteConfigUrl();
  if (!url) return;
  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const cfg = await res.json();
    importConfig(cfg);
  } catch (e) {
    console.warn("远程配置失败", e);
  }
}

export async function loadGame(game) {
  if (state.loadState[game.id] === "loading" || state.loadState[game.id] === "ready") {
    return state.byGame[game.id];
  }
  state.loadState[game.id] = "loading";

  if (game.custom) {
    state.byGame[game.id] = { events: game.events || [], pending: false };
    state.loadState[game.id] = "ready";
    return state.byGame[game.id];
  }
  if (!game.dataUrl) {
    state.byGame[game.id] = { events: [], pending: true };
    state.loadState[game.id] = "ready";
    return state.byGame[game.id];
  }
  const file = game.dataUrl.split("/").pop();
  const hit = await fetchFirstOk(DATA_BASES.map((b) => b + file));
  if (!hit) {
    state.byGame[game.id] = { events: [], pending: true };
    state.loadState[game.id] = "error";
    return state.byGame[game.id];
  }
  try {
    state.byGame[game.id] = await hit.res.json();
    state.loadState[game.id] = "ready";
  } catch {
    state.byGame[game.id] = { events: [], pending: true };
    state.loadState[game.id] = "error";
  }
  return state.byGame[game.id];
}

/** 确保指定游戏已加载（展开/深链用） */
export async function ensureGameLoaded(gameId) {
  const game = allGames().find((g) => g.id === gameId);
  if (!game) return null;
  return loadGame(game);
}
