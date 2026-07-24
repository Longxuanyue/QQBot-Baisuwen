import { $, adaptCover, endingSoon, fmtUpdated } from "./util.js";
import {
  CAT_ORDER,
  allGames,
  eventIndex,
  loadCustomGames,
  persist,
  state,
  toolsFor,
  wikiFor,
} from "./state.js";
import {
  bodyText,
  catLabel,
  eventCategory,
  fmtDate,
  isWebEvent,
  jumpUrl,
  liveStats,
  shortName,
  splitEvents,
} from "./format.js";
import { ensureGameLoaded, loadGame } from "./data.js";
import { tryOpenFromHash } from "./detail.js";

export function toolsHtml(game, { compact = false } = {}) {
  const wiki = wikiFor(game);
  const tools = toolsFor(game);
  const parts = [];
  if (wiki?.url) {
    parts.push(
      `<a class="tool-link wiki" href="${wiki.url}" target="_blank" rel="noopener" title="Wiki" data-tool>${wiki.name || "Wiki"}</a>`
    );
  }
  tools.slice(0, compact ? 2 : 5).forEach((t) => {
    parts.push(
      `<a class="tool-link" href="${t.url}" target="_blank" rel="noopener" title="${t.desc || t.name}" data-tool>${t.name}</a>`
    );
  });
  if (!parts.length) return "";
  return `<div class="tool-row ${compact ? "compact" : ""}" data-tools>${parts.join("")}</div>`;
}

function cardSubline(ev, live) {
  const label = (ev.primaryLabel || "").trim();
  if (label) return label;
  if (live.tip) return live.tip;
  const body = bodyText(ev);
  if (body) return body.replace(/\s+/g, " ").trim().slice(0, 36);
  return "";
}

export function cardHtml(game, ev) {
  const live = liveStats(ev);
  const name = shortName(ev);
  const src = ev.banner || "";
  const cat = eventCategory(ev);
  const stateText =
    live.status === "即将开始" ? "预告" : live.status === "进行中" ? "进行中" : "已结束";
  const kindClass = stateText === "预告" ? "preview" : stateText === "进行中" ? "live" : "done";
  const eid = String(ev.id || `${game.id}-${name}`);
  eventIndex.set(eid, { game, ev });
  const sub = cardSubline(ev, live);
  const jump = jumpUrl(ev);
  const web = isWebEvent(ev);
  const coverInner = src
    ? `<img class="cover-blur" src="${src}" alt="" aria-hidden="true" loading="lazy" />
       <img class="cover-img" src="${src}" alt="${name}" loading="lazy"
         onload="adaptCover(this)"
         onerror="const c=this.parentElement;const b=this.previousElementSibling;if(b)b.remove();this.remove();if(c)c.classList.add('cover-fallback');" />`
    : "";
  const jumpBtn =
    jump && web
      ? `<a class="jump-btn" href="${jump}" target="_blank" rel="noopener" data-jump title="打开网页活动">打开</a>`
      : jump
        ? `<a class="jump-btn muted" href="${jump}" target="_blank" rel="noopener" data-jump title="打开链接">链接</a>`
        : "";
  const fuzzy = ev.fuzzy ? `<span class="badge fuzzy">估时</span>` : "";
  return `
  <article class="card ${kindClass === "preview" ? "preview" : ""} ${web ? "is-web" : ""} ${endingSoon(ev) ? "is-soon" : ""}" title="${live.tip || ""} · 点击查看详情"
    data-event-id="${eid}" data-game-id="${game.id}" data-cat="${cat}" tabindex="0" role="button">
    <div class="cover ${src ? "" : "cover-fallback"}">
      ${coverInner}
      <span class="badge ${kindClass}">${stateText}</span>
      <span class="badge-cat cat-${cat}">${catLabel(cat)}</span>
      ${fuzzy}
      ${jumpBtn}
    </div>
    <div class="bar">
      <p class="bar-title">${name}${endingSoon(ev) ? `<em class="soon-tag">将截止</em>` : ""}</p>
      ${sub ? `<p class="bar-sub">${sub}</p>` : ""}
      <div class="remain ${kindClass} ${endingSoon(ev) ? "soon" : ""}">
        ${live.remain}
        <small>${endingSoon(ev) ? "将截止" : stateText}</small>
      </div>
      <div class="mid">
        <div class="dates">
          <span><em>起</em>${fmtDate(ev.start)}</span>
          <span><em>止</em>${fmtDate(ev.end)}</span>
        </div>
        <div class="track" aria-label="进度 ${live.pct.toFixed(0)}%">
          <div class="fill" style="width:${live.pct.toFixed(1)}%"></div>
        </div>
        <div class="pct-row">
          <span class="pct-num">${live.pct.toFixed(0)}%</span>
        </div>
      </div>
    </div>
  </article>`;
}

function gamesById() {
  return new Map(allGames().map((g) => [g.id, g]));
}

export function matchQueryEvents(events) {
  const q = state.query.trim().toLowerCase();
  if (!q) return events;
  return (events || []).filter((ev) => {
    const t = `${ev.title || ""} ${ev.header || ""}`.toLowerCase();
    return t.includes(q);
  });
}

function gameVisibleCount(game) {
  const payload = state.byGame[game.id];
  if (!payload && state.loadState[game.id] !== "ready") return 1; // 未加载时先显示行
  const events = matchQueryEvents(payload?.events || game.events || []);
  const { live, preview } = splitEvents(events);
  return live.length + preview.length;
}

export function visibleGames() {
  const map = gamesById();
  let list = state.enabled.map((id) => map.get(id)).filter(Boolean);
  const q = state.query.trim().toLowerCase();
  if (q) {
    list = list.filter((g) => {
      const blob = `${g.name} ${g.en} ${g.id}`.toLowerCase();
      if (blob.includes(q)) return true;
      const events = state.byGame[g.id]?.events || g.events || [];
      return events.some((ev) => `${ev.title || ""} ${ev.header || ""}`.toLowerCase().includes(q));
    });
  }
  if (state.hideEmpty) {
    list = list.filter((g) => {
      if (state.loadState[g.id] !== "ready") return true;
      return gameVisibleCount(g) > 0 || state.byGame[g.id]?.pending;
    });
  }
  return list;
}

export function gamesForPicker() {
  const all = allGames();
  const map = new Map(all.map((g) => [g.id, g]));
  const on = state.enabled.map((id) => map.get(id)).filter(Boolean);
  const off = all.filter((g) => !state.enabled.includes(g.id));
  return [...on, ...off];
}

export function moveEnabled(id, dir) {
  const i = state.enabled.indexOf(id);
  if (i < 0) return;
  const j = i + dir;
  if (j < 0 || j >= state.enabled.length) return;
  const next = [...state.enabled];
  [next[i], next[j]] = [next[j], next[i]];
  state.enabled = next;
}

export function gameRowHtml(game, payload) {
  const collapsed = Boolean(state.collapsed[game.id]);
  const load = state.loadState[game.id] || "idle";
  const events = matchQueryEvents(payload?.events || game.events || []);
  const { live, preview } = splitEvents(events);
  const total = live.length + preview.length;
  const emptyHint = payload?.pending
    ? "数据源待接入（可自定义添加活动）"
    : "当前筛选下暂无活动";

  let body;
  if (load === "idle" || load === "loading") {
    body = `<p class="game-empty game-loading">${load === "loading" ? "加载中…" : "进入视口后加载"}</p>`;
  } else if (payload?.pending && total === 0) {
    body = `<p class="game-empty">${emptyHint}</p>`;
  } else if (total === 0) {
    body = `<p class="game-empty">${emptyHint}</p>`;
  } else {
    body = `<div class="game-track">${[...live, ...preview].map((ev) => cardHtml(game, ev)).join("")}</div>`;
  }

  const countLabel = load === "ready" ? String(total) : load === "loading" ? "…" : "·";

  return `
  <section class="game-row ${collapsed ? "collapsed" : ""}" data-game="${game.id}" data-accent="${game.accent || ""}" data-load="${load}">
    <div class="game-head">
      <button type="button" class="game-bar" data-toggle="${game.id}" aria-expanded="${!collapsed}">
        <img class="game-icon" src="${game.icon}" alt="${game.name}" onerror="this.src='./icons/custom.svg'" />
        <div class="game-name">${game.name}<small>${game.en}</small></div>
        <span class="game-count ${load === "ready" && total === 0 ? "is-zero" : ""}">${countLabel}</span>
        <svg class="chev" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      ${toolsHtml(game, { compact: true })}
    </div>
    <div class="game-body">
      <div class="game-body-inner">${body}</div>
    </div>
  </section>`;
}

function bindCardHover() {
  $("#games")?.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("pointerenter", () => card.classList.add("is-hot"));
    card.addEventListener("pointerleave", () => card.classList.remove("is-hot"));
  });
}

let io = null;

export function observeGameRows() {
  if (io) io.disconnect();
  io = new IntersectionObserver(
    (entries) => {
      for (const ent of entries) {
        if (!ent.isIntersecting) continue;
        const id = ent.target.dataset.game;
        if (!id) continue;
        const game = allGames().find((g) => g.id === id);
        if (!game) continue;
        if (state.collapsed[id]) continue; // 折叠不拉
        if (state.loadState[id] === "ready" || state.loadState[id] === "loading") continue;
        loadGame(game).then(() => patchGameRow(game.id));
      }
    },
    { rootMargin: "120px 0px", threshold: 0.01 }
  );
  document.querySelectorAll("#games .game-row[data-game]").forEach((el) => io.observe(el));
}

export async function patchGameRow(gameId) {
  const game = allGames().find((g) => g.id === gameId);
  if (!game) return;
  const row = document.querySelector(`#games .game-row[data-game="${gameId}"]`);
  if (!row) {
    render();
    return;
  }
  const html = gameRowHtml(game, state.byGame[gameId]);
  const tmp = document.createElement("div");
  tmp.innerHTML = html.trim();
  const next = tmp.firstElementChild;
  row.replaceWith(next);
  next.querySelectorAll(".cover-img").forEach((img) => {
    if (img.complete && img.naturalWidth) adaptCover(img);
  });
  bindCardHover();
  if (!state.collapsed[gameId]) observeGameRows();
  updateMeta();
  tryOpenFromHash();
}

export async function expandAndLoad(gameId) {
  state.collapsed[gameId] = false;
  persist();
  await ensureGameLoaded(gameId);
  patchGameRow(gameId);
}

function updateMeta() {
  const games = visibleGames();
  let liveN = 0;
  let prevN = 0;
  let fuzzyN = 0;
  let soonN = 0;
  for (const g of games) {
    if (state.loadState[g.id] !== "ready") continue;
    const events = matchQueryEvents(state.byGame[g.id]?.events || g.events || []);
    const { live, preview } = splitEvents(events);
    liveN += live.length;
    prevN += preview.length;
    const shown = [...live, ...preview];
    fuzzyN += shown.filter((e) => e.fuzzy).length;
    soonN += shown.filter((e) => endingSoon(e)).length;
  }
  const catHint = CAT_ORDER.filter((k) => state.cats[k])
    .map((k) => catLabel(k))
    .join("+");
  const upd = fmtUpdated(state.status?.updatedAt);
  const parts = [catHint || "无筛选", `进行中 ${liveN}`, `预告 ${prevN}`];
  if (soonN) parts.push(`将截止 ${soonN}`);
  if (fuzzyN) parts.push(`估时 ${fuzzyN}`);
  if (upd) parts.push(`更新 ${upd}`);
  if (state.query.trim()) parts.unshift(`搜「${state.query.trim()}」`);
  const meta = $("#meta");
  if (meta) meta.textContent = parts.join(" · ");

  const updatedEl = $("#updatedAt");
  if (updatedEl) {
    if (!upd) {
      updatedEl.textContent = "本地预览";
      updatedEl.removeAttribute("title");
    } else if (state.status?.fetchOk === false) {
      updatedEl.textContent = `数据更新于 ${upd} · 部分源失败`;
      updatedEl.title = state.status?.updatedAt || "";
    } else {
      updatedEl.textContent = `数据更新于 ${upd}`;
      updatedEl.title = state.status?.updatedAt || "";
    }
  }

  const emptyEl = $("#empty");
  if (emptyEl) {
    const anyReady = games.some((g) => state.loadState[g.id] === "ready");
    emptyEl.textContent = state.query.trim()
      ? "没有匹配的游戏或活动"
      : games.length === 0
        ? "请先在「游戏」里勾选要显示的游戏"
        : "当前筛选下没有活动";
    const showEmpty = games.length === 0 || (anyReady && liveN + prevN === 0 && games.every((g) => state.loadState[g.id] === "ready"));
    emptyEl.classList.toggle("hidden", !showEmpty);
  }
}

export function applyFilterUI() {
  document.querySelectorAll("#filters [data-cat]").forEach((input) => {
    input.checked = Boolean(state.cats[input.dataset.cat]);
  });
  const hide = $("#hideEmpty");
  if (hide) hide.checked = Boolean(state.hideEmpty);
}

export function renderSkeleton() {
  const root = $("#games");
  if (!root) return;
  root.innerHTML = Array.from({ length: 4 }, (_, i) => `
    <section class="game-row skeleton" style="--delay:${i * 0.06}s">
      <div class="game-head"><div class="sk sk-icon"></div><div class="sk sk-line"></div></div>
      <div class="game-body"><div class="game-body-inner"><div class="game-track">
        <div class="sk sk-card"></div><div class="sk sk-card"></div><div class="sk sk-card"></div>
      </div></div></div>
    </section>`).join("");
}

export function renderPicker() {
  const root = $("#gamePicker");
  if (!root) return;
  const games = gamesForPicker();
  const en = state.enabled;
  root.innerHTML = `
    <div class="picker-bar">
      <span class="picker-hint">勾选显示 · ↑↓ 调整主列表顺序</span>
      <span class="picker-actions">
        <button type="button" class="linkish" data-pick-all>全选</button>
        <button type="button" class="linkish" data-pick-none>最少保留1个</button>
        <button type="button" class="linkish" data-export-cfg>导出配置</button>
        <label class="linkish" style="cursor:pointer">导入<input type="file" accept="application/json,.json" data-import-cfg hidden /></label>
      </span>
    </div>
    <div class="picker-grid">
      ${games
        .map((g) => {
          const on = en.includes(g.id);
          const idx = en.indexOf(g.id);
          const ord = on
            ? `<span class="pick-ord" title="显示顺序 ${idx + 1}">
                  <button type="button" class="ord-btn" data-move="up" data-game="${g.id}" ${idx === 0 ? "disabled" : ""} aria-label="上移">↑</button>
                  <button type="button" class="ord-btn" data-move="down" data-game="${g.id}" ${idx === en.length - 1 ? "disabled" : ""} aria-label="下移">↓</button>
                </span>`
            : "";
          return `
        <label class="pick-item ${on ? "is-on" : ""}">
          <input type="checkbox" data-game="${g.id}" ${on ? "checked" : ""} />
          <img src="${g.icon}" alt="" onerror="this.src='./icons/custom.svg'" />
          <span class="pick-name">${g.name}</span>
          ${ord}
          ${g.custom ? `<button type="button" class="rm" data-rm="${g.id}" title="删除自定义">删</button>` : ""}
        </label>`;
        })
        .join("")}
    </div>
    <form class="custom-add" id="customAdd">
      <input name="name" placeholder="自定义游戏名" required maxlength="20" />
      <input name="icon" placeholder="图标 URL（可空）" maxlength="300" />
      <button type="submit" class="btn">添加游戏</button>
    </form>
    <form class="custom-add event-add" id="customEventAdd">
      <select name="gameId" required>
        <option value="">选择自定义游戏…</option>
        ${loadCustomGames()
          .map((g) => `<option value="${g.id}">${g.name}</option>`)
          .join("")}
      </select>
      <input name="title" placeholder="活动名" required maxlength="40" />
      <input name="start" type="datetime-local" required title="开始" />
      <input name="end" type="datetime-local" required title="结束" />
      <button type="submit" class="btn ghost">加活动</button>
    </form>
    <p class="picker-hint" style="margin:8px 12px">远程配置：URL 加 <code>?config=你的.json</code></p>`;
}

export function render() {
  eventIndex.clear();
  const games = visibleGames();
  const root = $("#games");
  if (!root) return;
  root.innerHTML = games.map((g) => gameRowHtml(g, state.byGame[g.id])).join("");
  bindCardHover();
  root.querySelectorAll(".cover-img").forEach((img) => {
    if (img.complete && img.naturalWidth) adaptCover(img);
  });
  updateMeta();
  observeGameRows();
  // 未折叠且在首屏的会由 IO 拉取；同时主动拉前 2 个未折叠
  const eager = games.filter((g) => !state.collapsed[g.id]).slice(0, 2);
  Promise.all(eager.map((g) => loadGame(g))).then(() => {
    eager.forEach((g) => patchGameRow(g.id));
  });
  tryOpenFromHash();
}
