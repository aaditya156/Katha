import asyncio
import json
import pytest
from langgraph.checkpoint.memory import MemorySaver
from app.agents.graph import create_katha_graph
from app.agents.router import MAX_REVISIONS, should_revise
from app.agents.runner import launch_background_generation, pipeline_service
from app.agents.state import KathaEpisodeState
from app.core.events import event_hub
from app.providers.mock import MockLLMProvider
from app.schemas.script import CritiqueReport, SceneCritique


@pytest.fixture
def initial_test_state() -> KathaEpisodeState:
    return {
        "series_id": "series_test_123",
        "episode_id": "ep_test_123",
        "episode_number": 1,
        "premise": "A late-night radio DJ receives a broadcast claiming to be from 1947.",
        "target_language": "hinglish",
        "target_duration_minutes": 5,
        "genre": "thriller",
        "characters_hint": ["Kabir", "The Caller"],
        "revision_count": 0,
        "critique_history": [],
        "errors": [],
        "failing_scenes": [],
        "status": "INITIALIZED",
        "current_node": "start",
        "simulation_flags": {},
    }


@pytest.mark.asyncio
async def test_full_langgraph_workflow_success(initial_test_state: KathaEpisodeState) -> None:
    """Validate end-to-end execution of Planner -> Writer -> Critic -> Localizer -> Voice Caster -> Bible Updater."""
    # Critic passes all scenes on first pass
    llm = MockLLMProvider(critic_failing_scenes=[])
    checkpointer = MemorySaver()
    graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test_thread_success"}}
    final_state = await graph.ainvoke(initial_test_state, config=config)

    # 1. Planner output
    assert final_state["outline"] is not None
    assert final_state["outline"].title != ""
    assert len(final_state["outline"].scenes) >= 1

    # 2. Writer output
    assert final_state["raw_script"] is not None
    assert len(final_state["raw_script"].scenes) >= 1

    # 3. Critic output
    assert final_state["current_critique"] is not None
    assert final_state["current_critique"].passed is True
    assert final_state["critic_score"] >= 7.5
    assert final_state["revision_count"] == 0

    # 4. Localizer output
    assert final_state["localized_script"] is not None
    assert final_state["localized_script"].target_language == "hinglish"

    # 5. Voice Caster output
    assert final_state["cast_script"] is not None
    assert len(final_state["cast_script"].cast) >= 1
    # Check that lines have voice_ids
    assert final_state["cast_script"].scenes[0].lines[0].voice_id is not None

    # 6. Bible Updater output
    assert final_state["bible_updates"] is not None
    assert final_state["bible_updates"].episode_summary != ""
    assert final_state["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_conditional_revision_loop_rewrites_only_failing_scenes(
    initial_test_state: KathaEpisodeState,
) -> None:
    """Validate that when Critic fails Scene 2, ONLY Scene 2 is rewritten while Scene 1 is preserved."""
    # Initially fail Scene 2
    llm = MockLLMProvider(critic_failing_scenes=[2])
    checkpointer = MemorySaver()
    graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test_thread_revision"}}
    final_state = await graph.ainvoke(initial_test_state, config=config)

    # Revision loop must have been triggered
    assert final_state["revision_count"] >= 1
    assert len(final_state["critique_history"]) >= 1

    # Verify that Scene 1 was preserved from original draft
    scene_1 = final_state["raw_script"].scenes[0]
    assert scene_1.scene_number == 1
    assert scene_1.lines[0].id == "line_1_1"

    # Verify that Scene 2 was rewritten
    scene_2 = final_state["raw_script"].scenes[1]
    assert scene_2.scene_number == 2
    assert "REWRITTEN" in scene_2.heading or scene_2.lines[0].id == "rev_line_2_1"


@pytest.mark.asyncio
async def test_revision_limits_strict_cap_at_two(initial_test_state: KathaEpisodeState) -> None:
    """Validate loop invariant: Critic consistently fails script, but execution terminates at MAX_REVISIONS (2)."""
    # Always fail scenes 1 and 2 with failing score 5.0
    llm = MockLLMProvider(critic_failing_scenes=[1, 2], force_critic_score=5.0)
    checkpointer = MemorySaver()
    graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test_thread_max_revisions"}}
    final_state = await graph.ainvoke(initial_test_state, config=config)

    # Must terminate at max 2 revisions and not loop indefinitely
    assert final_state["revision_count"] == MAX_REVISIONS
    assert final_state["status"] == "COMPLETED"
    assert final_state["localized_script"] is not None


@pytest.mark.asyncio
async def test_forced_mid_run_failure_and_checkpoint_recovery(
    initial_test_state: KathaEpisodeState,
) -> None:
    """Validate that if a mid-run failure occurs at Critic, state is preserved in checkpointer and can resume."""
    checkpointer = MemorySaver()
    thread_id = "test_thread_checkpoint_recovery"
    config = {"configurable": {"thread_id": thread_id}}

    # 1. Run with forced failure at Critic node
    failing_state = dict(initial_test_state)
    failing_state["simulation_flags"] = {"fail_at_node": "critic"}

    llm = MockLLMProvider()
    graph = create_katha_graph(llm=llm, checkpointer=checkpointer)

    with pytest.raises(RuntimeError) as exc_info:
        await graph.ainvoke(failing_state, config=config)
    assert "Simulated forced failure at Critic node" in str(exc_info.value)

    # Verify checkpoint saved state up to Writer node
    checkpoint_state = await checkpointer.aget(config)
    assert checkpoint_state is not None
    saved_channel_values = checkpoint_state.get("channel_values", {})
    assert saved_channel_values.get("outline") is not None
    assert saved_channel_values.get("raw_script") is not None

    # 2. Resume execution from checkpoint with failure flag removed
    resume_state: KathaEpisodeState = {"simulation_flags": {}}
    resumed_final = await graph.ainvoke(resume_state, config=config)

    # Pipeline recovers and completes
    assert resumed_final["status"] == "COMPLETED"
    assert resumed_final["cast_script"] is not None


@pytest.mark.asyncio
async def test_sse_event_stream_delivery() -> None:
    """Validate that Server-Sent Events publish and receive structured lifecycle events."""
    test_episode_id = "sse_test_ep_999"

    async def _subscriber():
        received = []
        async for sse_msg in event_hub.subscribe(test_episode_id):
            received.append(sse_msg)
            if "pipeline_completed" in sse_msg:
                break
        return received

    sub_task = asyncio.create_task(_subscriber())
    await asyncio.sleep(0.05)  # Allow queue attachment

    # Publish events
    await event_hub.publish(
        episode_id=test_episode_id,
        event_type="node_started",
        node="planner",
        payload={"message": "Planning started"},
    )
    await event_hub.publish(
        episode_id=test_episode_id,
        event_type="pipeline_completed",
        payload={"total_lines": 10},
    )

    events = await asyncio.wait_for(sub_task, timeout=2.0)
    assert len(events) >= 2
    assert "data:" in events[0]
    first_event = json.loads(events[0].replace("data: ", "").strip())
    assert first_event["event_type"] == "node_started"
    assert first_event["node"] == "planner"


@pytest.mark.asyncio
async def test_job_idempotency_prevents_duplicate_runs() -> None:
    """Validate that triggering generation for an already running episode does not duplicate tasks."""
    test_ep_id = "idempotent_ep_1"
    llm = MockLLMProvider(delay_seconds=1.0)

    # First launch succeeds
    first_call = launch_background_generation(test_ep_id, llm)
    assert first_call is True

    # Immediate second launch detects in-flight task and returns False
    second_call = launch_background_generation(test_ep_id, llm)
    assert second_call is False
