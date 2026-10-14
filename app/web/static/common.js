// Shared helpers. Every screen builds its DOM through h(), which only ever
// sets text and properties -- player names and typed answers are untrusted, so
// nothing here goes through innerHTML.

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key in el) el[key] = value;
    else el.setAttribute(key, value);
  }
  el.append(...kids.flat(Infinity).filter((kid) => kid != null && kid !== false));
  return el;
}

export function mount(parent, ...kids) {
  parent.replaceChildren(...kids.flat(Infinity).filter((kid) => kid != null && kid !== false));
}

export function logo() {
  return h("div", { class: "logo" }, "Ka", h("span", null, "hit"), "ster");
}

export async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  // Signed out (or the login expired) on a host screen: go sign in.
  if (res.status === 401 && location.pathname !== "/home") location.href = "/home";
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong");
  }
  return data;
}

let toastTimer;
export function toast(message) {
  let el = document.getElementById("toast");
  if (!el) document.body.append((el = h("div", { id: "toast", role: "status" })));
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 4000);
}

// A WebSocket that reconnects by itself. The server sends a full state on every
// connect, so a dropped connection needs no recovery beyond dialing again.
export function openSocket(path, { hello, onMessage }) {
  let ws;
  let stopped = false;
  const banner = h("div", { id: "offline", hidden: true }, "Reconnecting…");
  document.body.append(banner);

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}${path}`);
    ws.onopen = () => {
      banner.hidden = true;
      if (hello) ws.send(JSON.stringify(hello()));
    };
    ws.onmessage = (event) => onMessage(JSON.parse(event.data));
    ws.onclose = () => {
      if (stopped) return;
      banner.hidden = false;
      setTimeout(connect, 1500);
    };
  }
  connect();
  // Free hosting puts an idle server to sleep, which would end the game. A
  // lobby can sit silent for a while, so say something every minute.
  setInterval(() => {
    if (!stopped && ws.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}');
  }, 60_000);

  return {
    send(message) {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
    },
    stop() {
      stopped = true;
      banner.hidden = true;
      ws.close();
    },
  };
}

// One ticking clock per page. The server says how many seconds are left; we
// count down locally from the moment that message arrived.
let deadline = 0;
export function setCountdown(remainingSeconds) {
  deadline = performance.now() + remainingSeconds * 1000;
  tick();
}
function tick() {
  const left = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
  for (const el of document.querySelectorAll("[data-countdown]")) {
    el.textContent = left;
    el.classList.toggle("low", left <= 5);
  }
}
setInterval(tick, 200);

export function songCover(song, className) {
  return song.image_url
    ? h("img", { class: className, src: song.image_url, alt: "" })
    : h("div", { class: `noimg ${className || ""}` });
}

// How the year guess is scored, in words. Numbers come from the server.
export function yearRule(scoring) {
  return `Exact year: ${scoring.year} points, ${scoring.year_step} fewer for each year off`;
}

export function textRule(scoring) {
  return `Song name and artist: up to ${scoring.title} points each, more for answering fast`;
}

export function yearsOff(years) {
  if (years == null) return "";
  return years === 0 ? "exact year" : `${years} year${years === 1 ? "" : "s"} off`;
}
