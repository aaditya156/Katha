import { AuthTokens, Episode, EpisodeOutline, ProblemDetails, Series, User } from '../types';

const API_BASE = '/api/v1';

class ApiClient {
  private getAuthHeader(): Record<string, string> {
    const token = localStorage.getItem('katha_access_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...this.getAuthHeader(),
      ...options.headers,
    };

    const response = await fetch(url, { ...options, headers });

    if (response.status === 204) {
      return {} as T;
    }

    if (!response.ok) {
      let problem: ProblemDetails;
      try {
        problem = await response.json();
      } catch {
        problem = {
          type: 'about:blank',
          title: response.statusText || 'Error',
          status: response.status,
          detail: 'Failed to communicate with Katha API server.',
          error_code: 'SERVER_COMMUNICATION_ERROR',
        };
      }

      if (response.status === 401 && !endpoint.includes('/auth/login')) {
        localStorage.removeItem('katha_access_token');
        localStorage.removeItem('katha_refresh_token');
        window.location.href = '/login';
      }

      throw problem;
    }

    return response.json() as Promise<T>;
  }

  // Auth API
  async login(email: string, password: string): Promise<AuthTokens> {
    return this.request<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }

  async register(email: string, password: string, fullName?: string): Promise<AuthTokens> {
    return this.request<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: fullName }),
    });
  }

  async getMe(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  // Series API
  async listSeries(): Promise<Series[]> {
    return this.request<Series[]>('/series');
  }

  async getSeries(id: string): Promise<Series> {
    return this.request<Series>(`/series/${id}`);
  }

  async createSeries(data: {
    title: string;
    logline: string;
    genre: string;
    target_language: 'hindi' | 'hinglish' | 'english';
  }): Promise<Series> {
    return this.request<Series>('/series', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async deleteSeries(id: string): Promise<void> {
    return this.request<void>(`/series/${id}`, {
      method: 'DELETE',
    });
  }

  // Episodes API
  async listEpisodes(seriesId: string): Promise<Episode[]> {
    return this.request<Episode[]>(`/episodes/series/${seriesId}`);
  }

  async getEpisode(episodeId: string): Promise<Episode> {
    return this.request<Episode>(`/episodes/${episodeId}`);
  }

  async triggerGeneration(episodeId: string): Promise<{ status: string; message: string; episode_id: string }> {
    return this.request<{ status: string; message: string; episode_id: string }>(
      `/generation/episodes/${episodeId}/generate`,
      { method: 'POST' }
    );
  }

  getEpisodeEventsUrl(episodeId: string): string {
    const token = localStorage.getItem('katha_access_token');
    return `/api/v1/generation/episodes/${episodeId}/events?token=${token || ''}`;
  }

  async createEpisode(data: {
    series_id: string;
    title: string;
    premise: string;
    episode_number: number;
    target_language: 'hindi' | 'hinglish' | 'english';
    duration_minutes_target: number;
  }): Promise<Episode> {
    return this.request<Episode>('/episodes', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async generateOutline(data: {
    series_id?: string;
    episode_number: number;
    premise: string;
    target_language: 'hindi' | 'hinglish' | 'english';
    target_duration_minutes: number;
    genre: string;
    characters_hint?: string[];
  }): Promise<EpisodeOutline> {
    return this.request<EpisodeOutline>('/episodes/generate-outline', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }
}

export const api = new ApiClient();

