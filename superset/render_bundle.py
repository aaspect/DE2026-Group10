"""Turns the committed dashboard bundle into the zip that `superset import-dashboards` reads.

The bundle's database file holds the placeholder `${SUPERSET_WAREHOUSE_URI}` instead of a
connection URI, so no credentials are committed. This script fills it in from the environment.

Usage: python render_bundle.py [bundle_dir] [output_zip]
"""

import os
import sys
import zipfile
from pathlib import Path

URI_VARIABLE = "SUPERSET_WAREHOUSE_URI"
URI_PLACEHOLDER = "${SUPERSET_WAREHOUSE_URI}"
DEFAULT_BUNDLE_DIR = Path("/app/dashboards/past_weather")
DEFAULT_OUTPUT_ZIP = Path("/tmp/past_weather.zip")


def main() -> int:
    warehouse_uri = os.environ.get(URI_VARIABLE)
    if not warehouse_uri:
        print(f"{URI_VARIABLE} is not set: the dashboard bundle cannot be built", file=sys.stderr)
        return 1
    bundle_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BUNDLE_DIR
    output_zip = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_ZIP
    write_bundle_zip(bundle_dir, output_zip, warehouse_uri)
    print(output_zip)
    return 0


def write_bundle_zip(bundle_dir: Path, output_zip: Path, warehouse_uri: str) -> None:
    """Zip every file of the bundle under the bundle's folder name, as an export has them."""
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(bundle_dir)
            text = path.read_text(encoding="utf-8")
            if relative_path.match("databases/*.yaml"):
                # A plain replacement, not string.Template: any other "$" must stay as it is.
                text = text.replace(URI_PLACEHOLDER, warehouse_uri)
            archive.writestr(f"{bundle_dir.name}/{relative_path.as_posix()}", text)


if __name__ == "__main__":
    raise SystemExit(main())
