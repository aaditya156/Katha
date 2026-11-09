import logging
from app.agents.state import KathaEpisodeState

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2
PASSING_SCORE = 7.5


def should_revise(state: KathaEpisodeState) -> str:
    """Conditional Edge after Critic: Decides whether to revise failing scenes or proceed to localization.

    Loop Invariant:
    - Maximum 2 revision cycles are allowed.
    - If critique score >= 7.5 and no failing scenes remain: proceeds to 'localizer'.
    - If revision_count >= 2: terminates revision cycle and proceeds to 'localizer'.
    - Otherwise: loops back to 'writer' targeting ONLY failing scenes.
    """
    errors = state.get("errors", [])
    if any(not err.get("recoverable", True) if isinstance(err, dict) else not err.recoverable for err in errors):
        logger.error("Unrecoverable error encountered in pipeline state; aborting loop.")
        return "failed"

    critique = state.get("current_critique")
    critic_score = state.get("critic_score", 0.0)
    revision_count = state.get("revision_count", 0)
    failing_scenes = state.get("failing_scenes", [])

    is_passed = False
    if critique:
        is_passed = (
            critique.passed
            and critic_score >= PASSING_SCORE
            and len(failing_scenes) == 0
        )

    logger.info(
        f"Route check after Critic: Score={critic_score:.1f}, Passed={is_passed}, "
        f"FailingScenes={failing_scenes}, RevisionCount={revision_count}/{MAX_REVISIONS}"
    )

    if is_passed:
        logger.info("Script meets dramatic quality threshold (>= 7.5). Advancing to Localizer.")
        return "localizer"

    if revision_count >= MAX_REVISIONS:
        logger.warning(
            f"Maximum revisions ({MAX_REVISIONS}) reached without passing score. "
            "Enforcing loop invariant: Advancing to Localizer."
        )
        return "localizer"

    logger.info(f"Revision {revision_count + 1}/{MAX_REVISIONS} triggered for scenes {failing_scenes}.")
    return "writer"

