"""Legacy committed-map helper (DM-9; superseded by DESIGN v3.72).

Admin → Demo Mode now queues versioned private map assets through the worker.
This file remains for historical/local fixtures only and refuses a real capture
unless `--allow-legacy` is explicit. A dry run remains read-only.

A demo session must never call the Maps JS API: every load is billable, and the
browser key would be handed to the public along with the session. `MapFrame`
already refuses to call `loadGoogleMaps()` when `isDemo()` — this script
produces the images it renders instead.

**Basemaps only, deliberately no pins.** Static Maps *can* draw markers, but
baking them in would be wrong twice over. A pin's colour is its Unit Group's
score band, so a Rubric change would silently leave the map asserting a score
the Hunt no longer computes — the same staleness trap that makes a Replay
Capture need re-exporting. And a baked pin is not clickable, while the Hunt map
exists to be clicked. So the still is the basemap, and the app draws real pins
over it from live data: correct colours, correct theme, still interactive.

That is also why each still records its `center`/`zoom`/`size` in the manifest.
The frontend needs them to project a coordinate back to a pixel; a still without
its projection metadata is unusable, not merely undocumented.

Both colour schemes are captured, because `mapTheme.basemapStyle()` restyles the
real map at runtime and a single still would be wrong in one of them.

Usage:
    uv run python scripts/capture_demo_maps.py --allow-legacy  # legacy capture
    uv run python scripts/capture_demo_maps.py --dry-run  # print plan, fetch nothing

Reads `GOOGLE_MAPS_API_KEY` (the **server** key) from the environment or `.env`.
The browser key is referrer-restricted and rejects Static Maps by design. The
server key is used offline, at capture time, and is never written into the
manifest or the images -- only the resulting pictures ship.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "frontend/src/features/demo/maps"
MANIFEST = OUT_DIR / "manifest.json"

STATIC_MAPS = "https://maps.googleapis.com/maps/api/staticmap"

# Static Maps caps `size` at 640x640; `scale=2` doubles the delivered pixels
# without counting against that, which is what makes these legible on a
# retina display.
SCALE = 2
DRAWER_SIZE = (640, 260)  # ListingLocationMap renders 200px tall, full width
HUNT_SIZE = (640, 400)  # HuntMapPage renders tall; 1.6 suits a desktop canvas
DRAWER_ZOOM = 15  # matches ListingLocationMap's ZOOM
HUNT_PADDING_PX = 64  # matches HuntMapPage's fitBounds padding

TILE = 256  # Web Mercator tile size, the projection both sides agree on

# Transcribed from `frontend/src/features/map/mapTheme.ts`. Static Maps takes
# the same styling vocabulary as the JS `styles` array, in URL form. Keep these
# in step with that file: a drifted still is a demo whose map does not match the
# app's own chrome.
DARK_STYLE = [
    "element:geometry|color:0x262320",
    "element:labels.text.fill|color:0x8B867E",
    "element:labels.text.stroke|color:0x161412",
    "feature:administrative|element:geometry|color:0x48443E",
    "feature:poi|visibility:off",
    "feature:park|element:geometry|color:0x302C27",
    "feature:road|element:geometry|color:0x3D3933",
    "feature:road|element:labels.text.fill|color:0x8B867E",
    "feature:road.highway|element:geometry|color:0x48443E",
    "feature:transit|visibility:off",
    "feature:water|element:geometry|color:0x201D1A",
]
LIGHT_STYLE = [
    "feature:poi.business|visibility:off",
    "feature:transit|element:labels.icon|visibility:off",
]


class CaptureError(RuntimeError):
    """The stills cannot be produced honestly."""


@dataclass
class Place:
    slug: str
    name: str
    lat: float
    lng: float


def _api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.is_file():
        match = re.search(r'^GOOGLE_MAPS_API_KEY\s*=\s*["\']?([^"\'\n#]+)', env.read_text(), re.M)
        if match:
            return match.group(1).strip()
    raise CaptureError(
        "GOOGLE_MAPS_API_KEY is not set and .env does not carry it. This must be "
        "the server key: the browser key is referrer-restricted and Static Maps "
        "rejects it with 403."
    )


# ── Web Mercator ─────────────────────────────────────────────────────────────
# The frontend reimplements the inverse of this in `demoProjection.ts`. Both
# must agree exactly or a pin lands off its building, so the formulas are
# written out here rather than hidden behind a library.


def _project(lat: float, lng: float) -> tuple[float, float]:
    """Longitude/latitude to unit-tile world coordinates at zoom 0."""
    siny = math.sin(math.radians(lat))
    # Clamp near the poles, where the projection diverges.
    siny = min(max(siny, -0.9999), 0.9999)
    return (
        TILE * (0.5 + lng / 360),
        TILE * (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)),
    )


def _fit(places: list[Place], size: tuple[int, int], padding: int) -> tuple[float, float, int]:
    """Center and integer zoom that fit every place, mirroring `fitBounds`."""
    if not places:
        raise CaptureError("No mapped places; there is no hunt-wide still to take.")
    lats = [p.lat for p in places]
    lngs = [p.lng for p in places]
    center_lat = (min(lats) + max(lats)) / 2
    center_lng = (min(lngs) + max(lngs)) / 2

    if len(places) == 1:
        return center_lat, center_lng, DRAWER_ZOOM

    sw = _project(min(lats), min(lngs))
    ne = _project(max(lats), max(lngs))
    span_x = abs(ne[0] - sw[0]) or 1e-9
    span_y = abs(sw[1] - ne[1]) or 1e-9
    usable_w = max(size[0] - 2 * padding, 1)
    usable_h = max(size[1] - 2 * padding, 1)
    zoom = min(
        math.floor(math.log2(usable_w / span_x)),
        math.floor(math.log2(usable_h / span_y)),
    )
    return center_lat, center_lng, max(0, min(21, zoom))


def _url(
    center: tuple[float, float], zoom: int, size: tuple[int, int], dark: bool, key: str
) -> str:
    params = [
        ("center", f"{center[0]},{center[1]}"),
        ("zoom", str(zoom)),
        ("size", f"{size[0]}x{size[1]}"),
        ("scale", str(SCALE)),
        ("format", "png"),
        ("maptype", "roadmap"),
    ]
    for style in DARK_STYLE if dark else LIGHT_STYLE:
        params.append(("style", style))
    params.append(("key", key))
    return f"{STATIC_MAPS}?{urllib.parse.urlencode(params)}"


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf8", "replace")
        raise CaptureError(f"Static Maps returned {exc.code}: {detail}") from exc
    # Static Maps answers some failures with a 200 and a PNG of an error string,
    # which would ship a picture of a stack trace into the demo.
    if not body.startswith(b"\x89PNG"):
        raise CaptureError(f"Static Maps returned {len(body)} bytes that are not a PNG.")
    return body


def _to_webp(png: bytes, destination: Path) -> int:
    """WebP if Pillow is available, PNG otherwise. Returns bytes written."""
    try:
        import io

        from PIL import Image
    except ImportError:
        fallback = destination.with_suffix(".png")
        fallback.write_bytes(png)
        print(f"    ! Pillow missing — wrote {fallback.name} instead of WebP")
        return len(png)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.save(destination, "WEBP", quality=82, method=6)
    return destination.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, fetch nothing")
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="acknowledge that Admin → Demo Mode is the supported publication path",
    )
    parser.add_argument(
        "--places",
        type=Path,
        default=None,
        help="JSON list of {slug,name,lat,lng}; defaults to reading stdin",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.allow_legacy:
        parser.error(
            "committed Demo maps were superseded by Admin → Demo Mode; "
            "use --allow-legacy only for an intentional historical/local fixture"
        )

    raw = (args.places.read_text() if args.places else sys.stdin.read()).strip()
    if not raw:
        raise CaptureError("No places given. Pass --places <file.json> or pipe JSON on stdin.")
    places = [Place(**entry) for entry in json.loads(raw)]

    key = "DRY-RUN" if args.dry_run else _api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "note": (
            "Generated by scripts/capture_demo_maps.py. Basemaps only — the app "
            "draws real pins over these, so a Rubric change does not stale them. "
            "center/zoom/size are the projection contract with demoProjection.ts."
        ),
        "scale": SCALE,
        "tileSize": TILE,
        "properties": {},
    }

    total = 0
    for place in places:
        entry: dict[str, object] = {
            "name": place.name,
            "center": {"lat": place.lat, "lng": place.lng},
            "zoom": DRAWER_ZOOM,
            "size": {"width": DRAWER_SIZE[0], "height": DRAWER_SIZE[1]},
            "images": {},
        }
        for scheme, dark in (("light", False), ("dark", True)):
            name = f"{place.slug}-{scheme}.webp"
            print(f"  {name} — {place.name} @ z{DRAWER_ZOOM}")
            if not args.dry_run:
                written = _to_webp(
                    _fetch(_url((place.lat, place.lng), DRAWER_ZOOM, DRAWER_SIZE, dark, key)),
                    OUT_DIR / name,
                )
                total += written
                print(f"    {written / 1024:.0f} kB")
            entry["images"][scheme] = name  # type: ignore[index]
        manifest["properties"][place.slug] = entry  # type: ignore[index]

    hunt_lat, hunt_lng, hunt_zoom = _fit(places, HUNT_SIZE, HUNT_PADDING_PX)
    hunt: dict[str, object] = {
        "center": {"lat": hunt_lat, "lng": hunt_lng},
        "zoom": hunt_zoom,
        "size": {"width": HUNT_SIZE[0], "height": HUNT_SIZE[1]},
        "images": {},
    }
    for scheme, dark in (("light", False), ("dark", True)):
        name = f"hunt-{scheme}.webp"
        print(f"  {name} — hunt-wide @ z{hunt_zoom} ({hunt_lat:.4f},{hunt_lng:.4f})")
        if not args.dry_run:
            written = _to_webp(
                _fetch(_url((hunt_lat, hunt_lng), hunt_zoom, HUNT_SIZE, dark, key)),
                OUT_DIR / name,
            )
            total += written
            print(f"    {written / 1024:.0f} kB")
        hunt["images"][scheme] = name  # type: ignore[index]
    manifest["hunt"] = hunt

    if not args.dry_run:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"\n{MANIFEST.relative_to(ROOT)} written; {total / 1024:.0f} kB of stills total.")
    else:
        print("\nDry run — nothing fetched, nothing written.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CaptureError as exc:
        sys.exit(f"capture-demo-maps: {exc}")
