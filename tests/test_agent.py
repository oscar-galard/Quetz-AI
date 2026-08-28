import unittest
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
    @patch("quetz.agent.ChatOllama")
    def test_summarize_node_purges_messages(self, mock_chat_ollama):
        # Setup mock response from LLM
        mock_llm_instance = MagicMock()
        mock_chat_ollama.return_value = mock_llm_instance
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
        mock_chat_ollama.assert_called_once()
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
    @patch("quetz.agent.ChatOllama")
    @patch("quetz.agent.q_config")
    def test_planner_node_runs(self, mock_q_config, mock_chat_ollama):
        mock_q_config.MODEL_NAME = "test-model"
        mock_q_config.INTERACTIVE_MODE = False
        mock_llm_instance = MagicMock()
        mock_chat_ollama.return_value = mock_llm_instance
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

    @patch("quetz.agent.ChatOllama")
    @patch("quetz.agent.q_config")
    def test_reviewer_node_runs(self, mock_q_config, mock_chat_ollama):
        mock_q_config.MODEL_NAME = "test-model"
        mock_llm_instance = MagicMock()
        mock_chat_ollama.return_value = mock_llm_instance
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

if __name__ == "__main__":
    unittest.main()
