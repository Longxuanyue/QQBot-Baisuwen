import { escapeHtml, fmtDate, fmtRelative, endingSoon } from "./util.js";
import { CAT_ORDER, state } from "./state.js";

export function shortName(ev) {
  const title = (ev.title || "").replace(/^预告·/, "").trim();
  if (title && title.length <= 28) return title;
  const raw = (ev.header || title || "").replace(/^预告·/, "");
  const m = raw.match(/[「【\[]([^」】\]]+)[」】\]]/);
  if (m) return m[1];
  const head = raw.split(/[·・]/)[0].trim();
  if (head && head.length <= 28) return head;
  return raw
    .replace(/活动即将开启|限时活动|故事集|即将开启|后续|预告·|预计.+开启|祈愿|跃迁|调频|唤取/g, "")
    .replace(/[【】\[\]\s]+/g, " ")
    .trim()
    .slice(0, 28);
}

export function eventCategory(ev) {
  const t = `${ev.title || ""} ${ev.header || ""} ${ev.summary || ""} ${ev.primaryLabel || ""}`;
  if (ev.webUrl || /网页活动|H5|新网页活动|浏览器|专题页|外链活动|官网活动|web\s*event/i.test(t)) {
    return "web";
  }
  if (CAT_ORDER.includes(ev.category)) return ev.category;
  if (ev.category === "other") return "event";
  if (/寻访|卡池|祈愿|跃迁|调频|招募|UP|特选|唤取|建造|共鸣/.test(t)) return "gacha";
  if (/签到|登录|维护|兑换|商店|特卖|申领|创作|征集|时装|涂装|皮肤|邮件|优化|修复|拍照|委托|回礼|直播/.test(t)) {
    return "event";
  }
  return "combat";
}

export function catLabel(cat) {
  return { combat: "作战", gacha: "卡池", web: "网页", event: "活动" }[cat] || "活动";
}

export function jumpUrl(ev) {
  const u = (ev.webUrl || ev.link || "").trim();
  if (!u) return "";
  if (/^uniwebview:/i.test(u)) return "";
  if (/^https?:\/\//i.test(u) || u.startsWith("//")) return u.startsWith("//") ? `https:${u}` : u;
  return "";
}

export function isWebEvent(ev) {
  return eventCategory(ev) === "web" || Boolean(ev.webUrl);
}

export function liveStats(ev) {
  const start = ev.start ? new Date(ev.start) : null;
  const end = ev.end ? new Date(ev.end) : null;
  const now = new Date();
  if (!start || !end || !(end > start)) {
    return { status: "未知", kind: "live", remain: "?", pct: 0, tip: "" };
  }
  const totalMs = end - start;
  const totalDays = totalMs / 86400000;

  if (now < start) {
    return {
      status: "即将开始",
      kind: "preview",
      remain: fmtRelative(start - now),
      pct: 0,
      tip: ev.fuzzy
        ? `预告（估时）· 约 ${fmtDate(ev.start)} 前后`
        : `还未开始 · ${fmtDate(ev.start)} 开启`,
    };
  }
  if (now >= end) {
    return { status: "已结束", kind: "done", remain: "已结束", pct: 100, tip: "已结束" };
  }
  const elapsedMs = now - start;
  const remainMs = end - now;
  const pct = Math.max(0, Math.min(100, (elapsedMs / totalMs) * 100));
  const elapsedDays = elapsedMs / 86400000;
  return {
    status: "进行中",
    kind: "live",
    remain: fmtRelative(remainMs),
    pct,
    tip: `已过 ${elapsedDays.toFixed(1)} 天 / 共 ${totalDays.toFixed(1)} 天`,
  };
}

export function splitEvents(events) {
  const live = [];
  const preview = [];
  for (const e of events || []) {
    if (!e.hasSchedule) continue;
    const cat = eventCategory(e);
    if (!state.cats[cat]) continue;
    const s = liveStats(e);
    if (s.status === "进行中") live.push(e);
    else if (s.status === "即将开始") preview.push(e);
  }
  live.sort((a, b) => new Date(a.end) - new Date(b.end));
  preview.sort((a, b) => new Date(a.start) - new Date(b.start));
  return { live, preview };
}

function normKey(s) {
  return String(s || "")
    .replace(/[\s「」『』【】\[\]（）()·・\-—_/|/\\.,，。！!？?：:；;“”‘’"']+/g, "")
    .toLowerCase();
}

export function highlightOrigin(text) {
  const esc = escapeHtml(String(text || ""));
  return esc
    .replace(
      /(20\d{2}[\/-]\d{1,2}[\/-]\d{1,2}\s*\d{1,2}[:：]\d{2})/g,
      '<mark class="hl-time">$1</mark>'
    )
    .replace(/(\d{1,2}月\d{1,2}日\s*\d{1,2}[:：]\d{2})/g, '<mark class="hl-time">$1</mark>')
    .replace(/【([^】]{1,40})】/g, '<mark class="hl-item">【$1】</mark>')
    .replace(/「([^」]{1,30})」/g, '<mark class="hl-name">「$1」</mark>')
    .replace(
      /(活动时间|开放时间|活动开放时间|寻访说明|申领说明|活动说明|更新维护时间|补偿)[：:]/g,
      '<mark class="hl-key">$1</mark>：'
    );
}

export function bodyText(ev) {
  const aliases = [ev.title, ev.header, shortName(ev), ev.primaryLabel]
    .map(normKey)
    .filter((a) => a.length >= 2);
  for (const raw of [ev.body, ev.text, ev.textPreview, ev.summary]) {
    if (!raw) continue;
    const trimmed = String(raw).trim();
    if (!trimmed) continue;
    const oneLine = trimmed.replace(/\s+/g, " ");
    const key = normKey(oneLine);
    if (!key) continue;
    if (
      aliases.some(
        (a) =>
          key === a ||
          (a.length >= 4 && key.length <= a.length + 8 && (key.includes(a) || a.includes(key)))
      )
    ) {
      continue;
    }
    if (oneLine.length < 28 && !/活动时间|开放时间|说明|奖励|参加|关卡/.test(oneLine)) continue;
    return trimmed;
  }
  return "";
}

export { endingSoon, fmtDate };
