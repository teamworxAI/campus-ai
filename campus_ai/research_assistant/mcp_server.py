"""Research Assistant as an MCP server (card P4): thin wrappers over the R4/R5/R9 functions.

    python -m campus_ai.research_assistant.mcp_server           # stdio, for MCP clients
    python -m campus_ai.research_assistant.mcp_server --http 8000

The embedding model and the Neo4j connection are made on the first tool call
(as `api.py` does), so listing the tools needs neither. Needs the embed image.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from campus_ai.core.mcp import build_server, serve
from campus_ai.research_assistant.consortium import brief, eligibility
from campus_ai.research_assistant.matching import ResearchSearch


def create_server(research: ResearchSearch | None = None, collections=None) -> MCPServer:
    """The server; builds the real services (model + Neo4j) on first use unless they are given."""
    state = {"research": research, "collections": collections}

    def services() -> tuple:
        if state["collections"] is None and state["research"] is None:
            from campus_ai.core.embed import get_embedder
            from campus_ai.core.graph import connect
            from campus_ai.research_assistant.collections import CollectionsSearch

            state["collections"] = CollectionsSearch(connect(), get_embedder())
        if state["research"] is None:  # same graph and model as collections search
            given = state["collections"]
            state["research"] = ResearchSearch(given.driver, given.retriever.embedder, given.database)
        return state["research"], state["collections"]

    def find_experts(query: str, k: int = 10, data_class: str = "P") -> list[dict]:
        """Find researchers for a topic, ranked, each with the publications that are the evidence."""
        return services()[0].experts(query, k)

    def find_partners(query: str, k: int = 10, countries: str = "associated", data_class: str = "P") -> list[dict]:
        """Find EU organisations to partner with for a call or idea, via matching Horizon Europe projects. countries is associated, eu or all."""
        return services()[0].partners(query, k, countries)

    def find_calls(query: str, k: int = 10, status: str = "open", data_class: str = "P") -> list[dict]:
        """Find Horizon Europe call topics for an idea. status is open, forthcoming or all."""
        return services()[0].calls(query, k, status)

    def get_call(call_id: str, data_class: str = "P") -> dict | None:
        """Get one call topic by id, with its actions, parts and call title; null if there is none."""
        return services()[0].call(call_id)

    def check_consortium(members: list[dict], action: str = "", data_class: str = "P") -> dict:
        """Check a consortium against the Horizon Europe rule for an action (e.g. HORIZON-RIA). members are objects with a country code each."""
        return eligibility(members, action)

    def draft_brief(call_id: str, partner_ids: list[str] | None = None, home: dict | None = None,
                    data_class: str = "P") -> dict:
        """Draft a citation-checked consortium brief for a call from the local model, always for a person to review. partner_ids picks from the partners found for the call (all if empty); home is {"name", "country"} (default Simon Fraser University, CA)."""
        home = home or {"name": "Simon Fraser University", "country": "CA"}
        research_search = services()[0]
        call = research_search.call(call_id)
        if not call:
            raise ValueError(f"no such call topic: {call_id}")
        found = research_search.partners(f"{call['title']}. {call.get('call_title') or ''}", 12, "associated",
                                         home=home["country"])
        chosen = [p for p in found if not partner_ids or p["id"] in partner_ids]
        actions = call.get("actions") or []
        check = eligibility(chosen + [{"country": home["country"]}], actions[0] if actions else "", call.get("parts") or [])
        return {"call": call, "home": home, "partners": chosen, "eligibility": check,
                "brief": brief(call, chosen, home, data_class)}

    def search_collections(query: str, k: int = 12, data_class: str = "P") -> dict:
        """Search the harvested open collections (Europeana): pictures and texts, ranked separately, each with its rights and citation."""
        found = services()[1]
        return {"pictures": [c.public() for c in found.pictures(query, k)],
                "texts": [c.public() for c in found.texts(query, max(4, k // 2))]}

    return build_server(
        "campus-ai-research-assistant",
        [find_experts, find_partners, find_calls, get_call, check_consortium, draft_brief, search_collections],
        "Find researchers, EU partners and Horizon Europe calls, check consortia and search open collections. Offline, local models.")


if __name__ == "__main__":
    serve(create_server())
