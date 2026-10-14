import { api, h, logo, mount, openSocket, setCountdown, songCover, textRule, toast, yearRule, yearsOff } from "/static/common.js";

const pin = location.pathname.split("/")[2];
const topbar = document.getElementById("topbar");
const main = document.getElementById("main");
const bottombar = document.getElementById("bottombar");

let state;

const socket = openSocket(`/ws/host/${pin}`, {
  onMessage(message) {
    if (message.type === "error") {
      if (message.fatal) {
        socket.stop();
        mount(main, h("h1", null, message.message), h("a", { class: "button primary", href: "/home" }, "Back to your quizzes"));
      } else {
        toast(message.message);
      }
      return;
    }
    state = message;
    render();
  },
});

const send = (type, extra) => socket.send({ type, ...extra });

function render() {
  document.title = `${state.quiz_name} – Kahitster`;
  renderTopbar();
  mount(main, VIEWS[state.phase]());
  if (state.phase === "question") setCountdown(state.remaining);
  renderDeviceStatus();
}

function renderTopbar() {
  const live = state.phase !== "lobby" && state.phase !== "finished";
  mount(topbar,
    logo(),
    h("strong", null, state.quiz_name),
    // Latecomers can still join, so keep the way in visible all game long.
    live && h("span", { class: "muted" }, `Join at ${shortUrl()} · PIN ${prettyPin()}`),
    h("span", { class: "right muted" }, `${state.players.length} player${state.players.length === 1 ? "" : "s"}`),
    live && h("button", { class: "ghost", onclick: () => confirm("End the game now and show the final results?") && send("end_game") }, "End game"));
}

const shortUrl = () => state.join_url.replace(/^https?:\/\//, "");
const prettyPin = () => `${state.pin.slice(0, 3)} ${state.pin.slice(3)}`;
const songNumber = () => `Song ${state.index + 1} of ${state.total}`;

// --- Views, one per phase ----------------------------------------------------

const VIEWS = {
  lobby() {
    return h("div", { class: "lobby" },
      h("div", { class: "joinbox" },
        h("div", { class: "kicker" }, "Join at"),
        h("div", { class: "joinurl" }, shortUrl()),
        h("div", { class: "kicker" }, "Game PIN"),
        h("div", { class: "pin" }, prettyPin()),
        h("img", { class: "qr", src: `/api/games/${pin}/qr.svg`, alt: "QR code to join the game" })),
      h("div", { class: "stack" },
        h("div", { class: "kicker" }, state.players.length ? "Who's in" : "Waiting for players…"),
        h("div", { class: "chips" }, state.players.map((player) =>
          h("span", { class: `chip ${player.connected ? "" : "off"}` }, player.name,
            h("button", { title: `Remove ${player.name}`, onclick: () => send("kick", { player_id: player.id }) }, "✕")))),
        h("div", { class: "muted stack" },
          h("div", null, textRule(state.scoring)),
          state.guess_year && h("div", null, yearRule(state.scoring))),
        h("div", null,
          h("button", { class: "primary big", disabled: state.players.length === 0, onclick: () => send("start") },
            `Start · ${state.total} song${state.total === 1 ? "" : "s"}`))));
  },

  question() {
    const answered = state.players.filter((player) => player.answered).length;
    return [
      h("div", { class: "kicker" }, songNumber()),
      h("div", { class: "countdown", "data-countdown": "" }),
      h("div", { class: "eq", "aria-hidden": "true" }, [1, 2, 3, 4, 5].map(() => h("i"))),
      h("div", { class: "kicker" }, `${answered} of ${state.players.length} answered`),
      state.playback_error && h("div", { class: "alert stack" },
        h("div", null, state.playback_error),
        h("div", null, h("button", { onclick: () => send("replay") }, "Try playing again"))),
      h("button", { class: "ghost", onclick: () => send("end_round") }, "End round now"),
    ];
  },

  reveal() {
    return [
      h("div", { class: "kicker" }, songNumber()),
      songCard(),
      h("div", { class: "tablewrap" }, answersTable()),
      h("button", { class: "primary big", onclick: () => send("leaderboard") }, "Leaderboard"),
    ];
  },

  leaderboard() {
    const last = state.index + 1 >= state.total;
    return [
      h("div", { class: "kicker" }, `Leaderboard after ${songNumber().toLowerCase()}`),
      board(state.leaderboard.slice(0, 8)),
      h("button", { class: "primary big", onclick: () => send("next") }, last ? "Final results" : "Next song"),
    ];
  },

  finished() {
    const [first, second, third] = state.leaderboard;
    const step = (row, cls, medal) => row && h("div", { class: cls }, `${medal} ${row.name}`, h("small", null, `${row.score} points`));
    return [
      h("div", { class: "kicker" }, "Final results"),
      h("div", { class: "podium" }, step(first, "p1", "🥇"), step(second, "p2", "🥈"), step(third, "p3", "🥉")),
      state.leaderboard.length > 3 && board(state.leaderboard.slice(3), false),
      h("a", { class: "button", href: "/home" }, "Back to your quizzes"),
    ];
  },
};

function songCard() {
  const song = state.song;
  return h("div", { class: "song" },
    songCover(song),
    h("div", null,
      h("h1", null, song.title),
      h("h2", null, song.artists.join(", ")),
      song.year && h("div", { class: "yeartag" }, song.year)));
}

function answersTable() {
  // Clicking a mark flips it: the host has the last word on spelling.
  const mark = (answer, part) => h("button", {
    class: `mark ${answer[`${part}_ok`] ? "ok" : "no"}`,
    title: "Click to change",
    "aria-label": `${answer.name}'s ${part === "title" ? "song" : "artist"} answer is marked ${answer[`${part}_ok`] ? "right" : "wrong"}. Click to change.`,
    onclick: () => send("override", { player_id: answer.id, part, ok: !answer[`${part}_ok`] }),
  }, answer[`${part}_ok`] ? "✓" : "✗");

  return h("table", null,
    h("thead", null, h("tr", null,
      h("th", null, "Player"), h("th", null, "Song"), h("th", null, "Artist"),
      state.guess_year && h("th", null, "Year"), h("th", { class: "num" }, "Points"))),
    h("tbody", null, state.answers.map((answer) => answer.answered
      ? h("tr", null,
          h("td", null, h("strong", null, answer.name)),
          h("td", null, mark(answer, "title"), answer.title || "—"),
          h("td", null, mark(answer, "artist"), answer.artist || "—"),
          state.guess_year && h("td", null, answer.year ?? "—",
            answer.years_off != null && h("span", { class: "muted" }, ` · ${yearsOff(answer.years_off)} · +${answer.year_points}`)),
          h("td", { class: "num" }, `+${answer.points}`))
      : h("tr", { class: "muted" },
          h("td", null, answer.name),
          h("td", { colSpan: state.guess_year ? 3 : 2 }, "No answer"),
          h("td", { class: "num" }, "0")))));
}

function board(rows, showGain = true) {
  return h("div", { class: "board" }, rows.map((row) =>
    h("div", { class: "line" },
      h("span", { class: "rank" }, row.rank),
      h("span", { class: "ellipsis" }, row.name),
      h("span", { class: "pts" }, row.score),
      showGain && h("span", { class: "gain" }, row.gained ? `+${row.gained}` : ""))));
}

// --- Spotify device picker (bottom bar) --------------------------------------

const deviceSelect = h("select", { "aria-label": "Spotify device", onchange: chooseDevice });
const deviceStatus = h("span", { class: "muted small grow" });
mount(bottombar,
  h("span", null, "Play music on"),
  deviceSelect,
  h("button", { class: "ghost", onclick: loadDevices }, "Refresh"),
  deviceStatus);

async function loadDevices() {
  try {
    const devices = await api("GET", "/api/spotify/devices");
    mount(deviceSelect,
      h("option", { value: "" }, devices.length ? "Whichever is active" : "No devices found"),
      devices.map((device) => h("option", { value: device.id, selected: device.id === state?.device_id },
        `${device.name}${device.is_active ? " (active)" : ""}`)));
    deviceStatus.textContent = devices.length
      ? ""
      : "Open Spotify on the speaker or phone, play anything for a second, then press Refresh.";
  } catch (error) {
    mount(deviceSelect, h("option", { value: "" }, "Not available"));
    deviceStatus.textContent = error.message;
  }
}

async function chooseDevice() {
  if (!deviceSelect.value) return;
  try {
    await api("POST", `/api/games/${pin}/device`, { device_id: deviceSelect.value });
    deviceStatus.textContent = "Device ready.";
  } catch (error) {
    deviceStatus.textContent = error.message;
  }
}

function renderDeviceStatus() {
  bottombar.hidden = state.phase === "finished";
  if (state.playback_error) deviceStatus.textContent = state.playback_error;
}

loadDevices();
