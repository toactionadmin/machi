"""machi: servicio de reels de episodios del stack de toAction."""

import argparse
import logging
from pathlib import Path


def main() -> None:
    import uvicorn

    from .api import crear_app
    from .config import Config, cargar_env

    p = argparse.ArgumentParser(prog="machi")
    p.add_argument("--env", type=Path, help="archivo KEY=valor con la configuración")
    args = p.parse_args()
    if args.env:
        cargar_env(args.env)

    cfg = Config.desde_entorno()
    # Como servicio de Windows no hay consola: el registro va también a <datos>\machi.log (5 × 5 MB).
    from logging.handlers import RotatingFileHandler

    cfg.datos.mkdir(parents=True, exist_ok=True)
    archivo = RotatingFileHandler(cfg.datos / "machi.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), archivo],
    )
    uvicorn.run(crear_app(cfg), host=cfg.host, port=cfg.puerto, log_level="info")
