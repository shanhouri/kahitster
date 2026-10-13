from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, games, pages, quizzes, ws
from app.core import http
from app.core.config import get_settings
from app.core.database import init_db
from app.integrations.spotify import SpotifyError

STATIC = Path(__file__).resolve().parent / "web" / "static"


class FreshStaticFiles(StaticFiles):
    """Static files the browser must revalidate, so a code change shows up on
    the next reload instead of whenever its cache expires."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await http.close_client()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)

for module in (auth, quizzes, games, ws, pages):
    app.include_router(module.router)
app.mount("/static", FreshStaticFiles(directory=STATIC), name="static")


@app.exception_handler(SpotifyError)
async def spotify_error(request: Request, exc: SpotifyError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(httpx.HTTPError)
async def spotify_unreachable(request: Request, exc: httpx.HTTPError):
    return JSONResponse({"detail": "Could not reach Spotify. Check the internet connection."}, status_code=502)
