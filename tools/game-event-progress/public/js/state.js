export const DATA_BASES = ["./data/", "../data/"];

export function dataUrl(file) {
  return DATA_BASES[0] + file;
}

export const BUILTIN_GAMES = [
  { id: "arknights", name: "明日方舟", en: "ARKNIGHTS", icon: "./icons/arknights.png", dataUrl: dataUrl("events.json"), accent: "ark" },
  { id: "endfield", name: "终末地", en: "ENDFIELD", icon: "./icons/endfield.png", dataUrl: dataUrl("endfield.json"), accent: "ef" },
  { id: "bluearchive", name: "蔚蓝档案", en: "BLUE ARCHIVE", icon: "./icons/bluearchive.png", dataUrl: dataUrl("bluearchive.json"), accent: "ba" },
  { id: "genshin", name: "原神", en: "GENSHIN", icon: "./icons/genshin.png", dataUrl: dataUrl("genshin.json"), accent: "gi" },
  { id: "starrail", name: "崩坏：星穹铁道", en: "STAR RAIL", icon: "./icons/starrail.png", dataUrl: dataUrl("starrail.json"), accent: "sr" },
  { id: "zzz", name: "绝区零", en: "ZZZ", icon: "./icons/zzz.png", dataUrl: dataUrl("zzz.json"), accent: "zz" },
  { id: "wuwa", name: "鸣潮", en: "WUTHERING WAVES", icon: "./icons/wuwa.png", dataUrl: dataUrl("wuwa.json"), accent: "ww" },
  { id: "azurlane", name: "碧蓝航线", en: "AZUR LANE", icon: "./icons/azurlane.png", dataUrl: dataUrl("azurlane.json"), accent: "al" },
  { id: "nikke", name: "胜利女神：NIKKE", en: "NIKKE", icon: "./icons/nikke.png", dataUrl: dataUrl("nikke.json"), accent: "nikke" },
  { id: "reverse1999", name: "重返未来：1999", en: "REVERSE 1999", icon: "./icons/reverse1999.png", dataUrl: dataUrl("reverse1999.json"), accent: "r1999" },
  { id: "ptn", name: "无期迷途", en: "PATH TO NOWHERE", icon: "./icons/ptn.png", dataUrl: dataUrl("ptn.json"), accent: "ptn" },
  { id: "snowbreak", name: "尘白禁区", en: "SNOWBREAK", icon: "./icons/snowbreak.png", dataUrl: dataUrl("snowbreak.json"), accent: "snow" },
  { id: "gfl2", name: "少女前线2：追放", en: "GFL2", icon: "./icons/gfl2.png", dataUrl: dataUrl("gfl2.json"), accent: "gfl2" },
  { id: "hearthstone", name: "炉石传说", en: "HEARTHSTONE", icon: "./icons/hearthstone.png", dataUrl: dataUrl("hearthstone.json"), accent: "hs" },
  { id: "pvz2", name: "植物大战僵尸2", en: "PVZ2 CN", icon: "./icons/pvz2.png", dataUrl: dataUrl("pvz2.json"), accent: "pvz" },
  { id: "naraka", name: "永劫无间", en: "NARAKA", icon: "./icons/naraka.png", dataUrl: dataUrl("naraka.json"), accent: "naraka" },
  { id: "delta", name: "三角洲行动", en: "DELTA FORCE", icon: "./icons/delta.png", dataUrl: dataUrl("delta.json"), accent: "delta" },
];

export const DEFAULT_ENABLED = BUILTIN_GAMES.map((g) => g.id);
export const CAT_ORDER = ["combat", "gacha", "web", "event"];
export const DEFAULT_CATS = { combat: true, gacha: true, web: true, event: true };

export const eventIndex = new Map();
export const gamesMeta = { byId: {} };

/** 远程自定义配置 URL（?config=） */
export function remoteConfigUrl() {
  return new URLSearchParams(location.search).get("config") || "";
}

export function loadCustomGames() {
  try {
    return JSON.parse(localStorage.getItem("dock.custom") || "[]") || [];
  } catch {
    return [];
  }
}

export function saveCustomGames(list) {
  localStorage.setItem("dock.custom", JSON.stringify(list));
}

function migrateCats(raw) {
  const cats = { ...DEFAULT_CATS, ...(raw || {}) };
  if (raw && raw.other != null && raw.event == null) cats.event = Boolean(raw.other);
  delete cats.other;
  for (const k of CAT_ORDER) {
    if (cats[k] == null) cats[k] = DEFAULT_CATS[k];
  }
  const ver = Number(localStorage.getItem("dock.catsVer") || 0);
  if (ver < 2) cats.gacha = true;
  if (ver < 3) {
    cats.event = true;
    localStorage.setItem("dock.catsVer", "3");
  }
  return cats;
}

export const state = {
  byGame: {},
  /** gameId → 'idle' | 'loading' | 'ready' | 'error' */
  loadState: {},
  collapsed: JSON.parse(localStorage.getItem("dock.collapsed") || "{}"),
  enabled: JSON.parse(localStorage.getItem("dock.enabled") || "null") || [...DEFAULT_ENABLED],
  cats: migrateCats(JSON.parse(localStorage.getItem("dock.cats") || "null")),
  hideEmpty: localStorage.getItem("dock.hideEmpty") !== "0",
  query: "",
  status: null,
  cacheTag: "",
};

export function persist() {
  localStorage.setItem("dock.collapsed", JSON.stringify(state.collapsed));
  localStorage.setItem("dock.enabled", JSON.stringify(state.enabled));
  localStorage.setItem("dock.cats", JSON.stringify(state.cats));
  localStorage.setItem("dock.hideEmpty", state.hideEmpty ? "1" : "0");
}

export function metaFor(game) {
  return gamesMeta.byId[game.id] || {};
}

export function toolsFor(game) {
  if (game.tools?.length) return game.tools;
  return (metaFor(game).tools || []).filter((t) => t?.url && !/mirrorchyan/i.test(t.url));
}

export function wikiFor(game) {
  if (game.wiki?.url) return game.wiki;
  return metaFor(game).wiki || null;
}

export function allGames() {
  const custom = loadCustomGames().map((g) => ({
    ...g,
    accent: "custom",
    custom: true,
    en: g.en || "CUSTOM",
    icon: g.icon || "./icons/custom.svg",
    tools: g.tools || [],
    wiki: g.wiki || null,
  }));
  return [
    ...BUILTIN_GAMES.map((g) => ({
      ...g,
      tools: toolsFor(g),
      wiki: wikiFor(g),
    })),
    ...custom,
  ];
}

export function exportConfig() {
  return {
    version: 1,
    exportedAt: new Date().toISOString(),
    enabled: state.enabled,
    cats: state.cats,
    collapsed: state.collapsed,
    hideEmpty: state.hideEmpty,
    custom: loadCustomGames(),
  };
}

export function importConfig(cfg) {
  if (!cfg || typeof cfg !== "object") throw new Error("无效配置");
  if (Array.isArray(cfg.enabled) && cfg.enabled.length) state.enabled = cfg.enabled;
  if (cfg.cats) state.cats = migrateCats(cfg.cats);
  if (cfg.collapsed) state.collapsed = cfg.collapsed;
  if (typeof cfg.hideEmpty === "boolean") state.hideEmpty = cfg.hideEmpty;
  if (Array.isArray(cfg.custom)) saveCustomGames(cfg.custom);
  persist();
}
