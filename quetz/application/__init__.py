"""Application layer: ports (interface contracts) and use cases.

The application package is framework-agnostic. It imports only the domain
layer and Python stdlib — never langchain, langgraph, or langsmith. Concrete
adapters implementing these ports live in ``quetz.infrastructure``.
"""
