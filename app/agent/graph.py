from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import (
    profiler,
    router,
    code_writer,
    code_executor,
    result_interpreter,
    chart_generator,
    response_composer,
    error_handler,
)


# --- Conditional edge functions ---

def route_after_router(state: AgentState) -> str:
    """After router decides, go to code_writer or skip straight to composer."""
    if state.route == "reasoning":
        return "response_composer"
    return "code_writer"


def route_after_executor(state: AgentState) -> str:
    """After execution, retry on failure or move to interpretation on success."""
    if state.execution_error and state.retry_count < 3:
        return "error_handler"
    return "result_interpreter"


def route_after_interpreter(state: AgentState) -> str:
    """Route after result_interpreter based on route type."""
    if state.route in ["hybrid", "chart"]:
        return "chart_generator"
    return "response_composer"


def route_after_profiler(state: AgentState) -> str:
    """After profiling, if this was an upload (sentinel message), end. Otherwise route normally."""
    if state.current_user_message == "__profile__":
        return END
    return "router"


# --- Graph definition ---

def build_graph():
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("profiler", profiler.run)
    graph.add_node("router", router.run)
    graph.add_node("code_writer", code_writer.run)
    graph.add_node("code_executor", code_executor.run)
    graph.add_node("result_interpreter", result_interpreter.run)
    graph.add_node("error_handler", error_handler.run)
    graph.add_node("chart_generator", chart_generator.run)
    graph.add_node("response_composer", response_composer.run)

    # Entry point
    graph.set_entry_point("profiler")

    # Edges
    graph.add_conditional_edges("profiler", route_after_profiler)
    graph.add_conditional_edges("router", route_after_router)
    graph.add_edge("code_writer", "code_executor")
    graph.add_conditional_edges("code_executor", route_after_executor)
    graph.add_edge("error_handler", "code_writer")
    graph.add_conditional_edges("result_interpreter", route_after_interpreter)
    graph.add_edge("chart_generator", "response_composer")
    graph.add_edge("response_composer", END)

    return graph.compile()


agent = build_graph()

