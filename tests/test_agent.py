import unittest
import os
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, RemoveMessage
from quetz.agent import parse_tool_call_from_text, summarize_node

class TestAgentFallbackParser(unittest.TestCase):
    def test_direct_json(self):
        content = '{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})
        self.assertTrue(result[0]["id"].startswith("fallback_id_"))

    def test_markdown_code_block(self):
        content = '```json\n{"name": "write_file", "args": {"file_path": "test.txt", "content": "hello"}}\n```'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})

        content_plain = '```\n{"name": "write_file", "parameters": {"file_path": "test.txt", "content": "hello"}}\n```'
        result_plain = parse_tool_call_from_text(content_plain)
        self.assertIsNotNone(result_plain)
        self.assertEqual(result_plain[0]["args"], {"file_path": "test.txt", "content": "hello"})

    def test_xml_tags(self):
        content = '<tool_call>{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}</tool_call>'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})

    def test_invalid_json_returns_none(self):
        self.assertIsNone(parse_tool_call_from_text("not a json string"))
        self.assertIsNone(parse_tool_call_from_text('{"name": "missing_closing_bracket"'))

    def test_sub_json_extraction(self):
        content = 'Here is the tool call you requested:\n\n{"name": "write_file", "arguments": {"file_path": "hello.txt", "content": "world"}}\n\nLet me know if you need anything else!'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "hello.txt", "content": "world"})

class TestAgentSummarizeNode(unittest.TestCase):
    @patch("quetz.agent.get_llm_base")
    def test_summarize_node_purges_messages(self, mock_get_llm_base):
        # Setup mock response from LLM
        mock_llm_instance = MagicMock()
        mock_get_llm_base.return_value = mock_llm_instance
        mock_llm_instance.invoke.return_value = AIMessage(content="Implementation summary of activities.")
        
        # Setup initial state with more than 4 messages to trigger summarization
        messages = [
            HumanMessage(content="User task", id="msg1"),
            AIMessage(content="Proposed plan", id="msg2"),
            HumanMessage(content="Step 1", id="msg3"),
            AIMessage(content="Calling edit_file", id="msg4"),
            ToolMessage(content="Success", tool_call_id="tc1", id="msg5"),
            AIMessage(content="I edited the file", id="msg6"),
        ]
        
        state = {
            "task": "Test task",
            "plan": "Test plan",
            "messages": messages,
            "iteration": 1,
            "review_feedback": "",
            "is_approved": False,
            "summary": ""
        }
        
        result = summarize_node(state, MagicMock())
        
        # Verify LLM was invoked
        mock_get_llm_base.assert_called_once()
        mock_llm_instance.invoke.assert_called_once()
        
        # Verify result contains the updated summary
        self.assertEqual(result["summary"], "Implementation summary of activities.")
        
        # Verify result contains RemoveMessage objects for all but the last 2 messages
        delete_messages = result["messages"]
        self.assertEqual(len(delete_messages), 4) # messages[:-2] => msg1, msg2, msg3, msg4
        self.assertTrue(all(isinstance(m, RemoveMessage) for m in delete_messages))
        self.assertEqual(delete_messages[0].id, "msg1")
        self.assertEqual(delete_messages[1].id, "msg2")
        self.assertEqual(delete_messages[2].id, "msg3")
        self.assertEqual(delete_messages[3].id, "msg4")


class TestAgentNodes(unittest.TestCase):
    @patch("quetz.agent.get_llm_base")
    @patch("quetz.agent.q_config")
    def test_planner_node_runs(self, mock_q_config, mock_get_llm_base):
        mock_q_config.MODEL_NAME = "test-model"
        mock_q_config.INTERACTIVE_MODE = False
        mock_llm_instance = MagicMock()
        mock_get_llm_base.return_value = mock_llm_instance
        mock_llm_instance.invoke.return_value = AIMessage(content="# PROPOSED PLAN\nThis is a plan of more than thirty characters.")
        
        state = {
            "task": "Test task",
            "plan": "",
            "messages": [],
            "iteration": 0,
            "review_feedback": "",
            "is_approved": False,
            "summary": ""
        }
        
        from quetz.agent import planner_node
        result = planner_node(state, MagicMock())
        self.assertEqual(result["plan"], "# PROPOSED PLAN\nThis is a plan of more than thirty characters.")

    @patch("quetz.agent.get_llm_base")
    @patch("quetz.agent.q_config")
    def test_reviewer_node_runs(self, mock_q_config, mock_get_llm_base):
        mock_q_config.MODEL_NAME = "test-model"
        mock_llm_instance = MagicMock()
        mock_get_llm_base.return_value = mock_llm_instance
        mock_llm_instance.invoke.return_value = AIMessage(content="APPROVED")
        
        state = {
            "task": "Test task",
            "plan": "Test plan",
            "messages": [HumanMessage(content="task"), AIMessage(content="response")],
            "iteration": 1,
            "review_feedback": "",
            "is_approved": False,
            "summary": ""
        }
        
        from quetz.agent import reviewer_node
        result = reviewer_node(state, MagicMock())
        self.assertTrue(result["is_approved"])
        self.assertEqual(result["review_feedback"], "")

    @patch("quetz.agent.get_llm")
    @patch("quetz.agent.q_config")
    def test_coder_node_runs(self, mock_q_config, mock_get_llm):
        mock_q_config.MAX_ITERATIONS = 5
        mock_q_config.MODEL_NAME = "test-model"
        
        mock_llm_instance = MagicMock()
        mock_get_llm.return_value = mock_llm_instance
        
        mock_chunk = MagicMock()
        mock_chunk.content = "Streaming chunk content"
        mock_chunk.tool_call_chunks = []
        mock_llm_instance.stream.return_value = [mock_chunk]
        
        state = {
            "task": "Test task",
            "plan": "Test plan",
            "messages": [HumanMessage(content="task")],
            "iteration": 1,
            "review_feedback": "",
            "is_approved": False,
            "summary": ""
        }
        
        from quetz.agent import coder_node
        result = coder_node(state, MagicMock())
        self.assertEqual(result["iteration"], 2)
        self.assertEqual(len(result["messages"]), 1)

class TestAgentLLMSelection(unittest.TestCase):
    @patch("quetz.agent.ChatOllama")
    @patch("quetz.agent.q_config")
    def test_get_llm_base_local(self, mock_q_config, mock_chat_ollama):
        mock_q_config.MODE = "local"
        mock_q_config.MODEL_NAME = "local-model"
        
        from quetz.agent import get_llm_base
        get_llm_base()
        
        mock_chat_ollama.assert_called_once_with(model="local-model", temperature=0.0)

    @patch("langchain_openai.ChatOpenAI")
    @patch("quetz.agent.q_config")
    def test_get_llm_base_cloud(self, mock_q_config, mock_chat_openai):
        mock_q_config.MODE = "cloud"
        mock_q_config.MODEL_NAME = "cloud-model"
        mock_q_config.CLOUD_API_KEY = "test-key"
        mock_q_config.CLOUD_BASE_URL = "https://api.test.com"
        
        from quetz.agent import get_llm_base
        get_llm_base()
        
        mock_chat_openai.assert_called_once_with(
            model="cloud-model",
            api_key="test-key",
            base_url="https://api.test.com",
            temperature=0.0
        )

class TestAgentToolsNode(unittest.TestCase):
    @patch("quetz.agent.tool_map", new_callable=dict)
    @patch("quetz.agent.q_config")
    def test_tools_node_parallel(self, mock_q_config, mock_tool_map):
        mock_q_config.INTERACTIVE_MODE = False
        
        mock_tool_1 = MagicMock()
        mock_tool_1.invoke.return_value = "Result 1"
        mock_tool_2 = MagicMock()
        mock_tool_2.invoke.return_value = "Result 2"
        
        mock_tool_map["tool_1"] = mock_tool_1
        mock_tool_map["tool_2"] = mock_tool_2
        
        last_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "tool_1", "args": {"arg1": "val1"}, "id": "call_1", "type": "tool_call"},
                {"name": "tool_2", "args": {"arg2": "val2"}, "id": "call_2", "type": "tool_call"}
            ]
        )
        state = {
            "messages": [last_msg]
        }
        
        from quetz.agent import tools_node
        result = tools_node(state, MagicMock())
        
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
    @patch("quetz.agent.get_llm_base")
    @patch("quetz.agent.q_config")
    def test_debug_research_node_runs(self, mock_q_config, mock_get_llm_base):
        mock_q_config.MODEL_NAME = "test-model"
        mock_q_config.WORKSPACE_DIR = "."
        
        mock_llm_instance = MagicMock()
        mock_get_llm_base.return_value = mock_llm_instance
        
        # Simulating one tool call response, followed by a text response (which stops the loop)
        mock_llm_instance.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"name": "search", "args": {"pattern": "reviewer"}, "id": "call_1", "type": "tool_call"}]),
            AIMessage(content="Research finished. Located quetz/agent.py.")
        ]
        
        # Mocking tool invocation
        mock_search_tool = MagicMock()
        mock_search_tool.invoke.return_value = "line 10: reviewer_node"
        with patch.dict("quetz.agent.read_tool_map", {"search": mock_search_tool}):
            state = {
                "task": "Review the reviewer node in agent.py",
                "messages": []
            }
            
            from quetz.agent import debug_research_node
            result = debug_research_node(state, MagicMock())
            
            self.assertEqual(len(result["messages"]), 5) # system prompt + task, first LLM response, ToolMessage, second LLM response
            self.assertTrue(isinstance(result["messages"][-1], AIMessage))
            self.assertEqual(result["messages"][-1].content, "Research finished. Located quetz/agent.py.")

    @patch("quetz.agent.get_llm_base")
    @patch("quetz.agent.q_config")
    def test_debug_reporter_node_runs(self, mock_q_config, mock_get_llm_base):
        mock_q_config.WORKSPACE_DIR = "."
        
        mock_llm_instance = MagicMock()
        mock_get_llm_base.return_value = mock_llm_instance
        mock_llm_instance.invoke.return_value = AIMessage(content="# Quetz-AI Report\nThis is a beautiful report with a plantuml diagram.")
        
        state = {
            "task": "Review the reviewer node in agent.py",
            "messages": [HumanMessage(content="Review the reviewer node in agent.py")]
        }
        
        # Ensure we delete quetz_report.md if it already exists from previous runs to isolate testing
        report_path = "./quetz_report.md"
        if os.path.exists(report_path):
            os.remove(report_path)
            
        from quetz.agent import debug_reporter_node
        result = debug_reporter_node(state, MagicMock())
        
        self.assertIn("# Quetz-AI Report", result["summary"])
        self.assertTrue(os.path.isfile(report_path))
        
        # Clean up report file after verifying it was created
        if os.path.exists(report_path):
            os.remove(report_path)

    @patch("quetz.agent.q_config")
    def test_build_graph_debug_mode_toggling(self, mock_q_config):
        # 1. Test Debug Mode Active
        mock_q_config.DEBUG_MODE = True
        from quetz.agent import build_graph
        compiled_debug = build_graph()
        debug_nodes = compiled_debug.get_graph().nodes
        self.assertIn("debug_researcher", debug_nodes)
        self.assertIn("debug_reporter", debug_nodes)
        self.assertNotIn("planner", debug_nodes)
        self.assertNotIn("coder", debug_nodes)
        
        # 2. Test Normal Coding Mode Active
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
        
        from quetz.agent import should_continue
        
        # Scenario 1: Last message has no tools (completed task), should skip reviewer and go directly to finish
        state_no_tools = {
            "messages": [AIMessage(content="Task completed successfully.")],
            "iteration": 1
        }
        result_no_tools = should_continue(state_no_tools)
        self.assertEqual(result_no_tools, "finish")
        
        # Scenario 2: Last message has tools, should still go to tools
        state_with_tools = {
            "messages": [AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": "a.txt"}, "id": "1"}])],
            "iteration": 1
        }
        result_with_tools = should_continue(state_with_tools)
        self.assertEqual(result_with_tools, "tools")

    @patch("quetz.agent.q_config")
    def test_should_continue_uses_reviewer_by_default(self, mock_q_config):
        mock_q_config.NO_REVIEWER = False
        mock_q_config.MAX_ITERATIONS = 5
        
        from quetz.agent import should_continue
        state = {
            "messages": [AIMessage(content="Task completed successfully.")],
            "iteration": 1
        }
        result = should_continue(state)
        self.assertEqual(result, "reviewer")

if __name__ == "__main__":
    unittest.main()
