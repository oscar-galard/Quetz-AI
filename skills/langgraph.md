---
skill: langgraph
layer: application
tags: [python, langgraph, langchain, agent, state, graph]
---

## State definition

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    plan: list[str]
    iteration: int
```

Rules:
- State is a `TypedDict` — never a mutable class with hidden behavior.
- Use reducers (`add_messages`, custom sum reducers) for fields that accumulate.
- Keep state JSON-serializable so checkpoints persist cleanly.

## Node design

```python
def plan_node(state: AgentState) -> dict:
    return {"plan": generate_plan(state["messages"])}

def executor_node(state: AgentState) -> dict:
    result = run_next(state["plan"], state["iteration"])
    return {"messages": [AIMessage(content=result)], "iteration": state["iteration"] + 1}
```

Rules:
- Nodes return **partial updates** — never the full state.
- Nodes must be pure given the state — no hidden global reads.
- Keep node functions small; extract helpers.

## Graph construction

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(AgentState)
graph.add_node("plan", plan_node)
graph.add_node("execute", executor_node)
graph.add_edge(START, "plan")
graph.add_conditional_edges("execute", should_continue, {"continue": "execute", "done": END})
app = graph.compile(checkpointer=MemorySaver())
```

Rules:
- Compile once, reuse the `CompiledGraph`.
- Always provide a `checkpointer` in production — `MemorySaver` is only for tests.
- Name nodes explicitly; avoid opaque lambda functions.
