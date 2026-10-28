import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp.client import Client

from campus_ai.core import tracing
from campus_ai.core.mcp import build_server
from campus_ai.course_access import mcp_server as course
from campus_ai.course_access.audit import Issue
from campus_ai.research_assistant import mcp_server as research


def data(result):
    return json.loads(result.content[0].text)


def run(coro):
    return asyncio.run(coro)


async def call(server, name, arguments):
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


async def list_tools(server):
    async with Client(server) as client:
        return (await client.list_tools()).tools


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.dict("os.environ", {"CAMPUS_AI_TRACE_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def traces(self):
        return [json.loads(line) for f in self.dir.glob("*.jsonl") for line in f.read_text().splitlines()]


class RegistrationTests(Base):
    def test_course_access_tools(self):
        tools = {t.name: t for t in run(list_tools(course.create_server()))}
        self.assertEqual(set(tools), {"audit_document", "propose_fixes", "remediate"})
        self.assertIn("WCAG 2.2 AA", tools["audit_document"].description)
        schema = tools["remediate"].input_schema
        self.assertEqual(set(schema["required"]), {"path", "out_dir"})
        self.assertEqual(schema["properties"]["data_class"]["default"], "I")
        self.assertEqual(schema["properties"]["approve_all"]["default"], False)

    def test_research_assistant_tools_list_without_services(self):
        with mock.patch("campus_ai.core.embed.get_embedder", side_effect=AssertionError("built at list time")):
            tools = {t.name: t for t in run(list_tools(research.create_server()))}
        self.assertEqual(set(tools), {"find_experts", "find_partners", "find_calls", "get_call", "check_consortium",
                                      "draft_brief", "search_collections"})
        self.assertIn("researchers", tools["find_experts"].description)
        schema = tools["find_partners"].input_schema
        self.assertEqual(schema["required"], ["query"])
        self.assertEqual(schema["properties"]["countries"]["default"], "associated")
        self.assertTrue(all(t.input_schema["properties"]["data_class"]["default"] == "P" for t in tools.values()))

    def test_tool_needs_data_class(self):
        def no_class(path: str) -> dict:
            """x"""
        with self.assertRaises(TypeError):
            build_server("x", [no_class])


class CourseAccessTests(Base):
    def test_audit_document(self):
        with mock.patch.object(course, "parse") as parse, \
                mock.patch.object(course.audit_module, "audit", return_value=[]) as audit, \
                mock.patch.object(course.audit_module, "report_dict", return_value={"issue_count": 0}) as report:
            result = run(call(course.create_server(), "audit_document", {"path": "/docs/week4.docx"}))
        parse.assert_called_once_with(Path("/docs/week4.docx"))
        audit.assert_called_once_with(parse.return_value)
        report.assert_called_once_with(parse.return_value, [], "week4.docx")
        self.assertEqual(data(result), {"issue_count": 0})

    def test_propose_fixes_passes_the_data_class(self):
        with mock.patch.object(course, "parse"), mock.patch.object(course.audit_module, "audit", return_value=[]), \
                mock.patch.object(course.workers, "propose_fixes", return_value=[]) as fixes, \
                mock.patch.object(course.alt_text, "propose", return_value=[]) as alts:
            run(call(course.create_server(), "propose_fixes", {"path": "a.docx", "with_alt_text": True, "data_class": "S"}))
        self.assertEqual(fixes.call_args.kwargs["data_class"], "S")
        self.assertEqual(alts.call_args.kwargs["data_class"], "S")

    def test_remediate(self):
        before = [Issue("image-missing-alt", "1.1.1", "m", "author")]
        outcome = {"before": before, "after": [], "applied": 2, "waiting": 1, "notes": ["n"],
                   "files": [Path("/out/a.docx"), Path("/out/a.html")]}
        with mock.patch.object(course, "run_remediate", return_value=outcome) as remediate:
            result = run(call(course.create_server(), "remediate", {"path": "/in/a.docx", "out_dir": "/out", "approve_all": True}))
        remediate.assert_called_once_with(Path("/in/a.docx"), Path("/out"), data_class="I", with_alt_text=False, approve_all=True)
        payload = data(result)
        self.assertEqual((payload["before"], payload["after"], payload["fixed"], payload["applied"]), (1, 0, 1, 2))
        self.assertEqual(len(payload["files"]), 5)
        self.assertTrue(payload["files"][0].endswith("a.docx"))

    def test_class_r_is_refused_and_traced(self):
        with mock.patch.object(course, "parse") as parse:
            result = run(call(course.create_server(), "audit_document", {"path": "a.docx", "data_class": "R"}))
        self.assertTrue(result.is_error)
        parse.assert_not_called()
        self.assertEqual([(t["tool"], t["outcome"]) for t in self.traces()], [("audit_document", "refused")])


class ResearchAssistantTests(Base):
    def server(self):
        self.graph, self.collections = mock.Mock(), mock.Mock()
        return research.create_server(self.graph, self.collections)

    def test_search_tools_pass_arguments(self):
        server = self.server()
        self.graph.experts.return_value = [{"id": "r1"}]
        self.graph.partners.return_value = [{"id": "o1"}]
        self.graph.calls.return_value = [{"id": "c1"}]
        self.graph.call.return_value = {"id": "c1", "identifier": "X"}
        run(call(server, "find_experts", {"query": "smoke", "k": 3}))
        run(call(server, "find_partners", {"query": "solar", "k": 4, "countries": "eu"}))
        run(call(server, "find_calls", {"query": "coast", "k": 2, "status": "all"}))
        result = run(call(server, "get_call", {"call_id": "c1"}))
        self.graph.experts.assert_called_once_with("smoke", 3)
        self.graph.partners.assert_called_once_with("solar", 4, "eu")
        self.graph.calls.assert_called_once_with("coast", 2, "all")
        self.graph.call.assert_called_once_with("c1")
        self.assertEqual(data(result), {"id": "c1", "identifier": "X"})

    def test_check_consortium(self):
        with mock.patch.object(research, "eligibility", return_value={"ok": True}) as check:
            result = run(call(self.server(), "check_consortium", {"members": [{"country": "DE"}], "action": "HORIZON-RIA"}))
        check.assert_called_once_with([{"country": "DE"}], "HORIZON-RIA")
        self.assertEqual(data(result), {"ok": True})

    def test_draft_brief(self):
        server = self.server()
        self.graph.call.return_value = {"id": "c1", "title": "T", "call_title": "C", "actions": ["HORIZON-RIA"], "parts": []}
        self.graph.partners.return_value = [{"id": "o1", "country": "DE"}, {"id": "o2", "country": "FR"}]
        with mock.patch.object(research, "brief", return_value={"brief": "text"}) as brief:
            result = run(call(server, "draft_brief", {"call_id": "c1", "partner_ids": ["o2"]}))
        chosen = brief.call_args.args[1]
        self.assertEqual([p["id"] for p in chosen], ["o2"])
        self.assertEqual(brief.call_args.args[3], "P")
        self.assertEqual(data(result)["brief"], {"brief": "text"})

    def test_search_collections(self):
        server = self.server()
        card = mock.Mock(public=lambda: {"id": "i1"})
        self.collections.pictures.return_value = [card]
        self.collections.texts.return_value = []
        result = run(call(server, "search_collections", {"query": "salmon", "k": 8}))
        self.collections.pictures.assert_called_once_with("salmon", 8)
        self.collections.texts.assert_called_once_with("salmon", 4)
        self.assertEqual(data(result), {"pictures": [{"id": "i1"}], "texts": []})

    def test_trace_has_metadata_only(self):
        server = self.server()
        self.graph.experts.return_value = []
        run(call(server, "find_experts", {"query": "secret topic words"}))
        (entry,) = self.traces()
        self.assertEqual((entry["tool"], entry["data_class"], entry["outcome"]), ("find_experts", "P", "ok"))
        self.assertIn("latency_ms", entry)
        self.assertNotIn("secret", json.dumps(entry))

    def test_class_r_refused(self):
        server = self.server()
        result = run(call(server, "find_experts", {"query": "x", "data_class": "R"}))
        self.assertTrue(result.is_error)
        self.graph.experts.assert_not_called()

    def test_tool_error_is_traced(self):
        server = self.server()
        self.graph.calls.side_effect = RuntimeError("secret detail")
        result = run(call(server, "find_calls", {"query": "x"}))
        self.assertTrue(result.is_error)
        (entry,) = self.traces()
        self.assertEqual((entry["outcome"], entry["error"]), ("error", "RuntimeError"))


class TracedTests(unittest.TestCase):
    def test_keeps_signature_and_docstring(self):
        import inspect
        from campus_ai.core.mcp import traced
        wrapped = traced(course.audit_document)
        self.assertEqual(inspect.signature(wrapped), inspect.signature(course.audit_document))
        self.assertEqual(wrapped.__doc__, course.audit_document.__doc__)


if __name__ == "__main__":
    unittest.main()
