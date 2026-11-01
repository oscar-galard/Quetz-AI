"""Infrastructure layer: adapters and observability.

This layer implements the application ports and owns all framework integration
(LangChain, LangSmith, tree-sitter, SQLite, subprocess Git), keeping the outer
layers pure.
"""
