import { h, mount, openSocket, setCountdown, songCover, textRule, yearRule, yearsOff } from "/static/common.js";

const pin = location.pathname.split("/")[2];
const app = document.getElementById("app");
const seatKey = `kahitster:${pin}`;

function readSeat() {
  try {
    return sessionStorage.getItem(seatKey) || localStorage.getItem(seatKey);
  } catch {
    return null;
  }
}

function forgetSeat() {
  try {
    sessionStorage.removeItem(seatKey);
    localStorage.removeItem(seatKey);
  } catch {
    // Nothing stored, nothing to forget.
  }
}

const token = readSeat();
let state;
// What is on screen right now. The server re-sends state whenever anyone does
// anything; redrawing on each one would wipe a half-typed answer.
let shown = "";
let socket;

if (!token) {
  location.replace(`/join/${pin}`);
} else {
  socket = openSocket(`/ws/play/${pin}`, {
    hello: () => ({ type: "hello", token }),
    onMessage(message) {
      if (message.type === "error") {
        if (message.fatal) leave(message);
        return;
      }
      state = message;
      render();
    },
  });
}

function leave(message) {
  socket.stop();
  forgetSeat();
  if (message.code === "unknown_player") {
    location.replace(`/join/${pin}`);
    return;
  }
  mount(app, h("main", { class: "center" },
    h("p", { class: "hero" }, message.message),
    h("a", { class: "button primary", href: "/join" }, "Join another game")));
}

function render() {
  const key = `${state.phase}:${state.index}:${state.answered}`;
  if (key !== shown) {
    shown = key;
    mount(app,
      h("div", { class: "me" }, h("span", { class: "ellipsis" }, state.name), h("span", { id: "score" })),
      h("main", null, VIEWS[state.phase]()));
  }
  // The score can change without the view changing, when the host corrects a mark.
  document.getElementById("score").textContent = `${state.score} pts`;
  if (state.phase === "question") setCountdown(state.remaining);
  else if (state.phase !== "lobby") renderResult();
}

const songNumber = () => `Song ${state.index + 1} of ${state.total}`;

const VIEWS = {
  lobby: () => h("div", { class: "center stack" },
    h("p", { class: "hero" }, `You're in, ${state.name}!`),
    h("p", { class: "muted" }, "See your name on the big screen? The game starts soon."),
    h("div", { class: "notice small stack" },
      h("div", null, textRule(state.scoring)),
      state.guess_year && h("div", null, yearRule(state.scoring)))),

  question: () => (state.answered ? locked() : answerForm()),

  // Filled in by renderResult(), which also runs when a mark is corrected.
  reveal: () => h("div", { id: "result", class: "stack" }),
  leaderboard: () => h("div", { id: "result", class: "stack" }),
  finished: () => h("div", { id: "result", class: "stack" }),
};

function locked() {
  return h("div", { class: "center stack" },
    h("p", { class: "hero" }, "Locked in!"),
    h("p", { class: "muted" }, "Waiting for the others…"),
    h("div", { class: "timer", "data-countdown": "" }));
}

function answerForm() {
  const title = h("input", { type: "text", placeholder: "Song name", maxLength: 120, autocomplete: "off",
    autocapitalize: "off", enterKeyHint: "next", "aria-label": "Song name" });
  const artist = h("input", { type: "text", placeholder: "Artist", maxLength: 120, autocomplete: "off",
    autocapitalize: "off", enterKeyHint: "send", "aria-label": "Artist" });
  const year = state.guess_year && yearPicker();

  const form = h("form", { class: "stack", onsubmit: submit },
    h("div", { class: "row" },
      h("span", { class: "muted grow" }, songNumber()),
      h("span", { class: "timer", "data-countdown": "" })),
    title, artist, year && year.el,
    h("button", { class: "primary" }, "Lock in answer"));

  function submit(event) {
    event.preventDefault();
    socket.send({ type: "answer", title: title.value, artist: artist.value, year: year ? year.value() : null });
  }
  setTimeout(() => title.focus());
  return form;
}

function yearPicker() {
  const now = new Date().getFullYear();
  const range = h("input", { type: "range", min: 1950, max: now, value: 2000, "aria-label": "Year" });
  const out = h("output", null, "2000");
  const set = (value) => {
    range.value = Math.min(now, Math.max(1950, value));
    out.textContent = range.value;
  };
  range.addEventListener("input", () => set(Number(range.value)));
  const nudge = (step, label) => h("button", { type: "button", "aria-label": label, onclick: () => set(Number(range.value) + step) }, step > 0 ? "+" : "−");

  return {
    value: () => Number(range.value),
    el: h("div", { class: "stack" },
      h("div", null, "What year did it come out?", h("div", { class: "muted small" }, yearRule(state.scoring))),
      h("div", { class: "yearpick" }, nudge(-1, "One year earlier"), out, nudge(1, "One year later")),
      range),
  };
}

function renderResult() {
  const box = document.getElementById("result");
  const { song, result } = state;
  const verdict = (label, guess, ok, points) => h("div", { class: "verdict" },
    h("span", null, h("span", { class: "muted" }, `${label}: `), guess || "—"),
    h("strong", { class: ok ? "ok-text" : "no-text" }, ok ? `✓ +${points}` : "✗"));

  const finished = state.phase === "finished";
  mount(box,
    finished && h("div", { class: "center stack" },
      h("p", { class: "hero" }, state.rank === 1 ? "🏆 You won!" : `You finished #${state.rank}`),
      h("p", { class: "muted" }, `out of ${state.player_count} · ${state.score} points`),
      h("div", { class: "stack" }, state.podium.map((row, i) =>
        h("div", { class: "verdict" }, h("span", null, `${["🥇", "🥈", "🥉"][i]} ${row.name}`), h("strong", null, row.score))))),
    !finished && [
      h("div", { class: "center stack" },
        songCover(song, "cover"),
        h("div", null, h("strong", null, song.title), h("div", { class: "muted" }, song.artists.join(", ")),
          song.year && h("div", { class: "muted" }, song.year))),
      result.answered
        ? [
            verdict("Song", result.title, result.title_ok, result.title_points),
            verdict("Artist", result.artist, result.artist_ok, result.artist_points),
            state.guess_year && verdict("Year",
              result.year != null && [result.year, result.years_off != null && ` · ${yearsOff(result.years_off)}`],
              result.year_points > 0, result.year_points),
          ]
        : h("p", { class: "center muted" }, "You didn't answer this one."),
      h("div", { class: "center" }, h("div", { class: "points" }, `+${result.points}`),
        h("div", { class: "muted" }, `You're #${state.rank} of ${state.player_count}`)),
    ]);
}
