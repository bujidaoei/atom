"""Run the private single-process broker on loopback."""
import uvicorn

from .config import BrokerConfig
from .service import create_app


def main():
    config = BrokerConfig.from_env()
    uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, workers=1,
                proxy_headers=False, access_log=False, limit_concurrency=32,
                timeout_keep_alive=5)


if __name__ == "__main__":
    main()
