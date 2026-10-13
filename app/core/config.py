import secrets
import socket
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to the project root rather than the working directory, so the app
# finds .env and its database no matter where it is launched from.
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """App configuration, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_name: str = "Kahitster"
    # SQLite by default; a postgres:// URL (e.g. from Neon) when hosted.
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'kahitster.db').as_posix()}"

    # Spotify app credentials (dashboard -> your app -> settings).
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    # Leave empty to derive it; see redirect_uri().
    spotify_redirect_uri: str = ""

    # Where players reach the app, baked into the join QR code. Empty means
    # "work it out": the hosting platform's URL, else this machine's LAN address.
    public_base_url: str = ""
    # Set by Render on every service.
    render_external_url: str = ""
    port: int = 8000

    # Signs host login cookies. Must be set when hosted; see secret_key().
    secret_key: str = ""

    http_timeout: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


def lan_ip() -> str:
    """This machine's address on the local network, as phones would dial it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting a UDP socket sends nothing; it only makes the OS pick the
        # outgoing interface, whose address is what we are after.
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _configured_base_url() -> str:
    settings = get_settings()
    return (settings.public_base_url or settings.render_external_url).rstrip("/")


def public_base_url() -> str:
    return _configured_base_url() or f"http://{lan_ip()}:{get_settings().port}"


def is_https() -> bool:
    return public_base_url().startswith("https://")


def redirect_uri() -> str:
    """Where Spotify sends the host back after login.

    Spotify accepts https addresses or the http loopback IP, nothing else --
    not "localhost", not a LAN address. So: the public site when it is https,
    otherwise this computer.
    """
    settings = get_settings()
    if settings.spotify_redirect_uri:
        return settings.spotify_redirect_uri
    if is_https():
        return f"{public_base_url()}/auth/callback"
    return f"http://127.0.0.1:{settings.port}/auth/callback"


@lru_cache
def secret_key() -> bytes:
    """Key for signing login cookies.

    Hosted, it comes from SECRET_KEY. On a home computer it is generated once
    and kept in a git-ignored file, so restarting the server does not sign
    everyone out.
    """
    configured = get_settings().secret_key
    if configured:
        return configured.encode()
    path = BASE_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
    return path.read_text().strip().encode()
