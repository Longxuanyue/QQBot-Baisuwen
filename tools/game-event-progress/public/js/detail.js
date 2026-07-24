import { $ } from "./util.js";
import { eventIndex, state, toolsFor, wikiFor, allGames } from "./state.js";
import {
  bodyText,
  catLabel,
  eventCategory,
  fmtDate,
  highlightOrigin,
  isWebEvent,
  jumpUrl,
  liveStats,
  shortName,
} from "./format.js";
import { ensureGameLoaded } from "./data.js";

function accentColor(gameId) {
  const row = document.querySelector(`.game-row[data-game="${gameId}"]`);
  if (row) {
    const v = getComputedStyle(row).getPropertyValue("--g-accent").trim();
    if (v) return v;
  }
  return "#f0c41a";
}

function timelineHtml(ranges) {
  if (!ranges?.length) return "";
  const now = Date.now();
  const items = ranges
    .map((r) => {
      const s = r.start ? new Date(r.start).getTime() : NaN;
      const e = r.end ? new Date(r.end).getTime() : NaN;
      if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return null;
      return { ...r, s, e };
    })
    .filter(Boolean);
  if (!items.length) return "";
  const min = Math.min(...items.map((x) => x.s));
  const max = Math.max(...items.map((x) => x.e));
  const span = Math.max(max - min, 1);
  const nowPct = Math.max(0, Math.min(100, ((now - min) / span) * 100));

  const bars = items
    .slice(0, 10)
    .map((r) => {
      const left = ((r.s - min) / span) * 100;
      const width = Math.max(2, ((r.e - r.s) / span) * 100);
      const rc = r.category || "event";
      const live = r.s <= now && now <= r.e;
      return `<div class="tl-bar cat-${rc} ${live ? "is-live" : ""}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${r.label || ""} ${fmtDate(r.start)} → ${fmtDate(r.end)}"></div>`;
    })
    .join("");

  return `
    <div class="detail-block">
      <h3>时间轴</h3>
      <div class="timeline" aria-hidden="true">
        <div class="tl-track">${bars}<i class="tl-now" style="left:${nowPct.toFixed(2)}%"></i></div>
        <div class="tl-scale"><span>${fmtDate(new Date(min).toISOString())}</span><span>${fmtDate(new Date(max).toISOString())}</span></div>
      </div>
    </div>`;
}

export function openDetail(gameId, eventId) {
  const hit = eventIndex.get(String(eventId));
  if (!hit) return;
  const { game, ev } = hit;
  const live = liveStats(ev);
  const cat = eventCategory(ev);
  const stateText =
    live.status === "即将开始" ? "预告" : live.status === "进行中" ? "进行中" : live.status;
  const kindClass = stateText === "预告" ? "preview" : stateText === "进行中" ? "live" : "done";
  const name = shortName(ev);
  const panel = $("#detail");
  panel.style.setProperty("--detail-accent", accentColor(gameId || game.id));
  $("#detailGame").textContent = `${game.name} · ${game.en}`;
  $("#detailTitle").textContent = name;
  $("#detailTags").innerHTML = `
    <span class="${kindClass}">${stateText}</span>
    <span>${catLabel(cat)}</span>
    ${ev.fuzzy ? "<span>估时</span>" : ""}`;
  $("#detailBanner").innerHTML = ev.banner
    ? `<img src="${ev.banner}" alt="${name}" />`
    : `<div class="cover-fallback" style="height:100%"></div>`;

  const rangeItems = (ev.allRanges || []).slice(0, 12);
  const ranges = rangeItems
    .map((r) => {
      const rc = r.category || "";
      const tag = rc ? `<span class="range-cat cat-${rc}">${catLabel(rc)}</span>` : "";
      return `<li>${tag}<b>${r.label || "时段"}</b> <span class="range-when">${fmtDate(r.start)} → ${fmtDate(r.end)}</span></li>`;
    })
    .join("");
  const days = ev.days || {};
  const body = bodyText(ev);
  const bodyHtml = body
    ? `<div class="detail-block"><h3>公告</h3><div class="origin-text">${highlightOrigin(body).replace(/\n/g, "<br>")}</div></div>`
    : "";
  $("#detailBody").innerHTML = `
    <div class="detail-meta">
      <div><b>开始</b><span>${fmtDate(ev.start)}</span></div>
      <div><b>结束</b><span>${fmtDate(ev.end)}</span></div>
      <div><b>剩余</b><span>${live.remain}</span></div>
      <div><b>进度</b><span>${live.pct.toFixed(1)}%</span></div>
    </div>
    <div class="detail-progress" title="${live.tip || ""}"><i style="width:${live.pct.toFixed(1)}%"></i></div>
    ${
      days.totalDays != null
        ? `<p class="detail-days">已过 ${days.elapsedDays ?? "?"} / 共 ${days.totalDays} 天 · 剩 ${days.remainDays ?? "?"} 天</p>`
        : ""
    }
    ${timelineHtml(rangeItems)}
    ${ranges ? `<div class="detail-block"><h3>相关时段</h3><ul class="range-list">${ranges}</ul></div>` : ""}
    ${bodyHtml}`;

  const jump = jumpUrl(ev);
  const wiki = wikiFor(game);
  const tools = toolsFor(game);
  const primaryLabel = isWebEvent(ev) ? "打开网页活动" : "打开链接";
  const wikiBtn = wiki?.url
    ? `<a class="ghost" href="${wiki.url}" target="_blank" rel="noopener">Wiki</a>`
    : "";
  const toolBtns = tools
    .map(
      (t) =>
        `<a class="ghost" href="${t.url}" target="_blank" rel="noopener" title="${t.desc || ""}">${t.name}</a>`
    )
    .join("");
  $("#detailFoot").innerHTML = `
    ${jump ? `<a class="primary" href="${jump}" target="_blank" rel="noopener">${primaryLabel}</a>` : ""}
    ${wikiBtn}
    ${toolBtns}
    <button type="button" class="ghost" data-copy-link>复制链接</button>
    <button type="button" class="ghost" data-close-detail>返回</button>`;

  if (wiki?.url || tools.length) {
    const block = document.createElement("div");
    block.className = "detail-block";
    const wikiHtml = wiki?.url
      ? `<a class="tool-link wiki" href="${wiki.url}" target="_blank" rel="noopener">${wiki.name || "Wiki"}<small>资料站</small></a>`
      : "";
    const toolsHtmlInner = tools
      .map(
        (t) =>
          `<a class="tool-link" href="${t.url}" target="_blank" rel="noopener" title="${t.desc || t.name}">${t.name}<small>${t.desc || ""}</small></a>`
      )
      .join("");
    block.innerHTML = `<h3>相关链接</h3><div class="tool-row">${wikiHtml}${toolsHtmlInner}</div>`;
    $("#detailBody").appendChild(block);
  }

  panel.classList.remove("hidden");
  panel.setAttribute("aria-hidden", "false");
  const hash = `#/event/${encodeURIComponent(game.id)}/${encodeURIComponent(eventId)}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

export function closeDetail() {
  const panel = $("#detail");
  panel.classList.add("hidden");
  panel.setAttribute("aria-hidden", "true");
  if (location.hash.startsWith("#/event/")) {
    history.replaceState(null, "", location.pathname + location.search);
  }
}

export async function tryOpenFromHash() {
  const m = location.hash.match(/^#\/event\/([^/]+)\/(.+)$/);
  if (!m) return;
  const gameId = decodeURIComponent(m[1]);
  const eventId = decodeURIComponent(m[2]);
  if (!eventIndex.has(eventId)) {
    await ensureGameLoaded(gameId);
    // 加载后需重新建 index：由调用方 render/patch
    const game = allGames().find((g) => g.id === gameId);
    const events = state.byGame[gameId]?.events || [];
    if (game) {
      for (const ev of events) {
        const eid = String(ev.id || `${game.id}-${shortName(ev)}`);
        eventIndex.set(eid, { game, ev });
      }
    }
  }
  if (eventIndex.has(eventId)) openDetail(gameId, eventId);
}
