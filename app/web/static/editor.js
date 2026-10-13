import { api, h, logo, mount, songCover, toast } from "/static/common.js";

const quizId = location.pathname.split("/")[2];
const app = document.getElementById("app");

let quiz;
// Song ids whose "also accept" row is open; survives list re-renders.
const openExtras = new Set();
// What the right-hand panel is showing.
const browse = { tab: "search", songs: [], nextOffset: null, more: null, playlists: null, playlist: null, note: "" };

const songsBox = h("section", { class: "card stack" });
const browseBox = h("div", { class: "stack" });
const searchInput = h("input", { type: "text", placeholder: "Song or artist", class: "grow" });
const searchForm = h("form", { class: "row", onsubmit: (event) => { event.preventDefault(); runSearch(); } },
  searchInput, h("button", { class: "primary" }, "Search"));
const tabsBox = h("div", { class: "tabs", role: "tablist" });
const headerBox = h("div", { class: "stack" });

async function init() {
  quiz = await api("GET", `/api/quizzes/${quizId}`);
  document.title = `${quiz.name} – Kahitster`;
  mount(app,
    headerBox,
    h("div", { class: "columns" },
      songsBox,
      h("section", { class: "card stack" }, h("h2", null, "Add songs from Spotify"), tabsBox, browseBox)));
  renderHeader();
  renderSongs();
  showTab("search");
}

async function reload() {
  quiz = await api("GET", `/api/quizzes/${quizId}`);
  renderHeader();
  renderSongs();
  renderBrowse();
}

// --- Header: name, settings, start ------------------------------------------

function renderHeader() {
  const save = (changes) => api("PATCH", `/api/quizzes/${quizId}`, changes).then((q) => (quiz = q));
  const option = (value, label, current) => h("option", { value, selected: String(current) === String(value) }, label);

  mount(headerBox,
    h("div", { class: "row" },
      h("a", { href: "/home", class: "plain", title: "Back to your quizzes" }, logo()),
      h("a", { href: "/home", class: "right" }, "← All quizzes")),
    h("section", { class: "card row" },
      h("label", { class: "field grow" }, "Quiz name",
        h("input", { type: "text", value: quiz.name, maxLength: 120,
          onchange: (event) => event.target.value.trim() && save({ name: event.target.value.trim() }) })),
      h("label", { class: "field" }, "Time per song",
        h("select", { onchange: (event) => save({ seconds_per_song: Number(event.target.value) }) },
          [15, 20, 30, 45, 60, 90].map((s) => option(s, `${s} seconds`, quiz.seconds_per_song)))),
      h("label", { class: "field" }, "Play each song from",
        h("select", { onchange: (event) => save({ start_mode: event.target.value }) },
          option("beginning", "The beginning", quiz.start_mode),
          option("random", "A random point", quiz.start_mode))),
      h("label", { class: "check" },
        h("input", { type: "checkbox", checked: quiz.guess_year,
          onchange: (event) => save({ guess_year: event.target.checked }) }),
        "Also guess the year"),
      h("button", { class: "primary big", disabled: quiz.songs.length === 0, onclick: startGame }, "Start game")));
}

async function startGame() {
  const game = await api("POST", "/api/games", { quiz_id: quiz.id });
  location.href = `/host/${game.pin}`;
}

// --- Left: the songs in this quiz -------------------------------------------

function renderSongs() {
  const suspects = quiz.songs.filter((song) => song.year_suspect).length;
  mount(songsBox,
    h("div", { class: "row" },
      h("h2", { class: "grow" }, `Songs in this quiz (${quiz.songs.length})`),
      h("button", { class: "ghost", disabled: quiz.songs.length < 2, onclick: shuffle }, "Shuffle order")),
    suspects > 0 && h("p", { class: "notice small" },
      `${suspects} song${suspects === 1 ? " has" : "s have"} a highlighted year: Spotify's date may be a ` +
      "re-release rather than the original. Check and correct it if you use year guessing."),
    quiz.songs.length
      ? h("div", { class: "list scroll" }, quiz.songs.map(songRow))
      : h("p", { class: "muted" }, "Empty so far. Add songs from the panel on the right."));
}

function songRow(song, index) {
  const patch = (changes) => api("PATCH", `/api/songs/${song.id}`, changes).then(reload);
  const split = (text) => text.split(";").map((part) => part.trim()).filter(Boolean);
  const open = openExtras.has(song.id);

  const row = h("div", { class: "item" },
    h("span", { class: "num" }, index + 1),
    songCover(song),
    h("div", { class: "grow" },
      h("div", { class: "ellipsis" }, h("strong", null, song.title)),
      h("div", { class: "muted small ellipsis" }, song.artists.join(", "))),
    h("input", { type: "number", class: `year ${song.year_suspect ? "warn" : ""}`, value: song.year ?? "",
      min: 1000, max: 9999, "aria-label": `Year of ${song.title}`,
      title: song.year_suspect ? "Check this year: it may be a re-release date" : "Year",
      onchange: (event) => patch({ year: event.target.value ? Number(event.target.value) : null }) }),
    h("button", { class: "icon ghost", title: "Other answers to accept", "aria-expanded": String(open),
      onclick: () => { open ? openExtras.delete(song.id) : openExtras.add(song.id); renderSongs(); } }, "⋯"),
    h("button", { class: "icon ghost", title: "Move up", disabled: index === 0, onclick: () => move(index, -1) }, "↑"),
    h("button", { class: "icon ghost", title: "Move down", disabled: index === quiz.songs.length - 1, onclick: () => move(index, 1) }, "↓"),
    h("button", { class: "icon danger", title: "Remove from quiz",
      onclick: () => api("DELETE", `/api/songs/${song.id}`).then(reload) }, "✕"));

  if (!open) return row;
  return [row, h("div", { class: "extras" },
    h("label", { class: "field" }, "Also accept these song names (separate with ;)",
      h("input", { type: "text", value: song.extra_titles.join("; "),
        onchange: (event) => patch({ extra_titles: split(event.target.value) }) })),
    h("label", { class: "field" }, "Also accept these artist names (separate with ;)",
      h("input", { type: "text", value: song.extra_artists.join("; "),
        onchange: (event) => patch({ extra_artists: split(event.target.value) }) })))];
}

async function saveOrder(ids) {
  await api("PUT", `/api/quizzes/${quizId}/order`, { song_ids: ids });
  reload();
}

function move(index, step) {
  const ids = quiz.songs.map((song) => song.id);
  [ids[index], ids[index + step]] = [ids[index + step], ids[index]];
  saveOrder(ids);
}

function shuffle() {
  const ids = quiz.songs.map((song) => song.id);
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  saveOrder(ids);
}

// --- Right: browsing Spotify -------------------------------------------------

const TABS = { search: "Search", playlists: "My playlists", liked: "Liked Songs" };

function showTab(tab) {
  Object.assign(browse, { tab, songs: [], nextOffset: null, more: null, playlist: null, note: "" });
  mount(tabsBox, Object.entries(TABS).map(([key, label]) =>
    h("button", { role: "tab", "aria-selected": String(key === tab), onclick: () => showTab(key) }, label)));
  renderBrowse();
  if (tab === "playlists") loadPlaylists();
  if (tab === "liked") loadSongs("/api/spotify/liked?", 0);
}

function runSearch() {
  const query = searchInput.value.trim();
  if (!query) return;
  browse.songs = [];
  loadSongs(`/api/spotify/search?q=${encodeURIComponent(query)}&`, 0);
}

// Fetch a page of songs into the panel; `url` ends ready for "offset=N".
async function loadSongs(url, offset) {
  browse.note = "Loading…";
  renderBrowse();
  try {
    const page = await api("GET", `${url}offset=${offset}`);
    browse.songs = offset === 0 ? page.songs : [...browse.songs, ...page.songs];
    browse.nextOffset = page.next_offset;
    browse.more = () => loadSongs(url, page.next_offset);
    browse.note = browse.songs.length ? "" : "Nothing found.";
  } catch (error) {
    browse.note = error.message;
  }
  renderBrowse();
}

async function loadPlaylists() {
  browse.note = "Loading…";
  renderBrowse();
  try {
    browse.playlists = await api("GET", "/api/spotify/playlists");
    browse.note = browse.playlists.length ? "" : "No playlists found.";
  } catch (error) {
    browse.note = error.message;
  }
  renderBrowse();
}

function openPlaylist(playlist) {
  browse.playlist = playlist;
  browse.songs = [];
  loadSongs(`/api/spotify/playlists/${playlist.id}/songs?`, 0);
}

function renderBrowse() {
  const inQuiz = new Set(quiz.songs.map((song) => song.spotify_id));
  const fresh = browse.songs.filter((song) => !inQuiz.has(song.spotify_id));
  const showingPlaylists = browse.tab === "playlists" && !browse.playlist;

  mount(browseBox,
    browse.tab === "search" && searchForm,
    browse.playlist && h("div", { class: "row" },
      h("button", { class: "link", onclick: () => showTab("playlists") }, "← Playlists"),
      h("strong", { class: "ellipsis" }, browse.playlist.name)),
    browse.note && h("p", { class: "muted" }, browse.note),
    showingPlaylists && browse.playlists && h("div", { class: "list scroll" }, browse.playlists.map(playlistRow)),
    !showingPlaylists && browse.songs.length > 0 && [
      h("div", { class: "row" },
        h("span", { class: "muted small grow" }, `${browse.songs.length} shown`),
        h("button", { disabled: fresh.length === 0, onclick: () => addSongs(fresh) }, `Add all ${fresh.length} not yet in quiz`)),
      h("div", { class: "list scroll" },
        browse.songs.map((song) => resultRow(song, inQuiz.has(song.spotify_id))),
        browse.nextOffset != null && h("button", { class: "ghost", onclick: browse.more }, "Load more")),
    ]);
}

function playlistRow(playlist) {
  return h("div", { class: "item" },
    songCover(playlist),
    h("div", { class: "grow" },
      h("div", { class: "ellipsis" }, h("strong", null, playlist.name)),
      h("div", { class: "muted small" }, playlist.readable
        ? `${playlist.total} songs`
        : "Not yours: Spotify only lets this app read playlists you own")),
    h("button", { disabled: !playlist.readable, onclick: () => openPlaylist(playlist) }, "Open"));
}

function resultRow(song, added) {
  return h("div", { class: "item" },
    songCover(song),
    h("div", { class: "grow" },
      h("div", { class: "ellipsis" }, h("strong", null, song.title)),
      h("div", { class: "muted small ellipsis" }, `${song.artists.join(", ")}${song.year ? ` · ${song.year}` : ""}`)),
    added
      ? h("span", { class: "muted small" }, "In quiz ✓")
      : h("button", { onclick: () => addSongs([song]) }, "+ Add"));
}

async function addSongs(songs) {
  const result = await api("POST", `/api/quizzes/${quizId}/songs`, { songs });
  toast(`Added ${result.added} song${result.added === 1 ? "" : "s"}`);
  reload();
}

window.addEventListener("unhandledrejection", (event) => toast(event.reason.message));
init();
