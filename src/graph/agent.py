from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    plan,
    generate_code,
    execute_locally,
    verify,
    answer,
    finalize,
    handle_error,
)
from graph.edges import (
    entry_router,
    after_plan,
    after_generate,
    after_execute,
    after_verify,
)


def _build_graph():
    g = StateGraph(AgentState)
    for name, fn in [
        ("plan", plan),
        ("generate_code", generate_code),
        ("execute_locally", execute_locally),
        ("verify", verify),
        ("answer", answer),
        ("finalize", finalize),
        ("handle_error", handle_error),
    ]:
        g.add_node(name, fn)

    g.set_conditional_entry_point(
        entry_router,
        {"plan": "plan", "generate_code": "generate_code"},
    )
    g.add_conditional_edges(
        "plan", after_plan,
        {"handle_error": "handle_error", "generate_code": "generate_code"},
    )
    g.add_conditional_edges(
        "generate_code", after_generate,
        {"handle_error": "handle_error", "execute_locally": "execute_locally"},
    )
    g.add_conditional_edges(
        "execute_locally", after_execute,
        {"handle_error": "handle_error", "verify": "verify"},
    )
    g.add_conditional_edges(
        "verify", after_verify,
        {"generate_code": "generate_code", "answer": "answer"},
    )
    g.add_edge("answer", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()   # keep the exported name the skeleton uses
