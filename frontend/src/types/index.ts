export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface Series {
  id: string;
  user_id: string;
  title: string;
  genre: string;
  logline: string;
  target_language: 'hindi' | 'hinglish' | 'english';
  status: string;
  created_at: string;
  updated_at: string;
  episodes?: Episode[];
}

export interface ScriptLine {
  id: string;
  line_number: number;
  character_name: string;
  text: string;
  stage_direction: string;
  emotion: string;
  pace: string;
  voice_id?: string | null;
}

export interface ScriptScene {
  scene_number: number;
  heading: string;
  atmosphere_soundscape: string;
  dramatic_objective: string;
  characters_present: string[];
  lines: ScriptLine[];
}

export interface VoiceAssignment {
  character_name: string;
  voice_id: string;
  provider: string;
  gender: string;
  vocal_archetype: string;
  speed: number;
  pitch: number;
}

export interface LocalizedLine {
  id: string;
  line_number: number;
  character_name: string;
  text_original: string;
  text_localized: string;
  dialect_notes: string;
  emotion?: string;
  pace?: string;
  voice_id?: string | null;
}

export interface LocalizedScene {
  scene_number: number;
  heading: string;
  atmosphere_soundscape: string;
  lines: LocalizedLine[];
}

export interface TimelineEntry {
  line_id: string;
  character_name: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
}

export interface CastScript {
  title: string;
  target_language: string;
  cast: VoiceAssignment[];
  scenes: LocalizedScene[];
  total_lines: number;
  timeline?: TimelineEntry[];
}

export interface SceneCritique {
  scene_number: number;
  passed: boolean;
  score: number;
  issues: string[];
  suggested_improvements: string;
}

export interface CritiqueReport {
  score: number;
  passed: boolean;
  consistency_score: number;
  coherence_score: number;
  naturalness_score: number;
  pacing_score: number;
  safety_score: number;
  scene_critiques: SceneCritique[];
  failing_scene_numbers: number[];
  feedback: string;
}

export interface Episode {
  id: string;
  series_id: string;
  episode_number: number;
  title: string;
  premise: string;
  status: 'DRAFT' | 'OUTLINE_GENERATED' | 'WRITING' | 'REVISING' | 'LOCALIZED' | 'READY' | 'FAILED';
  target_language: 'hindi' | 'hinglish' | 'english';
  duration_minutes_target: number;
  outline?: EpisodeOutline | null;
  script?: CastScript | null;
  audio_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CharacterAppearance {
  name: string;
  role: string;
  vocal_archetype: string;
  emotional_state: string;
}

export interface DramaticBeat {
  beat_number: number;
  description: string;
  conflict_type: string;
  stakes: string;
}

export interface SceneOutline {
  scene_number: number;
  heading: string;
  atmosphere_soundscape: string;
  characters_present: string[];
  dramatic_objective: string;
  beats: DramaticBeat[];
}

export interface EpisodeOutline {
  title: string;
  logline: string;
  target_language: string;
  estimated_duration_minutes: number;
  characters: CharacterAppearance[];
  scenes: SceneOutline[];
  cliffhanger_or_resolution: string;
}

export interface PipelineEvent {
  episode_id: string;
  event_type: string;
  node?: string | null;
  timestamp: string;
  payload: Record<string, any>;
}

export interface StoryBibleEntry {
  id: string;
  series_id: string;
  episode_id?: string | null;
  entity_type: 'character' | 'relationship' | 'location' | 'event' | 'open_plot_thread' | 'rule' | 'episode_summary' | string;
  entity_name: string;
  content: string;
  metadata_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface StoryBibleSearchResult {
  entry: StoryBibleEntry;
  score: number;
  retrieval_method: string;
}

export interface StoryBibleSearchResponse {
  status: 'RETRIEVAL_SUCCESS' | 'RETRIEVAL_EMPTY' | 'RETRIEVAL_DISABLED';
  query: string;
  results: StoryBibleSearchResult[];
  retrieval_enabled: boolean;
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  error_code: string;
  extras?: Record<string, unknown>;
}

export interface GoldenTestCase {
  id: string;
  title: string;
  premise: string;
  genre: string;
  target_language: string;
  target_duration_minutes: number;
  expected_characters: string[];
  key_continuity_elements: string[];
  difficulty: string;
}

export interface DimensionScore {
  score: number;
  reasoning: string;
  evidence: string[];
}

export interface EvaluationRubricOutput {
  character_consistency: DimensionScore;
  plot_coherence: DimensionScore;
  language_naturalness: DimensionScore;
  pacing: DimensionScore;
  safety: DimensionScore;
  overall_critique: string;
}

export interface EvaluationRun {
  id: string;
  series_id?: string | null;
  episode_id?: string | null;
  test_case_id?: string | null;
  model_name: string;
  provider: string;
  critic_enabled: boolean;
  retrieval_enabled: boolean;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number;
  revision_count: number;
  tts_cache_hit_rate: number;
  composite_score: number;
  character_consistency: number;
  plot_coherence: number;
  language_naturalness: number;
  pacing: number;
  safety: number;
  passed: boolean;
  verdict: string;
  scores_json: Record<string, any>;
  node_latencies_json: Record<string, any>;
  feedback: string;
  created_at: string;
}

export interface EvaluationSummaryMetrics {
  total_runs: number;
  pass_rate: number;
  avg_quality_score: number;
  dimension_averages: {
    character_consistency: number;
    plot_coherence: number;
    language_naturalness: number;
    pacing: number;
    safety: number;
  };
  p50_latency_ms: number;
  p95_latency_ms: number;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  avg_revision_count: number;
  avg_tts_cache_hit_rate: number;
  failure_taxonomy: Record<string, number>;
}

export interface ExperimentVariantMetrics {
  variant_name: string;
  sample_count: number;
  avg_composite_score: number;
  avg_character_consistency: number;
  avg_plot_coherence: number;
  avg_language_naturalness: number;
  avg_pacing: number;
  avg_safety: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  avg_tokens: number;
  avg_cost_usd: number;
  pass_rate: number;
  revision_rate: number;
  tts_cache_hit_rate: number;
}

export interface BenchmarkExperimentResponse {
  experiment_id: string;
  experiment_type: 'critic_on_off' | 'rag_ablation' | 'model_comparison';
  title: string;
  variants: ExperimentVariantMetrics[];
  delta_analysis: Record<string, any>;
  created_at: string;
}

export interface CalibrationReport {
  total_samples: number;
  spearman_correlation: Record<string, number>;
  weighted_cohens_kappa: Record<string, number>;
  mean_absolute_error: Record<string, number>;
  identified_weaknesses: string[];
  recommendations: string[];
  calibration_status: 'EXCELLENT' | 'ACCEPTABLE' | 'NEEDS_TUNING';
}
