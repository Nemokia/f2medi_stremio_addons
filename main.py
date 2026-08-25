"""F2Media Stremio addon entry point.

Flow: Stremio stream request -> Cinemeta metadata -> F2MediaResolver
(discovery + validation + matching) -> content parser -> Stremio streams.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from httpclient.client import HttpClient, HttpClientConfig, HttpError
from httpclient.json_utils import parse_json_response
from parsers.f2medi_parser import parse_f2media_page
from resolvers import F2MediaResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("f2m.app")

app = FastAPI(
    title="F2Medi Stremio Add-on",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_http_client = HttpClient(HttpClientConfig.from_env())
_resolver = F2MediaResolver(http=_http_client)


def get_cinemeta_meta(item_type: str, imdb_id: str) -> dict | None:
    """Fetch item metadata (title/year) from Stremio's Cinemeta addon."""
    url = f"https://v3-cinemeta.strem.io/meta/{item_type}/{imdb_id}.json"
    try:
        response = _http_client.get(url, timeout=15.0)
    except HttpError as exc:
        logger.warning("[CINEMETA] request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("[CINEMETA] status=%d", response.status_code)
        return None

    payload = parse_json_response(response)
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else None


@app.get("/manifest.json")
def get_manifest():
    return {
        "id": "org.f2medi.stremio",
        "version": "3.0.0",
        "name": "F2Medi",
        "description": "جستجوی زنده فیلم و سریال‌های F2Medi برای Stremio",
        "types": ["movie", "series"],
        "resources": ["stream"],
        "idPrefixes": ["tt"],
        "catalogs": [],
    }


@app.get("/stream/{type}/{id}.json")
def get_streams(type: str, id: str):
    parts = id.split(":")
    imdb_id = parts[0]
    season = episode = None
    if type == "series" and len(parts) >= 3:
        season = parts[1]
        episode = parts[2]

    logger.info("[APP] stream request type=%s id=%s", type, imdb_id)

    meta = get_cinemeta_meta(type, imdb_id)
    if not meta or not meta.get("name"):
        logger.warning("[APP] no cinemeta metadata for %s", imdb_id)
        return {"streams": []}

    title = meta["name"]
    year_raw = meta.get("year")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except ValueError:
        year = None

    result = _resolver.resolve(
        title=title,
        item_type=type,
        imdb_id=imdb_id,
        year=year,
    )

    if not result.found or not result.html:
        logger.info("[APP] page not found for %s (%s)", title, imdb_id)
        return {"streams": []}

    try:
        page = parse_f2media_page(result.html, item_type=type, url=result.url or "")
    except Exception:
        logger.exception("[APP] parser crashed")
        return {"streams": []}

    stremio_streams = []
    for stream in page.streams:
        if type == "series":
            if season is not None and stream.season != season.zfill(2):
                continue
            if episode is not None and stream.episode != episode.zfill(2):
                continue

        url_out = stream.url
        if not url_out or url_out.lower().endswith(".mka"):
            continue

        language = (
            "🎤 دوبله فارسی"
            if stream.lang_type == "Dubbed"
            else "📝 زیرنویس چسبیده"
        )
        stremio_streams.append({
            "name": "F2Medi",
            "description": f"{stream.quality}\n{language}",
            "url": url_out,
            "behaviorHints": {
                "notWebReady": True,
                "bingeGroup": f"f2medi-{stream.quality}-{stream.lang_type or 'sub'}",
            },
        })

    logger.info("[APP] returning %d stream(s)", len(stremio_streams))
    return {"streams": stremio_streams}


@app.get("/")
def health():
    return {"status": "ok", "addon": "F2Medi", "version": "3.0.0"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081)
