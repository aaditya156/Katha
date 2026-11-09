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
  script?: Record<string, unknown> | null;
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

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  error_code: string;
  extras?: Record<string, unknown>;
}
