"""Crea la base de datos «Reels propuestos» de machi dentro de una página de Notion.

Uso (la página tiene que estar compartida con la integración):
    $env:NOTION_TOKEN = "..."; .venv\\Scripts\\python scripts\\crear_base_notion.py <id o URL de la página>

Imprime el ID de la base para poner en NOTION_DB_ID.
"""

import os
import re
import sys

import httpx

from machi.notion import API, PROPIEDADES, VERSION


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    m = re.search(r"([0-9a-f]{32})", sys.argv[1].replace("-", ""))
    if not m:
        sys.exit("No reconozco el ID de la página")
    r = httpx.post(
        f"{API}/databases",
        headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}", "Notion-Version": VERSION},
        json={
            "parent": {"type": "page_id", "page_id": m.group(1)},
            "title": [{"type": "text", "text": {"content": "Reels propuestos"}}],
            "initial_data_source": {"properties": PROPIEDADES},
        },
        timeout=30,
    )
    if r.status_code >= 400:
        sys.exit(f"Notion respondió {r.status_code}: {r.text}")
    base = r.json()
    print(f"NOTION_DB_ID={base['id']}")
    print(f"URL: {base.get('url', '')}")


if __name__ == "__main__":
    main()
