import unittest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from quetz.cli import planning_phase
from quetz import config

class TestPlanningPhase(unittest.TestCase):
    def setUp(self):
        # Save interactive mode setting
        self.original_interactive = config.INTERACTIVE_MODE
        config.INTERACTIVE_MODE = True

    def tearDown(self):
        # Restore interactive mode
        config.INTERACTIVE_MODE = self.original_interactive

    @patch("quetz.agent.get_llm")
    @patch("builtins.input", return_value="n")
    @patch("builtins.print")
    def test_planning_phase_self_correction(self, mock_print, mock_input, mock_get_llm):
        # Mock LLM behavior
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Configure LLM to return ":" first, then a valid plan
        mock_response_1 = AIMessage(content=":")
        mock_response_2 = AIMessage(content="# PROPOSED PLAN\n1. Do task A\n2. Do task B\nThis is a valid plan of length greater than 30 characters.")
        
        # Save copies of invoke arguments to handle mutable list reference assertions
        invoked_messages = []
        def invoke_side_effect(messages):
            invoked_messages.append(list(messages))
            if len(invoked_messages) == 1:
                return mock_response_1
            return mock_response_2
        mock_llm.invoke.side_effect = invoke_side_effect
        
        # We expect SystemExit because input is mocked to return "n" (abort)
        with self.assertRaises(SystemExit) as cm:
            planning_phase("Create a website")
            
        # Verify exit code is 0 (successful abort)
        self.assertEqual(cm.exception.code, 0)
        
        # Verify LLM was called twice
        self.assertEqual(mock_llm.invoke.call_count, 2)
        
        # Check that the first invoke call was with original messages
        self.assertEqual(len(invoked_messages[0]), 2)
        self.assertIsInstance(invoked_messages[0][0], SystemMessage)
        self.assertIsInstance(invoked_messages[0][1], HumanMessage)
        self.assertEqual(invoked_messages[0][1].content, "Create a website")
        
        # Check that second invoke call included correction messages
        self.assertEqual(len(invoked_messages[1]), 4)
        self.assertEqual(invoked_messages[1][2].content, ":")
        self.assertIn("The plan you formulated is too short", invoked_messages[1][3].content)

    @patch("quetz.agent.get_llm")
    @patch("builtins.input", return_value="y")
    @patch("builtins.print")
    def test_planning_phase_approved_history_clean(self, mock_print, mock_input, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Return ":" first, then a valid plan
        mock_response_1 = AIMessage(content=":")
        mock_response_2 = AIMessage(content="# PROPOSED PLAN\nThis is a very long and detailed valid plan.")
        mock_llm.invoke.side_effect = [mock_response_1, mock_response_2]
        
        result_messages = planning_phase("Test task")
        
        # Verify returned messages has length 3 (HumanMessage task, AIMessage plan, HumanMessage approved)
        # (excluding SystemMessage which is filtered out in planning_phase)
        self.assertEqual(len(result_messages), 3)
        self.assertEqual(result_messages[0].content, "Test task")
        self.assertEqual(result_messages[1].content, "# PROPOSED PLAN\nThis is a very long and detailed valid plan.")
        self.assertEqual(result_messages[2].content, "Plan approved. Please proceed with the implementation using the available tools.")

class TestBanner(unittest.TestCase):
    @patch("builtins.print")
    def test_print_banner(self, mock_print):
        from quetz.cli import print_banner, BANNER
        print_banner()
        mock_print.assert_called_once_with(BANNER)

if __name__ == "__main__":
    unittest.main()
