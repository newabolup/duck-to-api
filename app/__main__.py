import uvicorn

from app.config import get_settings


def main() -> None:
    cfg = get_settings()
    uvicorn.run("app.main:app", host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
