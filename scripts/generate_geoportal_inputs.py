"""Generate minimal input files from human-reviewed Geoportal outputs.

Reads selected Geoportal JSON files (full DataCite 4.6 metadata outputs),
extracts the minimal fields the pipeline needs (url, title, description,
publisher), and writes them to tests/fixtures/geoportal/inputs/.

The original Geoportal files serve as ground truth for comparison.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GEOPORTAL_DIR = Path("examples/Geoportal")
OUTPUT_DIR = Path("tests/fixtures/geoportal/inputs")

SELECTED_FILES = [
    "183. Establecimientos de salud de Chile Febrero 2026.json",
    "195. Red Vial Nacional.json",
    "290. Humedales.json",
    "207. Capitales.json",
    "264. Territorios con Potencial Turistico 2024.json",
    "273. Establecimientos de Educacion Superior.json",
    "294. Pasos Fronterizos.json",
    "387. Antenas en Servicio Ley de Torres.json",
    "411. Datos Censo 2017 Comuna.json",
    "474. Centrales termoelectricas.json",
    "482. Pisos vegetacionales de Luebert y Pliscoff 2017.json",
    "266. Red Ferroviaria.json",
]


def extract_input(geoportal_data: dict) -> dict:
    attrs = geoportal_data["metadata"]["attributes"]

    url = attrs.get("resource", {}).get("identifier", "")
    titles = attrs.get("titles", [])
    title = titles[0]["name"] if titles else ""
    descriptions = attrs.get("descriptions", [])
    description = descriptions[0]["description"] if descriptions else ""
    publishers = attrs.get("publishers", [])
    publisher = publishers[0].get("publisher_name", "") if publishers else ""

    return {
        "url": url,
        "title": title,
        "description": description,
        "publisher": publisher,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    found = 0
    missing = 0

    for filename in SELECTED_FILES:
        src = GEOPORTAL_DIR / filename
        if not src.exists():
            print(f"  SKIP (not found): {filename}", file=sys.stderr)
            missing += 1
            continue

        data = json.loads(src.read_text(encoding="utf-8"))
        input_data = extract_input(data)

        dst = OUTPUT_DIR / filename
        dst.write_text(
            json.dumps(input_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        found += 1
        print(f"  OK: {filename} → url={input_data['url'][:60]}...")

    print(f"\n{found} inputs generated, {missing} missing.")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
