export const $ = (sel, root = document) => root.querySelector(sel);

/** ?soonHours=48 可调「将截止」阈值 */
export function soonHours() {
  const n = Number(new URLSearchParams(location.search).get("soonHours"));
  return Number.isFinite(n) && n > 0 ? n : 48;
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function fmtDate(iso) {
  if (!iso) return "?";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "?";
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${m}/${day} ${h}:${min}`;
}

const rtf =
  typeof Intl !== "undefined" && Intl.RelativeTimeFormat
    ? new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" })
    : null;

/** 相对时间：优先 Intl，回退手写 */
export function fmtRelative(ms) {
  const sec = Math.round(ms / 1000);
  const abs = Math.abs(sec);
  if (rtf) {
    if (abs < 60) return rtf.format(Math.round(sec), "second");
    if (abs < 3600) return rtf.format(Math.round(sec / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(sec / 3600), "hour");
    if (abs < 86400 * 30) return rtf.format(Math.round(sec / 86400), "day");
    return rtf.format(Math.round(sec / (86400 * 30)), "month");
  }
  const days = Math.floor(abs / 86400);
  const hours = Math.floor((abs % 86400) / 3600);
  if (sec >= 0) {
    if (days > 0) return hours ? `${days}天${hours}时后` : `${days}天后`;
    if (hours > 0) return `${hours}小时后`;
    return "即将开始";
  }
  const left = -sec;
  const d2 = Math.floor(left / 86400);
  const h2 = Math.floor((left % 86400) / 3600);
  if (d2 > 0) return h2 ? `${d2}天${h2}时` : `${d2}天`;
  if (h2 > 0) return `${h2}小时`;
  return "将结束";
}

export function fmtUpdated(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  const abs = `${m}/${day} ${h}:${min}`;
  const delta = d.getTime() - Date.now();
  const rel = fmtRelative(delta);
  if (Math.abs(delta) < 86400000 * 2) return `${abs} · ${rel}`;
  return abs;
}

export function endingSoon(ev, hours = soonHours()) {
  if (!ev?.end) return false;
  const left = new Date(ev.end).getTime() - Date.now();
  return left > 0 && left <= hours * 3600 * 1000;
}

export function adaptCover(img) {
  const cover = img?.closest?.(".cover");
  const card = img?.closest?.(".card");
  if (!cover || !card || !img.naturalWidth) return;
  const r = img.naturalWidth / img.naturalHeight;
  let kind = "std";
  let ar = "16 / 9";
  if (r >= 2.35) {
    kind = "wide";
    ar = `${r.toFixed(3)} / 1`;
  } else if (r <= 1.15) {
    kind = "square";
    ar = "1 / 1";
  } else if (r < 1.45) {
    kind = "tall";
    ar = `${r.toFixed(3)} / 1`;
  }
  card.dataset.ratio = kind;
  cover.style.aspectRatio = ar;
}

// 内联 onload 回调
window.adaptCover = adaptCover;
