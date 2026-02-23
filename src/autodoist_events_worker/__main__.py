import logging
import sys
from typing import Optional, Sequence

from .config import EventsConfig
from .service import create_app


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = EventsConfig.from_env_and_cli(argv)
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    app = create_app(config)
    app.run(host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
