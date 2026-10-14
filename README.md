# Kahitster

A Kahoot-style "guess the song" party game played from your own Spotify.

You build a quiz from songs in your Spotify account, start it in front of the
room, and everyone joins from their phone with a QR code or PIN. Each round a
song plays on your speaker and players type the **song name** and **artist**;
optionally they also guess the **year**. Faster correct answers score more.

Only the host needs Spotify (Premium) and signs in. Players need nothing but a
browser.

## Put it online (free)

Hosted online, players join from any network with no setup on anyone's
computer. It uses two free services: **Render** runs the app and **Neon** keeps
the quizzes.

**1. Spotify app.** Create an app at https://developer.spotify.com/dashboard
(tick **Web API**). In its **Settings** you will need the **Client ID** and
**Client secret** below. Under the **User Management** tab, add the name and
Spotify email of everyone who will host.

**2. Code on GitHub.** Put this folder in a GitHub repository (private is
fine). `.env`, the local database and `.secret_key` are git-ignored and must
stay out of it.

**3. Database on Neon.** Sign up at https://neon.com, create a project, and
copy its connection string. Turn **Connection pooling off** before copying; the
string starts with `postgresql://`.

**4. App on Render.** Sign up at https://render.com, choose **New → Blueprint**
and pick the repository. Render reads `render.yaml` and asks for three values:

| Name | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `SPOTIFY_CLIENT_ID` | from the Spotify app's Settings |
| `SPOTIFY_CLIENT_SECRET` | from the Spotify app's Settings |

When the deploy finishes, Render shows the site's address, such as
`https://kahitster.onrender.com`.

**5. Tell Spotify the address.** In the Spotify app's Settings, add this
redirect URI, with your own address:

```
https://kahitster.onrender.com/auth/callback
```

Then open `https://kahitster.onrender.com/home` and sign in.

### What "free" costs

- **The site sleeps after 15 idle minutes** and takes about a minute to wake.
  Open it a minute or two before the party.
- **A game in progress lives in memory.** If Render restarts the service, that
  game is gone; saved quizzes are safe in the database. A running game keeps
  the site awake by itself.
- **Up to 5 hosts.** Spotify only lets people listed under User Management
  sign in, and caps the list. Players are unlimited and never sign in.

## Run it on your own computer

Useful for building quizzes or changing the code. Needs Python 3.11 or newer.
In PowerShell, from this folder:

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Then put your Spotify keys in `.env`:

1. In the Spotify app's Settings, add the redirect URI
   `http://127.0.0.1:8000/auth/callback`, exactly. Spotify rejects `localhost`.
2. Open the `.env` file you just created and paste the **Client ID** and **Client secret** from the Spotify app's
   Settings page after the `=` on these two lines, with no spaces or quotes:

   ```
   SPOTIFY_CLIENT_ID=paste_client_id_here
   SPOTIFY_CLIENT_SECRET=paste_client_secret_here
   ```

   Save the file. If the server is already running, stop it with Ctrl+C and
   start it again, since `.env` is only read at startup. Keep the secret out
   of `.env.example` and anywhere else you might share.
3. Back on the Spotify dashboard website (not in `.env`): open your app, click
   **Settings**, then the **User Management** tab next to *Basic Information*.
   Enter the name and Spotify email of whoever will host and click
   **Add user**. Do this even for your own account if login is refused.

```bash
python -m app
```

Open `http://127.0.0.1:8000/home` to sign in. Quizzes made here are stored in
`kahitster.db` on this computer, separately from the online site.

For phones to join a game run this way they must be on the same Wi-Fi, and
Windows must allow incoming connections to Python on that network. Hosting
online avoids both.

## Hosting a game

1. Open `/home` on the site and press **Sign in with Spotify**.
2. **Create quiz**, then add songs by search, from your playlists, or from
   Liked Songs. Set the time per song and whether to guess the year.
   - Years highlighted in yellow come from a remaster or compilation and may be
     the re-release date. Type the right year if you use year guessing.
   - The **⋯** button on a song lets you accept other spellings, for example
     a transliterated title.
3. Open Spotify on the device connected to the speaker and play anything for
   a second, so Spotify sees it as active.
4. Press **Start game**. Put the browser tab on the big screen, pick the device
   at the bottom, and wait for players to join.
5. After each song the reveal screen lists what everyone typed. Click a ✓ or ✗
   to overrule the spell-checker.

Show only the browser tab on the big screen: the Spotify app itself displays
the song that is playing.

## Scoring

| Part | Points |
|---|---|
| Song name | up to 500, sliding to 250 for the slowest answer |
| Artist (any one credited artist) | up to 500, same slide |
| Year | 500 for the exact year, 100 fewer for each year off (2 years off: 300; 5 or more: 0) |

Spelling is forgiving: case, accents, punctuation and suffixes like
"- Remastered 2011" are ignored, and longer names allow one to three typos.
Hebrew final letters and geresh marks don't matter, and a guess that contains
the whole title with a word or two around it (a line from the chorus) counts.

Names are accepted in English and Hebrew: when songs are added, the app asks
Spotify for their Hebrew names too ("עודד מנשה" for "Oded Menashe") and adds
any it has to the song's accepted answers, visible under **⋯** in the editor.
Set `OTHER_NAMES_LANGUAGE` to another language code, or empty to turn it off.
The rules are in `app/services/scoring.py` and `app/services/matching.py`.

## Limits

- Spotify lets a development-mode app read only playlists you own or
  collaborate on, and returns 10 search results at a time.
- Music plays through the host's Spotify, never on players' phones.
- Spotify's developer terms restrict games built on its content. This is meant
  for private use among friends.

## How it is built

```
app/
  main.py              app assembly
  core/                settings, database, host sign-in
  models.py            hosts, quizzes, songs (SQLite locally, Postgres online)
  integrations/        Spotify Web API client
  services/            matching, scoring, the live game, playback
  api/                 routes: auth, quizzes, games, WebSockets, pages
  web/                 plain HTML, CSS and JS -- no build step
render.yaml            hosting blueprint
tests/
```

Signing in with Spotify is what makes someone a host. Each host sees only
their own quizzes and games; players can only join and answer.

```bash
python -m pytest
```
