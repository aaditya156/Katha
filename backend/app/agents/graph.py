from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from app.agents.bible_updater import bible_updater_node
from app.agents.critic import critic_node
from app.agents.localizer import localizer_node
from app.agents.planner import planner_node
from app.agents.router import should_revise
from app.agents.state import KathaEpisodeState
from app.agents.voice_caster import voice_caster_node
from app.agents.writer import writer_node
from app.providers.base import BaseLLMProvider


def create_katha_graph(
    llm: BaseLLMProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """Construct and compile the cyclical LangGraph episodic pipeline for Katha Studio."""
    workflow = StateGraph(KathaEpisodeState)

    # Wrap agent nodes with injected LLM provider
    async def _planner(state: KathaEpisodeState) -> dict[str, Any]:
        return await planner_node(state, llm)

    async def _writer(state: KathaEpisodeState) -> dict[str, Any]:
        return await writer_node(state, llm)

    async def _critic(state: KathaEpisodeState) -> dict[str, Any]:
        return await critic_node(state, llm)

    async def _localizer(state: KathaEpisodeState) -> dict[str, Any]:
        return await localizer_node(state, llm)

    async def _voice_caster(state: KathaEpisodeState) -> dict[str, Any]:
        return await voice_caster_node(state, llm)

    async def _bible_updater(state: KathaEpisodeState) -> dict[str, Any]:
        return await bible_updater_node(state, llm)

    # Register Nodes
    workflow.add_node("planner", _planner)
    workflow.add_node("writer", _writer)
    workflow.add_node("critic", _critic)
    workflow.add_node("localizer", _localizer)
    workflow.add_node("voice_caster", _voice_caster)
    workflow.add_node("bible_updater", _bible_updater)

    # Standard Transitions
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "writer")
    workflow.add_edge("writer", "critic")

    # Conditional Revision Edge after Critic (Max 2 Revisions)
    workflow.add_conditional_edges(
        "critic",
        should_revise,
        {
            "writer": "writer",
            "localizer": "localizer",
            "failed": END,
        },
    )

    workflow.add_edge("localizer", "voice_caster")
    workflow.add_edge("voice_caster", "bible_updater")
    workflow.add_edge("bible_updater", END)

    # Compile with checkpointer for pause/resume and fault tolerance
    return workflow.compile(checkpointer=checkpointer)
