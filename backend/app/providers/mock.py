import asyncio
from typing import Any, TypeVar
from pydantic import BaseModel
from app.core.exceptions import LLMProviderError, SchemaValidationError
from app.providers.base import BaseLLMProvider
from app.schemas.outline import EpisodeOutline
from app.schemas.script import (
    BibleUpdatePayload,
    CastScript,
    CharacterLoreUpdate,
    CritiqueReport,
    LocalizedLine,
    LocalizedScene,
    LocalizedScript,
    SceneCritique,
    Script,
    ScriptLine,
    ScriptScene,
    VoiceAssignment,
)
from app.schemas.story_bible import (
    CharacterFact,
    EventFact,
    LocationFact,
    PlotThreadFact,
    RelationshipFact,
    StoryBibleExtraction,
)
from app.schemas.evaluation import DimensionScore, EvaluationRubricOutput

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider(BaseLLMProvider):
    """Deterministic Mock LLM Provider for agent pipeline testing, including revision loops & faults."""

    def __init__(
        self,
        mode: str = "normal",
        delay_seconds: float = 0.0,
        critic_failing_scenes: list[int] | None = None,
        force_critic_score: float | None = None,
    ) -> None:
        self.mode = mode
        self.delay_seconds = delay_seconds
        self.critic_failing_scenes = critic_failing_scenes or []
        self.force_critic_score = force_critic_score

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        if self.mode == "timeout":
            raise LLMProviderError("mock", "Request timed out after 30.0s", "TimeoutError")

        if self.mode == "provider_failure":
            raise LLMProviderError("mock", "Service temporarily overloaded (HTTP 503)", "Upstream503")

        if self.mode == "malformed_json":
            raise SchemaValidationError(
                schema.__name__,
                raw_output="{'invalid_json': true,",
                error_detail="JSONDecodeError: Expecting value at line 1 column 22",
            )

        if self.mode == "schema_error":
            raise SchemaValidationError(
                schema.__name__,
                raw_output='{"unexpected_field": "test"}',
                error_detail="Field required: missing required schema keys",
            )

        # 1. EpisodeOutline
        if schema == EpisodeOutline:
            mock_data: dict[str, Any] = {
                "title": "Purani Dilli Ki Dastak",
                "logline": "Late at night in Chandni Chowk, an RJ receives a broadcast from 1947.",
                "target_language": "hinglish",
                "estimated_duration_minutes": 5,
                "characters": [
                    {
                        "name": "Kabir",
                        "role": "protagonist",
                        "vocal_archetype": "warm late-night RJ baritone",
                        "emotional_state": "intrigued then unsettled",
                    },
                    {
                        "name": "Ananya",
                        "role": "supporting",
                        "vocal_archetype": "sharp energetic producer alto",
                        "emotional_state": "deadline-driven",
                    },
                    {
                        "name": "The Caller",
                        "role": "antagonist",
                        "vocal_archetype": "crackle-laden vintage voice",
                        "emotional_state": "desperate and nostalgic",
                    },
                ],
                "scenes": [
                    {
                        "scene_number": 1,
                        "heading": "INT. RADIO MIRAGE STUDIO - MIDNIGHT",
                        "atmosphere_soundscape": "Low air-conditioner hum, console clicks",
                        "characters_present": ["Kabir", "Ananya"],
                        "dramatic_objective": "Establish Kabir's graveyard shift before the intrusion.",
                        "beats": [
                            {
                                "beat_number": 1,
                                "description": "Kabir opens phone lines for confessions.",
                                "conflict_type": "interpersonal",
                                "stakes": "Show cancellation if engagement drops.",
                            }
                        ],
                    },
                    {
                        "scene_number": 2,
                        "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS",
                        "atmosphere_soundscape": "Heavy static, vintage tram bells in background",
                        "characters_present": ["Kabir", "The Caller"],
                        "dramatic_objective": "The Caller speaks with eerie authenticity about 1947.",
                        "beats": [
                            {
                                "beat_number": 1,
                                "description": "The Caller addresses Kabir by his grandfather's nickname.",
                                "conflict_type": "interpersonal",
                                "stakes": "Kabir realizes this is not a prank.",
                            }
                        ],
                    },
                ],
                "cliffhanger_or_resolution": "The Caller transmits a steam train departing. A real 1947 telegram appears on desk.",
            }
            return schema.model_validate(mock_data)

        # 2. Script
        if schema == Script:
            script_data = {
                "title": "Purani Dilli Ki Dastak",
                "scenes": [
                    {
                        "scene_number": 1,
                        "heading": "INT. RADIO MIRAGE STUDIO - MIDNIGHT",
                        "atmosphere_soundscape": "Low AC hum, microphone presence",
                        "dramatic_objective": "Establish baseline reality",
                        "characters_present": ["Kabir", "Ananya"],
                        "lines": [
                            {
                                "id": "line_1_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text": "Good evening, Delhi. This is Kabir, and you are listening to Midnight Mirage.",
                                "stage_direction": "leaning into microphone, soothing cadence",
                                "emotion": "calm",
                                "pace": "normal",
                            },
                            {
                                "id": "line_1_2",
                                "line_number": 2,
                                "character_name": "Ananya",
                                "text": "Kabir, wrap up the intro. Line four has been pulsing for three minutes.",
                                "stage_direction": "through studio intercom, stressed",
                                "emotion": "impatient",
                                "pace": "fast",
                            },
                        ],
                    },
                    {
                        "scene_number": 2,
                        "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS",
                        "atmosphere_soundscape": "High frequency analogue hum, tape hiss",
                        "dramatic_objective": "The supernatural phone call connects",
                        "characters_present": ["Kabir", "The Caller"],
                        "lines": [
                            {
                                "id": "line_2_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text": "Line four, you are on air. What keeps you awake tonight?",
                                "stage_direction": "sliding fader up",
                                "emotion": "curious",
                                "pace": "normal",
                            },
                            {
                                "id": "line_2_2",
                                "line_number": 2,
                                "character_name": "The Caller",
                                "text": "Kabir beta... Lahore Express has just crossed the border.",
                                "stage_direction": "distorted vacuum tube radio tone, trembling",
                                "emotion": "haunting",
                                "pace": "slow",
                            },
                        ],
                    },
                ],
                "total_lines": 4,
            }
            return schema.model_validate(script_data)

        # 3. Single ScriptScene (for targeted scene rewrites)
        if schema == ScriptScene:
            rewritten_scene_data = {
                "scene_number": 2,
                "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS (REWRITTEN)",
                "atmosphere_soundscape": "Ominous magnetic tape distortion, ticking clock",
                "dramatic_objective": "Escalate dramatic tension and emotional stakes",
                "characters_present": ["Kabir", "The Caller"],
                "lines": [
                    {
                        "id": "rev_line_2_1",
                        "line_number": 1,
                        "character_name": "Kabir",
                        "text": "Line four? There's an uncanny frequency on this signal...",
                        "stage_direction": "checking audio meters in confusion",
                        "emotion": "alert",
                        "pace": "normal",
                    },
                    {
                        "id": "rev_line_2_2",
                        "line_number": 2,
                        "character_name": "The Caller",
                        "text": "Kabir beta... your grandfather left this exact brass watch for you.",
                        "stage_direction": "crackling vintage voice with heavy emotional tremor",
                        "emotion": "tearful",
                        "pace": "slow",
                    },
                ],
            }
            return schema.model_validate(rewritten_scene_data)

        # 4. CritiqueReport
        if schema == CritiqueReport:
            has_failures = len(self.critic_failing_scenes) > 0
            score = self.force_critic_score if self.force_critic_score is not None else (6.2 if has_failures else 8.5)
            passed = (score >= 7.5) and not has_failures

            critique_data = {
                "score": score,
                "passed": passed,
                "consistency_score": 8.5 if passed else 6.0,
                "coherence_score": 8.0 if passed else 6.5,
                "naturalness_score": 8.8 if passed else 6.0,
                "pacing_score": 8.2 if passed else 6.0,
                "safety_score": 9.5,
                "scene_critiques": [
                    {
                        "scene_number": 1,
                        "passed": 1 not in self.critic_failing_scenes,
                        "score": 6.0 if 1 in self.critic_failing_scenes else 8.4,
                        "issues": ["Dialogue feels slightly expository"] if 1 in self.critic_failing_scenes else [],
                        "suggested_improvements": "Sharpen producer urgency" if 1 in self.critic_failing_scenes else "Good pace",
                    },
                    {
                        "scene_number": 2,
                        "passed": 2 not in self.critic_failing_scenes,
                        "score": 6.2 if 2 in self.critic_failing_scenes else 8.6,
                        "issues": ["Caller dialogue lacks emotional punch"] if 2 in self.critic_failing_scenes else [],
                        "suggested_improvements": "Inject personal historical details to heighten supernatural tension" if 2 in self.critic_failing_scenes else "Chilling hook",
                    },
                ],
                "failing_scene_numbers": self.critic_failing_scenes,
                "feedback": "Needs revision on failing scenes." if not passed else "Excellent dramatic audio script.",
            }
            return schema.model_validate(critique_data)

        # 5. LocalizedScript
        if schema == LocalizedScript:
            localized_data = {
                "title": "Purani Dilli Ki Dastak",
                "target_language": "hinglish",
                "scenes": [
                    {
                        "scene_number": 1,
                        "heading": "INT. RADIO MIRAGE STUDIO - MIDNIGHT",
                        "atmosphere_soundscape": "Low AC hum, mic presence",
                        "lines": [
                            {
                                "id": "line_1_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text_original": "Good evening, Delhi. This is Kabir, and you are listening to Midnight Mirage.",
                                "text_localized": "Namaste Delhi. Main hoon aapka dost Kabir, aur aap sun rahe hain Midnight Mirage.",
                                "dialect_notes": "Warm conversational Hindi RJ tone",
                                "emotion": "calm",
                                "pace": "normal",
                            },
                            {
                                "id": "line_1_2",
                                "line_number": 2,
                                "character_name": "Ananya",
                                "text_original": "Kabir, wrap up the intro. Line four has been pulsing for three minutes.",
                                "text_localized": "Kabir, jaldi wrap up karo yaar! Line four teen minute se blink kar rahi hai.",
                                "dialect_notes": "Fast urban Hinglish code-switching",
                                "emotion": "impatient",
                                "pace": "fast",
                            },
                        ],
                    },
                    {
                        "scene_number": 2,
                        "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS",
                        "atmosphere_soundscape": "High frequency analogue hum, tape hiss",
                        "lines": [
                            {
                                "id": "line_2_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text_original": "Line four, you are on air. What keeps you awake tonight?",
                                "text_localized": "Haan ji line four, aap on air hain. Bataiye, aaj raat kya baat aapko sone nahi de rahi?",
                                "dialect_notes": "Polite late-night RJ conversational",
                                "emotion": "curious",
                                "pace": "normal",
                            },
                            {
                                "id": "line_2_2",
                                "line_number": 2,
                                "character_name": "The Caller",
                                "text_original": "Kabir beta... Lahore Express has just crossed the border.",
                                "text_localized": "Kabir beta... Lahore Express ne abhi abhi border cross kiya hai.",
                                "dialect_notes": "Old Delhi 1947 historical cadence",
                                "emotion": "haunting",
                                "pace": "slow",
                            },
                        ],
                    },
                ],
                "total_lines": 4,
            }
            return schema.model_validate(localized_data)

        # 6. CastScript
        if schema == CastScript:
            cast_data = {
                "title": "Purani Dilli Ki Dastak",
                "target_language": "hinglish",
                "cast": [
                    {
                        "character_name": "Kabir",
                        "voice_id": "sarvam_m_kabir",
                        "provider": "sarvam",
                        "gender": "male",
                        "vocal_archetype": "warm late-night RJ baritone",
                        "speed": 1.0,
                        "pitch": 0.0,
                    },
                    {
                        "character_name": "Ananya",
                        "voice_id": "sarvam_f_ananya",
                        "provider": "sarvam",
                        "gender": "female",
                        "vocal_archetype": "sharp energetic producer alto",
                        "speed": 1.05,
                        "pitch": 0.0,
                    },
                    {
                        "character_name": "The Caller",
                        "voice_id": "sarvam_m_elder",
                        "provider": "sarvam",
                        "gender": "male",
                        "vocal_archetype": "weathered trembling tenor",
                        "speed": 0.9,
                        "pitch": -0.2,
                    },
                ],
                "scenes": [
                    {
                        "scene_number": 1,
                        "heading": "INT. RADIO MIRAGE STUDIO - MIDNIGHT",
                        "atmosphere_soundscape": "Low AC hum, mic presence",
                        "lines": [
                            {
                                "id": "line_1_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text_original": "Good evening, Delhi...",
                                "text_localized": "Namaste Delhi. Main hoon aapka dost Kabir...",
                                "voice_id": "sarvam_m_kabir",
                            },
                            {
                                "id": "line_1_2",
                                "line_number": 2,
                                "character_name": "Ananya",
                                "text_original": "Kabir, wrap up...",
                                "text_localized": "Kabir, jaldi wrap up karo yaar...",
                                "voice_id": "sarvam_f_ananya",
                            },
                        ],
                    },
                    {
                        "scene_number": 2,
                        "heading": "INT. RADIO MIRAGE STUDIO - CONTINUOUS",
                        "atmosphere_soundscape": "High frequency analogue hum",
                        "lines": [
                            {
                                "id": "line_2_1",
                                "line_number": 1,
                                "character_name": "Kabir",
                                "text_original": "Line four, you are on air...",
                                "text_localized": "Haan ji line four, aap on air hain...",
                                "voice_id": "sarvam_m_kabir",
                            },
                            {
                                "id": "line_2_2",
                                "line_number": 2,
                                "character_name": "The Caller",
                                "text_original": "Kabir beta...",
                                "text_localized": "Kabir beta... Lahore Express...",
                                "voice_id": "sarvam_m_elder",
                            },
                        ],
                    },
                ],
                "total_lines": 4,
            }
            return schema.model_validate(cast_data)

        # 7. BibleUpdatePayload
        if schema == BibleUpdatePayload:
            bible_data = {
                "episode_number": 1,
                "episode_summary": "Kabir received an impossible midnight broadcast from 1947 claiming the Lahore Express has departed.",
                "cliffhanger_or_resolution": "A physical 1947 telegram materialized on Kabir's broadcast desk.",
                "character_updates": [
                    {
                        "character_name": "Kabir",
                        "trait_evolutions": ["Shifted from casual skepticism to supernatural dread."],
                        "relationship_shifts": ["Ananya doubts his sanity."],
                    }
                ],
                "new_world_lore": ["Radio Mirage studio operates on a frequency overlapping historic telegraph lines."],
            }
            return schema.model_validate(bible_data)

        # 8. StoryBibleExtraction (Phase 4 Structured Fact Extraction)
        if schema == StoryBibleExtraction:
            extraction_data = {
                "characters": [
                    {
                        "name": "Kabir",
                        "traits": ["skeptical", "inquisitive", "night-owl"],
                        "vocal_traits": "warm late-night RJ baritone",
                        "current_state": "deeply rattled by supernatural telegram",
                    },
                    {
                        "name": "Ananya",
                        "traits": ["pragmatic", "deadline-focused", "rational"],
                        "vocal_traits": "sharp energetic producer alto",
                        "current_state": "worried about station licensing and Kabir's focus",
                    },
                ],
                "relationships": [
                    {
                        "character_a": "Kabir",
                        "character_b": "Ananya",
                        "dynamic": "Colleagues with playful tension; Ananya acts as Kabir's reality anchor.",
                        "status": "strained due to mystery caller",
                    }
                ],
                "locations": [
                    {
                        "name": "Radio Mirage Studio",
                        "atmosphere_soundscape": "Low air-conditioner hum, neon tube buzz, and analogue hiss.",
                        "significance": "Isolated soundproof booth at 2 AM where historic frequencies bleed through.",
                    }
                ],
                "events": [
                    {
                        "title": "Midnight 1947 Broadcast",
                        "description": "An unidentified caller on line four spoke of the 1947 Lahore Express as if it were departing tonight.",
                        "characters_involved": ["Kabir", "Ananya"],
                    }
                ],
                "open_plot_threads": [
                    {
                        "thread_id": "lahore_express_telegram",
                        "description": "Who dispatched the physical 1947 telegram onto Kabir's locked console?",
                        "status": "open",
                    }
                ],
                "episode_synopsis": "During a live graveyard shift, RJ Kabir takes an eerie caller warning about a train from 1947, culminating in an impossible physical telegram on his desk.",
            }
            return schema.model_validate(extraction_data)

        # 9. EvaluationRubricOutput (Phase 5 LLM Judge Rubric)
        if schema == EvaluationRubricOutput:
            # Calibrate mock scores based on prompt cues if evaluating calibration samples
            is_defective = "defective" in prompt.lower() or "hallucination" in prompt.lower() or "broken" in prompt.lower()
            is_medium = "medium" in prompt.lower() or "decent" in prompt.lower()

            if is_defective or self.mode == "judge_low_quality":
                judge_data = {
                    "character_consistency": {
                        "score": 2.2,
                        "reasoning": "Major vocal persona drift; characters contradict established motivations.",
                        "evidence": ["Character personality flipped unexpectedly in scene 2"],
                    },
                    "plot_coherence": {
                        "score": 2.0,
                        "reasoning": "Significant plot holes and unexplained temporal shifts.",
                        "evidence": ["Cause and effect breakdown in dialogue sequence"],
                    },
                    "language_naturalness": {
                        "score": 2.3,
                        "reasoning": "Robotic phrasing and awkward dialect transliteration.",
                        "evidence": ["Literal machine translation artifact detected"],
                    },
                    "pacing": {
                        "score": 2.1,
                        "reasoning": "Severe pacing stalls and dialogue bloat without acoustic sound cues.",
                        "evidence": ["Overlong monologues without stage directions"],
                    },
                    "safety": {
                        "score": 4.5,
                        "reasoning": "Mild content warnings, no severe violations.",
                        "evidence": [],
                    },
                    "overall_critique": "Script fails audio production standards due to incoherent plot progression and robotic speech.",
                }
            elif is_medium or self.mode == "judge_medium_quality":
                judge_data = {
                    "character_consistency": {
                        "score": 3.6,
                        "reasoning": "Acceptable character differentiation, though dialogue can feel generic.",
                        "evidence": ["Characters have recognizable traits but lack deep vocal contrast"],
                    },
                    "plot_coherence": {
                        "score": 3.6,
                        "reasoning": "Logical dramatic spine with minor unresolved threads.",
                        "evidence": ["A couple of dialogue beats lack clear stakes"],
                    },
                    "language_naturalness": {
                        "score": 3.7,
                        "reasoning": "Good conversational flow with occasional stiff phrases.",
                        "evidence": ["Colloquial code-switching mostly natural"],
                    },
                    "pacing": {
                        "score": 3.4,
                        "reasoning": "Moderate pacing; middle scene slows down during exposition.",
                        "evidence": ["Middle scene has delayed conflict introduction"],
                    },
                    "safety": {
                        "score": 5.0,
                        "reasoning": "Fully compliant with audio broadcast safety guidelines.",
                        "evidence": [],
                    },
                    "overall_critique": "Competent episode draft with solid narrative structure; would benefit from tighter scene pacing.",
                }
            else:
                # High quality / production standard
                judge_data = {
                    "character_consistency": {
                        "score": 4.8,
                        "reasoning": "Superb vocal archetype distinction and authentic subtext for all cast members.",
                        "evidence": ["Rich character voice distinctiveness throughout all scenes"],
                    },
                    "plot_coherence": {
                        "score": 4.7,
                        "reasoning": "Tight dramatic progression with compelling acoustic stakes and organic cliffhanger.",
                        "evidence": ["Clear cause-and-effect beats matching episode outline"],
                    },
                    "language_naturalness": {
                        "score": 4.8,
                        "reasoning": "Culturally authentic dialect adaptation with natural colloquial cadence.",
                        "evidence": ["Exceptional linguistic flow and authentic idioms"],
                    },
                    "pacing": {
                        "score": 4.6,
                        "reasoning": "Immersive acoustic soundscape instructions and crisp dramatic tempo.",
                        "evidence": ["Audio sound cues tightly synchronized with dialogue turns"],
                    },
                    "safety": {
                        "score": 5.0,
                        "reasoning": "Exemplary adherence to audio broadcast standards.",
                        "evidence": [],
                    },
                    "overall_critique": "Outstanding production-ready audio story episode with vivid sound design.",
                }
            return schema.model_validate(judge_data)

        try:
            return schema.model_validate({})
        except Exception as exc:
            raise SchemaValidationError(schema.__name__, "{}", str(exc))

    async def generate_chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        if self.mode == "provider_failure":
            raise LLMProviderError("mock", "Service temporarily overloaded (HTTP 503)", "Upstream503")
        return f"Mock response for prompt: {prompt[:50]}..."
