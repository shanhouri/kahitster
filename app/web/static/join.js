import { api, h, logo, mount } from "/static/common.js";

const app = document.getElementById("app");
const pinFromUrl = (location.pathname.split("/")[2] || "").replace(/\D/g, "");

// Each game's seat token lives under its own key, so a phone can rejoin after
// a refresh without asking for the name again.
const seatKey = (pin) => `kahitster:${pin}`;

function storedSeat(pin) {
  try {
    return localStorage.getItem(seatKey(pin));
  } catch {
    return null;
  }
}

if (pinFromUrl && storedSeat(pinFromUrl)) {
  location.replace(`/play/${pinFromUrl}`);
} else {
  const pin = h("input", { type: "tel", inputMode: "numeric", placeholder: "Game PIN", value: pinFromUrl,
    maxLength: 7, autocomplete: "off", required: true, "aria-label": "Game PIN" });
  const name = h("input", { type: "text", placeholder: "Your name", maxLength: 20,
    autocomplete: "off", required: true, "aria-label": "Your name" });
  const error = h("p", { class: "alert", hidden: true, role: "alert" });

  mount(app,
    h("div", { class: "center stack" }, logo()),
    h("form", { class: "stack", onsubmit: join }, pin, name, error, h("button", { class: "primary" }, "Join")),
    h("p", { class: "center muted small" }, "Running the game? ", h("a", { href: "/home" }, "Host sign-in")));
  (pinFromUrl ? name : pin).focus();

  async function join(event) {
    event.preventDefault();
    error.hidden = true;
    try {
      const seat = await api("POST", "/api/join", { pin: pin.value.replace(/\D/g, ""), name: name.value });
      // Both stores: localStorage survives a closed tab, sessionStorage still
      // works in browsers that block localStorage in private mode.
      for (const store of ["localStorage", "sessionStorage"]) {
        try {
          window[store].setItem(seatKey(seat.pin), seat.token);
        } catch {
          // Blocked; the other store may still work.
        }
      }
      location.href = `/play/${seat.pin}`;
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    }
  }
}
