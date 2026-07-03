"""Graph structure + entry routing. No LLM key required."""


def test_graph_compiles():
    from graph.agent import agentic_ai
    assert agentic_ai is not None


def test_entry_router_picks_fast_path_for_trivial_ask():
    from graph.edges import entry_router

    state = {"question": "how many rows are there?", "dataset_meta": {"columns": []}}
    assert entry_router(state) == "generate_code"


def test_entry_router_plans_for_grouped_ask():
    from graph.edges import entry_router

    state = {"question": "what is total revenue by region?", "dataset_meta": {"columns": []}}
    assert entry_router(state) == "plan"


def test_after_verify_retries_then_gives_up():
    from graph.edges import after_verify
    from config.settings import get_settings

    max_retries = get_settings().max_retries
    failing = {
        "verification": {"passed": False},
        "execution_result": {"error": "boom"},
    }

    # below the cap → retry
    assert after_verify({**failing, "retry_count": 0}) == "generate_code"
    # at/above the cap → give up and answer (low_confidence set in verify)
    assert after_verify({**failing, "retry_count": max_retries}) == "answer"


def test_after_verify_passes_to_answer_on_success():
    from graph.edges import after_verify

    ok_state = {"verification": {"passed": True}, "execution_result": {"error": None}}
    assert after_verify(ok_state) == "answer"
