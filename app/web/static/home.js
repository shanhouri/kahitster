import { api, h, logo, mount, toast } from "/static/common.js";

const app = document.getElementById("app");

async function render() {
  const me = await api("GET", "/api/me");
  const quizzes = me.connected ? await api("GET", "/api/quizzes") : [];
  mount(app, logo(), spotifyCard(me), me.connected && quizzesCard(quizzes));
}

function spotifyCard(me) {
  if (!me.configured) {
    return h("section", { class: "card stack" },
      h("h2", null, "Spotify is not set up yet"),
      h("p", { class: "muted" },
        "The Spotify Client ID and Client secret are missing. See the README for where to put them, " +
        "then restart the server."));
  }
  if (!me.connected) {
    return h("section", { class: "card stack" },
      h("div", { class: "row" },
        h("div", { class: "grow" },
          h("h2", null, "Host a game"),
          h("p", { class: "muted" }, "Sign in with Spotify to build quizzes and play their songs. Requires Premium.")),
        h("a", { class: "button primary", href: "/auth/login" }, "Sign in with Spotify")),
      h("p", { class: "muted small" }, "Here to play? ", h("a", { href: "/join" }, "Enter a game PIN")));
  }
  return h("section", { class: "card row" },
    h("div", { class: "grow" }, "Signed in as ", h("strong", null, me.display_name)),
    h("button", { class: "ghost", onclick: signOut }, "Sign out"));
}

function quizzesCard(quizzes) {
  const name = h("input", { type: "text", placeholder: "New quiz name", maxLength: 120, class: "grow", required: true });
  const form = h("form", { class: "row", onsubmit: (event) => createQuiz(event, name.value) },
    name, h("button", { class: "primary" }, "Create quiz"));

  return h("section", { class: "card stack" },
    h("h2", null, "Your quizzes"),
    quizzes.length
      ? h("div", { class: "list" }, quizzes.map(quizRow))
      : h("p", { class: "muted" }, "No quizzes yet. Create your first one below."),
    form);
}

function quizRow(quiz) {
  return h("div", { class: "item" },
    h("div", { class: "grow" },
      h("a", { href: `/quiz/${quiz.id}` }, h("strong", null, quiz.name)),
      h("div", { class: "muted small" }, `${quiz.song_count} song${quiz.song_count === 1 ? "" : "s"}`)),
    h("button", { class: "primary", disabled: quiz.song_count === 0, onclick: () => startGame(quiz.id) }, "Play"),
    h("a", { class: "button", href: `/quiz/${quiz.id}` }, "Edit"),
    h("button", { class: "danger", onclick: () => deleteQuiz(quiz) }, "Delete"));
}

async function createQuiz(event, name) {
  event.preventDefault();
  const quiz = await api("POST", "/api/quizzes", { name });
  location.href = `/quiz/${quiz.id}`;
}

async function deleteQuiz(quiz) {
  if (!confirm(`Delete "${quiz.name}" and its song list?`)) return;
  await api("DELETE", `/api/quizzes/${quiz.id}`);
  render();
}

async function startGame(quizId) {
  const game = await api("POST", "/api/games", { quiz_id: quizId });
  location.href = `/host/${game.pin}`;
}

async function signOut() {
  await api("POST", "/auth/logout");
  render();
}

window.addEventListener("unhandledrejection", (event) => toast(event.reason.message));
render();
