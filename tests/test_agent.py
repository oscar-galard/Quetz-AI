import unittest
import os
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, RemoveMessage

from quetz.agent import parse_tool_call_from_text, should_continue, should_approve, build_graph
from quetz.domain.model import ToolCall, Turn

# ---------------------------------------------------------------------------
# Fakes used to mock at the infrastructure container boundary.
# ---------------------------------------------------------------------------


class FakeResult:
    """Duck-typed LLM result consumed by the application use cases."""

    def __init__(self, content="", tool_calls=None, message=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.message = message if message is not None else Turn.assistant(
            content=content,
            tool_calls=tuple(
                ToolCall(tc["name"], tc["args"], tc.get("id") or "")
                for tc in (tool_calls or [])
            ),
        )


class FakeLLM:
    """Implements .invoke and .stream used by the use cases."""

    def __init__(self, invoke=None, stream=None):
        self._invoke = invoke
        self._stream = stream

    def invoke(self, messages):
        if callable(self._invoke):
            return self._invoke(messages)
        return FakeResult()

    def stream(self, messages, *, on_content=None, on_tool_name=None, on_tool_args=None):
        if callable(self._stream):
            return self._stream(messages, on_content=on_content, on_tool_name=on_tool_name, on_tool_args=on_tool_args)
        return FakeResult()


class FakeBinder:
    """Implements bind_tools so a bound LLM is returned."""

    def __init__(self, llm=None):
        self._llm = llm or FakeLLM()

    def bind_tools(self, tools):
        return self._llm


class FakeApprover:
    def __init__(self, decision=None):
        from quetz.application.ports.output import Approval

        self._decision = decision or Approval(status="approved")

    def decide(self, plan):
        return self._decision


class FakeExecutor:
    def __init__(self, content="Result 1"):
        self._content = content

    def execute(self, call):
        from quetz.application.ports.tool_executor import ToolResult

        return ToolResult(content=self._content, tool_call_id=call.id, name=call.name)

    def is_known_tool(self, name):
        return True


def make_container(**overrides):
    from quetz.infrastructure.container import Container

    c = Container()
    c.make_llm = lambda tools=None: overrides.get("llm", FakeLLM())
    c.make_binder = lambda tools: overrides.get("binder", FakeBinder(overrides.get("llm", FakeLLM())))
    c.make_planner_llm = lambda: overrides.get("binder", FakeBinder(overrides.get("llm", FakeLLM())))
    if "executor" in overrides:
        c.executor = overrides["executor"]
    if "approver" in overrides:
        c.approver = overrides["approver"]
    return c


class TestAgentFallbackParser(unittest.TestCase):
    def test_direct_json(self):
        content = '{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})

    def test_markdown_code_block(self):
        content = '```json\n{"name": "write_file", "args": {"file_path": "test.txt", "content": "hello"}}\n```'
        result = parse_tool_call_from_text(content)
        self.assertEqual(result[0]["name"], "write_file")

        content_plain = '```\n{"name": "write_file", "parameters": {"file_path": "test.txt", "content": "hello"}}\n```'
        result_plain = parse_tool_call_from_text(content_plain)
        self.assertEqual(result_plain[0]["name"], "write_file")

    def test_xml_tags(self):
        content = '<tool_call>{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}</tool_call>'
        result = parse_tool_call_from_text(content)
        self.assertEqual(result[0]["name"], "write_file")

    def test_invalid_json_returns_none(self):
        self.assertIsNone(parse_tool_call_from_text("not a json string"))
        self.assertIsNone(parse_tool_call_from_text('{"name": "missing_closing_bracket"'))

    def test_sub_json_extraction(self):
        content = 'Here is the tool call you requested:\n\n{"name": "write_file", "arguments": {"file_path": "hello.txt", "content": "world"}}\n\nLet me know if you need anything else!'
        result = parse_tool_call_from_text(content)
        self.assertEqual(result[0]["name"], "write_file")


class TestAgentSummarizeNode(unittest.TestCase):
    def test_summarize_node_purges_messages(self):
        from quetz.infrastructure.graph.nodes import summarize_node

        c = make_container(llm=FakeLLM(invoke=lambda msgs: FakeResult(content="Implementation summary of activities.")))

        messages = [
            HumanMessage(content="User task", id="msg1"),
            AIMessage(content="Proposed plan", id="msg2"),
            HumanMessage(content="Step 1", id="msg3"),
            AIMessage(content="Calling edit_file", id="msg4"),
            ToolMessage(content="Success", tool_call_id="tc1", id="msg5"),
            AIMessage(content="I edited the file", id="msg6"),
        ]
        state = {
            "task": "Test task", "plan": "Test plan", "messages": messages,
            "iteration": 1, "review_feedback": "", "is_approved": False, "summary": "",
        }

        result = summarize_node(state, MagicMock(), c)
        self.assertEqual(result["summary"], "Implementation summary of activities.")
        delete_messages = result["messages"]
        self.assertEqual(len(delete_messages), 4)
        self.assertTrue(all(isinstance(m, RemoveMessage) for m in delete_messages))
        self.assertEqual([m.id for m in delete_messages], ["msg1", "msg2", "msg3", "msg4"])


class TestAgentNodes(unittest.TestCase):
    def test_planner_node_runs(self):
        from quetz.infrastructure.graph.nodes import planner_node

        llm = FakeLLM(invoke=lambda msgs: FakeResult(content="# PROPOSED PLAN\nThis is a plan of more than thirty characters."))
        c = make_container(llm=llm, approver=FakeApprover(), executor=FakeExecutor())

        state = {
            "task": "Test task", "plan": "", "messages": [],
            "iteration": 0, "review_feedback": "", "is_approved": False, "summary": "",
        }
        result = planner_node(state, MagicMock(), c)
        self.assertEqual(result["plan"], "# PROPOSED PLAN\nThis is a plan of more than thirty characters.")

    def test_reviewer_node_runs(self):
        from quetz.infrastructure.graph.nodes import reviewer_node

        llm = FakeLLM(invoke=lambda msgs: FakeResult(content="APPROVED"))
        c = make_container(llm=llm)

        state = {
            "task": "Test task", "plan": "Test plan",
            "messages": [HumanMessage(content="task"), AIMessage(content="response")],
            "iteration": 1, "review_feedback": "", "is_approved": False, "summary": "",
        }
        result = reviewer_node(state, MagicMock(), c)
        self.assertTrue(result["is_approved"])
        self.assertEqual(result["review_feedback"], "")

    def test_coder_node_runs(self):
        from quetz.infrastructure.graph.nodes import coder_node

        def _stream(msgs, *, on_content=None, on_tool_name=None, on_tool_args=None):
            if on_content:
                on_content("Streaming chunk content")
                on_content(")")
                on_content("\n")
            return FakeResult(content="Streaming chunk content")

        c = make_container(binder=FakeBinder(FakeLLM(stream=_stream)))

        state = {
            "task": "Test task", "plan": "Test plan",
            "messages": [HumanMessage(content="task")],
            "iteration": 1, "review_feedback": "", "is_approved": False, "summary": "",
        }
        result = coder_node(state, MagicMock(), c)
        self.assertEqual(result["iteration"], 2)
        self.assertEqual(len(result["messages"]), 1)


class TestAgentLLMSelection(unittest.TestCase):
    @patch("langchain_ollama.ChatOllama")
    @patch("quetz.infrastructure.llm.factory.q_config")
    def test_build_base_chat_model_local(self, mock_q_config, mock_chat_ollama):
        mock_q_config.MODE = "local"
        mock_q_config.MODEL_NAME = "local-model"
        from quetz.infrastructure.llm.factory import build_base_chat_model

        build_base_chat_model()
        mock_chat_ollama.assert_called_once_with(model="local-model", temperature=0.0)

    @patch("langchain_openai.ChatOpenAI")
    @patch("quetz.infrastructure.llm.factory.q_config")
    def test_build_base_chat_model_cloud(self, mock_q_config, mock_chat_openai):
        mock_q_config.MODE = "cloud"
        mock_q_config.MODEL_NAME = "cloud-model"
        mock_q_config.CLOUD_API_KEY = "test-key"
        mock_q_config.CLOUD_BASE_URL = "https://api.test.com"
        from quetz.infrastructure.llm.factory import build_base_chat_model

        build_base_chat_model()
        mock_chat_openai.assert_called_once_with(
            model="cloud-model", api_key="test-key", base_url="https://api.test.com", temperature=0.0
        )


class TestAgentToolsNode(unittest.TestCase):
    @patch("quetz.infrastructure.tools.adapter.read_tool_map", new_callable=dict)
    @patch("quetz.infrastructure.tools.adapter.tool_map", new_callable=dict)
    def test_tools_node_parallel(self, mock_tool_map, mock_read_tool_map):
        from quetz.infrastructure.graph.nodes import tools_node

        mock_tool_1 = MagicMock()
        mock_tool_1.invoke.return_value = "Result 1"
        mock_tool_2 = MagicMock()
        mock_tool_2.invoke.return_value = "Result 2"
        mock_tool_map["tool_1"] = mock_tool_1
        mock_tool_map["tool_2"] = mock_tool_2

        from quetz.infrastructure.container import Container

        c = Container()

        last_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "tool_1", "args": {"arg1": "val1"}, "id": "call_1", "type": "tool_call"},
                {"name": "tool_2", "args": {"arg2": "val2"}, "id": "call_2", "type": "tool_call"},
            ],
        )
        state = {"messages": [last_msg]}

        result = tools_node(state, MagicMock(), c)
        self.assertEqual(len(result["messages"]), 2)
        msg1, msg2 = result["messages"]
        self.assertTrue(isinstance(msg1, ToolMessage))
        self.assertEqual(msg1.content, "Result 1")
        self.assertEqual(msg1.tool_call_id, "call_1")
        self.assertEqual(msg1.name, "tool_1")
        self.assertTrue(isinstance(msg2, ToolMessage))
        self.assertEqual(msg2.content, "Result 2")
        self.assertEqual(msg2.tool_call_id, "call_2")
        self.assertEqual(msg2.name, "tool_2")


class TestAgentDebugMode(unittest.TestCase):
    def test_debug_research_node_runs(self):
        from quetz.infrastructure.graph.nodes import debug_research_node

        class ResearchLLM(FakeLLM):
            def __init__(self):
                super().__init__()
                self.calls = 0
                self._invoke = self._step

            def _step(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return FakeResult(
                        tool_calls=[{"name": "search", "args": {"pattern": "reviewer"}, "id": "call_1", "type": "tool_call"}]
                    )
                return FakeResult(content="Research finished. Located quetz/agent.py.")

        c = make_container(
            binder=FakeBinder(ResearchLLM()),
            executor=FakeExecutor(content="line 10: reviewer_node"),
        )

        state = {"task": "Review the reviewer node in agent.py", "messages": []}
        result = debug_research_node(state, MagicMock(), c)

        from quetz.infrastructure.codec import langchain_to_turns

        turns = langchain_to_turns(result["messages"])
        self.assertEqual(len(turns), 5)
        self.assertEqual(turns[-1].content, "Research finished. Located quetz/agent.py.")

    def test_debug_reporter_node_runs(self):
        from quetz.infrastructure.graph.nodes import debug_reporter_node

        llm = FakeLLM(invoke=lambda msgs: FakeResult(content="# Quetz-AI Report\nThis is a report."))
        report_path = "./quetz_report.md"
        if os.path.exists(report_path):
            os.remove(report_path)

        class DummyWriter:
            def write(self, filename, content):
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"✅ wrote {filename}"

        c = make_container(llm=llm)
        c.report_writer = DummyWriter()

        state = {
            "task": "Review the reviewer node in agent.py",
            "messages": [HumanMessage(content="Review the reviewer node in agent.py")],
        }
        result = debug_reporter_node(state, MagicMock(), c)
        self.assertIn("# Quetz-AI Report", result["summary"])
        self.assertTrue(os.path.isfile(report_path))
        if os.path.exists(report_path):
            os.remove(report_path)

    @patch("quetz.infrastructure.graph.builder.q_config")
    def test_build_graph_debug_mode_toggling(self, mock_q_config):
        # 1. Debug mode active
        mock_q_config.DEBUG_MODE = True
        compiled_debug = build_graph()
        debug_nodes = compiled_debug.get_graph().nodes
        self.assertIn("debug_researcher", debug_nodes)
        self.assertIn("debug_reporter", debug_nodes)
        self.assertNotIn("planner", debug_nodes)
        self.assertNotIn("coder", debug_nodes)

        # 2. Normal coding mode
        mock_q_config.DEBUG_MODE = False
        compiled_normal = build_graph()
        normal_nodes = compiled_normal.get_graph().nodes
        self.assertNotIn("debug_researcher", normal_nodes)
        self.assertNotIn("debug_reporter", normal_nodes)
        self.assertIn("planner", normal_nodes)
        self.assertIn("coder", normal_nodes)


class TestAgentReviewerDisabling(unittest.TestCase):
    @patch("quetz.agent.q_config")
    def test_should_continue_skips_reviewer(self, mock_q_config):
        mock_q_config.NO_REVIEWER = True
        mock_q_config.MAX_ITERATIONS = 5

        state_no_tools = {"messages": [AIMessage(content="Task completed successfully.")], "iteration": 1}
        self.assertEqual(should_continue(state_no_tools), "finish")

        state_with_tools = {
            "messages": [AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": "a.txt"}, "id": "1"}])],
            "iteration": 1,
        }
        self.assertEqual(should_continue(state_with_tools), "tools")

    @patch("quetz.agent.q_config")
    def test_should_continue_uses_reviewer_by_default(self, mock_q_config):
        mock_q_config.NO_REVIEWER = False
        mock_q_config.MAX_ITERATIONS = 5
        state = {"messages": [AIMessage(content="Task completed successfully.")], "iteration": 1}
        self.assertEqual(should_continue(state), "reviewer")


class TestReviewerParsing(unittest.TestCase):
    def _review(self, content):
        from quetz.application.use_cases.reviewer import ReviewUseCase

        llm = FakeLLM(invoke=lambda msgs: FakeResult(content=content))
        uc = ReviewUseCase(llm=llm)
        return uc.execute(task="t", plan="p", action_log="a")

    def test_first_line_approved(self):
        self.assertTrue(self._review("APPROVED").approved)

    def test_approved_on_final_line(self):
        # Local models often answer in prose then close with APPROVED.
        fb = self._review(
            "The implementation follows Unix conventions.\n\nAPPROVED"
        )
        self.assertTrue(fb.approved)

    def test_approved_with_checkmark_line(self):
        self.assertTrue(self._review("✅ APPROVED").approved)

    def test_rejected_marker(self):
        fb = self._review("REJECTED: Missing error handling")
        self.assertFalse(fb.approved)
        self.assertEqual(fb.reasons, "Missing error handling")

    def test_negative_approval(self):
        fb = self._review("The work is NOT APPROVED yet.")
        self.assertFalse(fb.approved)

    def test_garbage_short_response_rejected(self):
        # Bare token / junk should not terminate the task as approved.
        self.assertFalse(self._review("a").approved)
        self.assertFalse(self._review(": 2024-05-21 16:27:29.843000").approved)

    def test_plan_header_echo_not_treated_as_approval(self):
        # The model re-echoing the plan header must not count as a verdict.
        fb = self._review("I could not finish. APPROVED ACTION PLAN was provided but not met.")
        self.assertFalse(fb.approved)


if __name__ == "__main__":
    unittest.main()
