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

export interface CastScript {
  title: string;
  target_language: string;
  cast: VoiceAssignment[];
  scenes: LocalizedScene[];
  total_lines: number;
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

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  error_code: string;
  extras?: Record<string, unknown>;
}
