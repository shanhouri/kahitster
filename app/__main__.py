"""`python -m app` -- start the server so phones on the Wi-Fi can reach it."""
import uvicorn

from app.core.config import get_settings, public_base_url

if __name__ == "__main__":
    port = get_settings().port
    print(f"\n  Host (sign in here):  http://127.0.0.1:{port}/home")
    print(f"  Players join at:      {public_base_url()}\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
