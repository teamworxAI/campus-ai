"""HTTP API for collections search (R9). Runs in the `api` service, offline:

    docker compose up web        # then open http://localhost:8080

    GET  /api/health
    GET  /api/search?q=salmon+fishing&k=12     pictures and texts, ranked separately
    POST /api/search/image (form field "file") pictures similar to an uploaded image
    GET  /api/items/{id}                       one item with citations and similar pictures
    GET  /media/{path}                         images in media/ folders under DATA_DIR
    GET  /api/experts?q=wildfire+smoke         researchers for a topic, with their evidence (R4, journey 4)
    GET  /api/partners?q=...&countries=eu      EU organisations for a call or idea, via matching projects and their own
                                               nodes (journey 1); `signal=projects|organisations|fused` picks the ranking
    GET  /api/calls?q=...&status=open          open and forthcoming Horizon Europe topics (journey 2)
    GET  /api/calls/for/{researcher_id}        the same for one researcher's own profile text
    GET  /api/calls/{call_id}/analysis         the call analyst: topics, outcomes, partner profile, quoted (R4)
    GET  /api/partners/complement?call=...&n=3 what each partner adds to the call, and a complementary set (R4)
    GET  /api/ask?q=...                        route a plain question to journey 1-5 and run its search (R4)
"""

from __future__ import annotations

import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from campus_ai.research_assistant import collections
from campus_ai.research_assistant.collections import CollectionsSearch, picture_match
from campus_ai.research_assistant.call_analyst import analyse, partner_query
from campus_ai.research_assistant.complementarity import assess, complement, details
from campus_ai.research_assistant.consortium import brief, eligibility
from campus_ai.research_assistant.matching import COUNTRY_SETS, DEFAULT_SIGNAL, SIGNALS, ResearchSearch
from campus_ai.research_assistant.router import answer, route

MAX_UPLOAD = 10 * 1024 * 1024
CALL_STATUS = ("open", "forthcoming", "all")
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}  # never JSONL, keys or other data


def create_app(service: CollectionsSearch | None = None, research: ResearchSearch | None = None) -> FastAPI:
    """The app; builds the real services (model + Neo4j) at startup unless they are given."""
    state: dict = {"service": service, "research": research}
    lock = threading.Lock()  # one embedding at a time: the model is the bottleneck anyway
    analyses: dict[str, dict] = {}  # call analyses by call id, for the life of the process (the model takes minutes)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        driver = None
        if state["service"] is None:
            from campus_ai.core.embed import get_embedder
            from campus_ai.core.graph import connect

            embedder, driver = get_embedder(), connect()
            embedder.embed(["warm-up"], kind="query", data_class="P")  # load the model before the first request
            state["service"] = CollectionsSearch(driver, embedder)
        if state["research"] is None:  # same graph and model as collections search
            given = state["service"]
            state["research"] = ResearchSearch(given.driver, given.retriever.embedder, given.database)
        yield
        if driver:
            driver.close()

    app = FastAPI(title="campus-ai research assistant", lifespan=lifespan)

    def search() -> CollectionsSearch:
        return state["service"]

    def graph() -> ResearchSearch:
        return state["research"]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "items": search().count(), "graph": graph().counts()}

    @app.get("/api/experts")
    def experts(q: str = Query(min_length=1, max_length=500), k: int = Query(10, ge=1, le=30)) -> dict:
        with lock:
            found = graph().experts(q, k)
        return {"query": q, "experts": found}

    @app.get("/api/partners")
    def partners(q: str = Query(min_length=1, max_length=2000), k: int = Query(10, ge=1, le=30),
                 countries: str = Query("associated"), signal: str | None = Query(None)) -> dict:
        if countries not in COUNTRY_SETS:
            raise HTTPException(422, f"countries must be one of {', '.join(COUNTRY_SETS)}")
        if signal is not None and signal not in SIGNALS:
            raise HTTPException(422, f"signal must be one of {', '.join(SIGNALS)}")
        with lock:
            found = graph().partners(q, k, countries, signal=signal)
        return {"query": q, "countries": countries, "signal": signal or DEFAULT_SIGNAL, "partners": found}

    @app.get("/api/calls")
    def calls(q: str = Query(min_length=1, max_length=2000), k: int = Query(10, ge=1, le=30),
              status: str = Query("open")) -> dict:
        if status not in CALL_STATUS:
            raise HTTPException(422, f"status must be one of {', '.join(CALL_STATUS)}")
        with lock:
            found = graph().calls(q, k, status)
        return {"query": q, "status": status, "calls": found}

    @app.post("/api/brief")
    def consortium_brief(body: dict) -> dict:
        """Journey 3: partners for a call (by id) or an idea (text), the eligibility check and a citation-checked brief."""
        query, call_id = (body.get("query") or "").strip(), body.get("call_id")
        countries = body.get("countries") or "associated"
        if countries not in COUNTRY_SETS:
            raise HTTPException(422, f"countries must be one of {', '.join(COUNTRY_SETS)}")
        k = max(1, min(int(body.get("k") or 6), 12))
        home = {"name": body.get("home_name") or "Simon Fraser University", "country": (body.get("home_country") or "CA").upper()}
        with lock:
            call = graph().call(call_id) if call_id else None
            if call_id and not call:
                raise HTTPException(404, "no such call topic")
            text = query or (f"{call['title']}. {call.get('call_title') or ''}" if call else "")
            if not text:
                raise HTTPException(422, "give a call_id or a query")
            found = graph().partners(text, k, countries, home=home["country"])
        chosen = [p for p in found if not body.get("members") or p["id"] in body["members"]]
        actions = (call or {}).get("actions") or []
        check = eligibility(chosen + [{"country": home["country"]}], actions[0] if actions else "", (call or {}).get("parts") or [])
        try:
            draft = brief(call, chosen, home)
        except Exception as error:  # the model being down is reported, not fatal: the shortlist and check stand
            draft = {"brief": "", "error": f"{type(error).__name__}: {str(error)[:200]}", "needs_review": True}
        return {"query": text, "call": call, "home": home, "partners": chosen, "eligibility": check, "brief": draft}

    def analysis_of(call_id: str) -> dict:
        if call_id in analyses:
            return {**analyses[call_id], "cached": True}
        with lock:
            call = graph().call(call_id)
        if not call:
            raise HTTPException(404, "no such call topic")
        result = analyse(call)
        result["partner_query"] = partner_query(result)
        if not result.get("model_error"):  # a failed run is retried next time
            analyses[call_id] = result
        return {**result, "cached": False}

    @app.get("/api/calls/{call_id}/analysis")
    def call_analysis(call_id: str) -> dict:
        """The call analyst (R4): facts from the records plus span-checked topics, outcomes and partner profile."""
        return analysis_of(call_id)

    @app.get("/api/partners/complement")
    def partners_complement(call: str = Query(min_length=1, max_length=200), q: str = Query("", max_length=2000),
                            k: int = Query(10, ge=1, le=30), n: int = Query(3, ge=1, le=10),
                            countries: str = Query("associated")) -> dict:
        """What each partner on the call's shortlist adds, the set view and a complementary pick of n (R4, no model call
        unless the call has not been analysed in this process yet)."""
        if countries not in COUNTRY_SETS:
            raise HTTPException(422, f"countries must be one of {', '.join(COUNTRY_SETS)}")
        analysis = analysis_of(call)
        query = q.strip() or analysis.get("partner_query") or analysis.get("title") or ""
        with lock:
            shortlist = graph().partners(query, k, countries)
            info = details(graph(), shortlist)
        assessed = assess(shortlist, analysis, info)
        return {"call": {key: analysis.get(key) for key in ("id", "identifier", "title", "url", "action")}, "query": query,
                "countries": countries, "analysis_cached": analysis["cached"], "model_error": analysis.get("model_error"),
                "needs": assessed["needs"], "roles_needed": assessed["roles_needed"], "partners": assessed["partners"],
                "set": assessed["set"], "complementary": complement(shortlist, analysis, n, info)}

    @app.get("/api/ask")
    def ask(q: str = Query(min_length=1, max_length=2000), k: int = Query(10, ge=1, le=30)) -> dict:
        """One box for every journey: rules first, the local model only when no rule fires."""
        routed = route(q)  # outside the lock: the model may be asked
        with lock:
            return answer(q, graph(), search(), k, routed)

    @app.get("/api/calls/for/{researcher_id:path}")
    def calls_for(researcher_id: str, k: int = Query(10, ge=1, le=30), status: str = Query("open")) -> dict:
        if status not in CALL_STATUS:
            raise HTTPException(422, f"status must be one of {', '.join(CALL_STATUS)}")
        with lock:
            found = graph().calls_for(researcher_id, k, status)
        if not found["researcher"]:
            raise HTTPException(404, "no such researcher")
        return found

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
        best = pictures[0].similarity if pictures else None
        return {
            "query": file.filename or "image",
            "pictures": [c.public() for c in pictures],
            "texts": [],
            # "same": the picture is in the index; "close": similar ones; "none": nothing close,
            # so the list is only the nearest of what the index holds.
            "match": picture_match(best),
            "best_similarity": best,
            "indexed_items": search().count(),
        }

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
