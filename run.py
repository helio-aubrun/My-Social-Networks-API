import logging
import sys
from pathlib import Path

import uvicorn

from app.config import ROOT, get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()

    if not settings.ssl_key_path or not settings.ssl_cert_path:
        sys.exit("[ERROR] SSL_KEY_PATH et SSL_CERT_PATH doivent être définis dans .env")
    key, cert = ROOT / settings.ssl_key_path, ROOT / settings.ssl_cert_path
    for path in (key, cert):
        if not Path(path).is_file():
            sys.exit(f"[ERROR] Fichier introuvable : {path} (générez-le avec python scripts/generate_cert.py)")

    logging.info("[API] écoute sur https://%s:%s", settings.host, settings.port)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        ssl_keyfile=str(key),
        ssl_certfile=str(cert),
        server_header=False,
        date_header=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
