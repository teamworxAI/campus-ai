"""HTTP API for collections search (R9). Runs in the `api` service, offline:

    docker compose up web        # then open http://localhost:8080

    GET  /api/health
    GET  /api/search?q=salmon+fishing&k=12     pictures and texts, ranked separately
    POST /api/search/image (form field "file") pictures similar to an uploaded image
    GET  /api/items/{id}                       one item with citations and similar pictures
    GET  /media/{path}                         images in media/ folders under DATA_DIR
"""

from __future__ import annotations

import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from campus_ai.research_assistant import collections
from campus_ai.research_assistant.collections import CollectionsSearch

MAX_UPLOAD = 10 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}  # never JSONL, keys or other data


def create_app(service: CollectionsSearch | None = None) -> FastAPI:
    """The app; builds the real service (model + Neo4j) at startup unless one is given."""
    state: dict = {"service": service}
    lock = threading.Lock()  # one embedding at a time: the model is the bottleneck anyway

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        driver = None
        if state["service"] is None:
            from campus_ai.core.embed import get_embedder
            from campus_ai.core.graph import connect

            embedder, driver = get_embedder(), connect()
            embedder.embed(["warm-up"], kind="query")  # load the model before the first request
            state["service"] = CollectionsSearch(driver, embedder)
        yield
        if driver:
            driver.close()

    app = FastAPI(title="campus-ai collections search", lifespan=lifespan)

    def search() -> CollectionsSearch:
        return state["service"]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "items": search().count()}

    @app.get("/api/search")
    def search_text(q: str = Query(min_length=1, max_length=300), k: int = Query(12, ge=1, le=50)) -> dict:
        with lock:
            pictures = search().pictures(q, k)
            texts = search().texts(q, max(4, k // 2))
        return {"query": q, "pictures": [c.public() for c in pictures], "texts": [c.public() for c in texts]}

    @app.post("/api/search/image")
    def search_image(file: UploadFile, k: int = Query(12, ge=1, le=50)) -> dict:
        if file.content_type not in IMAGE_TYPES:
            raise HTTPException(415, "upload a JPEG, PNG, WebP or GIF image")
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "images up to 10 MB")
        with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "").suffix[:8]) as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                with lock:
                    pictures = search().pictures(tmp.name, k, modality="image")
            except (OSError, ValueError) as error:  # not a readable image
                raise HTTPException(422, "could not read that image") from error
        return {"query": file.filename or "image", "pictures": [c.public() for c in pictures], "texts": []}

    @app.get("/api/items/{item_id:path}")
    def item(item_id: str) -> dict:
        with lock:
            found = search().item(item_id)
        if not found:
            raise HTTPException(404, "no such item")
        return found

    @app.get("/media/{path:path}")
    def media(path: str) -> FileResponse:
        root = collections.DATA_DIR.resolve()
        target = (root / path).resolve()
        # Only images in a harvest's media/ folder, so nothing else under data/ (private data) is served.
        servable = target.is_relative_to(root) and target.parent.name == "media" and target.suffix.lower() in MEDIA_SUFFIXES
        if not servable or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target, headers={"Cache-Control": "public, max-age=86400"})

    return app


app = create_app()
