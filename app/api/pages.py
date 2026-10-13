"""HTML pages. They are static files; each page's script reads ids from the URL
and fetches its data, so no request value is ever interpolated into markup."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.core.security import session_account_id

TEMPLATES = Path(__file__).resolve().parents[1] / "web" / "templates"

router = APIRouter(include_in_schema=False)


def _page(name: str) -> FileResponse:
    # Pages are tiny and change with the code; never serve a stale one.
    return FileResponse(TEMPLATES / name, headers={"Cache-Control": "no-store"})


def _host_page(request: Request, name: str):
    # Only a convenience: the page holds no data, and the API behind it checks
    # the login properly. This just spares a signed-out host a broken screen.
    if session_account_id(request) is None:
        return RedirectResponse("/home")
    return _page(name)


@router.get("/")
async def root(request: Request):
    # A signed-in host lands on their quizzes; everyone else gets the PIN box.
    signed_in = session_account_id(request) is not None
    return _page("home.html" if signed_in else "join.html")


@router.get("/home")
async def home():
    return _page("home.html")


@router.get("/quiz/{quiz_id}")
async def editor(quiz_id: int, request: Request):
    return _host_page(request, "editor.html")


@router.get("/host/{pin}")
async def host(pin: str, request: Request):
    return _host_page(request, "host.html")


@router.get("/join")
@router.get("/join/{pin}")
async def join(pin: str | None = None):
    return _page("join.html")


@router.get("/play/{pin}")
async def play(pin: str):
    return _page("play.html")


@router.get("/healthz")
async def health():
    return {"ok": True}
