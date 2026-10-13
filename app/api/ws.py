"""The two live connections: the host's big screen and each player's phone."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import same_origin, session_account_id
from app.services import game as games

router = APIRouter()


async def _open(ws: WebSocket, pin: str) -> games.Game | None:
    await ws.accept()
    game = games.get_game(pin)
    if game is None:
        await ws.send_json(games.fatal("no_game", "This game no longer exists"))
        await ws.close()
    return game


@router.websocket("/ws/host/{pin}")
async def host_socket(ws: WebSocket, pin: str):
    game = games.get_game(pin)
    owns = game is not None and same_origin(ws) and session_account_id(ws) == game.owner_id
    if game is not None and not owns:
        await ws.close(code=1008)
        return
    game = await _open(ws, pin)
    if game is None:
        return

    game.host_sockets.add(ws)
    try:
        await ws.send_json(game.host_state())
        while True:
            message = await ws.receive_json()
            # Pings only keep a free hosting plan from putting the server to sleep.
            if message.get("type") == "ping":
                continue
            try:
                await _host_action(game, message)
            except games.GameError as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
            await game.broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        game.host_sockets.discard(ws)


async def _host_action(game: games.Game, message: dict) -> None:
    match message.get("type"):
        case "start":
            await game.start()
        case "end_round":
            await game.end_question()
        case "leaderboard":
            game.show_leaderboard()
        case "next":
            await game.next()
        case "replay":
            await game.replay()
        case "end_game":
            await game.finish()
        case "kick":
            await game.kick(str(message.get("player_id")))
        case "override":
            game.override(
                str(message.get("player_id")), message.get("part"), bool(message.get("ok"))
            )


@router.websocket("/ws/play/{pin}")
async def player_socket(ws: WebSocket, pin: str):
    game = await _open(ws, pin)
    if game is None:
        return

    player = None
    try:
        # The first message says who this is; the token never goes in the URL.
        hello = await ws.receive_json()
        player = game.player_by_token(str(hello.get("token")))
        if player is None:
            await ws.send_json(games.fatal("unknown_player", "Join the game again"))
            await ws.close()
            return

        player.sockets.add(ws)
        await game.broadcast()
        while True:
            message = await ws.receive_json()
            if message.get("type") != "answer":
                continue
            try:
                game.submit_answer(
                    player.id, message.get("title"), message.get("artist"), message.get("year")
                )
            except games.GameError as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
                continue
            if game.everyone_answered():
                await game.end_question()
            await game.broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        if player is not None:
            player.sockets.discard(ws)
            await game.broadcast()
