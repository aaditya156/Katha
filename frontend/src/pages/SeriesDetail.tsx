import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../services/api';
import { Episode, EpisodeOutline, ProblemDetails, Series } from '../types';
import {
  ArrowLeft,
  Headphones,
  Sparkles,
  Radio,
  Clock,
  Volume2,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';

export const SeriesDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [series, setSeries] = useState<Series | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Outline Generator State
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [premiseInput, setPremiseInput] = useState('');
  const [durationInput, setDurationInput] = useState(5);
  const [generatedOutline, setGeneratedOutline] = useState<EpisodeOutline | null>(null);
  const [outlineError, setOutlineError] = useState<string | null>(null);
  const [isSavingEpisode, setIsSavingEpisode] = useState(false);
  const navigate = useNavigate();

  const loadData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const seriesData = await api.getSeries(id);
      setSeries(seriesData);
      const epData = await api.listEpisodes(id);
      setEpisodes(epData);
    } catch (err) {
      setError('Failed to load series details.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [id]);

  const handleGenerateOutline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!series) return;
    setIsGenerating(true);
    setOutlineError(null);
    setGeneratedOutline(null);

    try {
      const outline = await api.generateOutline({
        series_id: series.id,
        episode_number: episodes.length + 1,
        premise: premiseInput,
        target_language: series.target_language,
        target_duration_minutes: durationInput,
        genre: series.genre,
      });
      setGeneratedOutline(outline);
    } catch (err) {
      const problem = err as ProblemDetails;
      setOutlineError(problem.detail || 'Outline generation failed.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSaveEpisode = async () => {
    if (!series || !generatedOutline) return;
    setIsSavingEpisode(true);
    try {
      const newEp = await api.createEpisode({
        series_id: series.id,
        episode_number: episodes.length + 1,
        title: generatedOutline.title,
        premise: premiseInput,
        target_language: series.target_language,
        duration_minutes_target: durationInput,
      });
      setEpisodes((prev) => [...prev, newEp]);
      setGeneratorOpen(false);
      setGeneratedOutline(null);
      setPremiseInput('');
    } catch {
      alert('Failed to save episode to database.');
    } finally {
      setIsSavingEpisode(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin text-amber-400" />
        <span className="ml-3">Loading studio workspace...</span>
      </div>
    );
  }

  if (error || !series) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">
        <div className="text-center">
          <p className="text-red-400 mb-4">{error || 'Series not found'}</p>
          <Link to="/" className="text-amber-400 hover:underline">
            Return to Series List
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Series Roster
          </Link>
          <div className="flex items-center gap-2">
            <Headphones className="w-5 h-5 text-amber-400" />
            <span className="font-display font-bold text-lg text-white">कथा Studio</span>
          </div>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="flex-1 max-w-7xl mx-auto px-4 py-8 w-full">
        {/* Series Banner */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-8 mb-8 backdrop-blur-sm relative overflow-hidden">
          <div className="absolute top-0 right-0 w-80 h-80 bg-amber-500/5 rounded-full blur-3xl pointer-events-none" />

          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="px-3 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-semibold uppercase tracking-wider">
              {series.genre}
            </span>
            <span className="px-3 py-1 rounded-lg bg-slate-800 text-slate-300 text-xs font-medium uppercase tracking-wider">
              Dialect: {series.target_language}
            </span>
            <span className="px-3 py-1 rounded-lg bg-slate-800 text-slate-300 text-xs font-medium">
              Episodes: {episodes.length}
            </span>
          </div>

          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight font-display mb-3">
            {series.title}
          </h1>

          <p className="text-slate-300 max-w-3xl leading-relaxed text-sm sm:text-base">
            {series.logline}
          </p>
        </div>

        {/* Episodes Section Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Radio className="w-5 h-5 text-amber-400" />
              Episode Roster
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Plan and generate episodic scripts with audio synthesis.
            </p>
          </div>

          <button
            onClick={() => setGeneratorOpen(!generatorOpen)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-slate-950 bg-amber-500 hover:bg-amber-400 transition-all shadow-md shadow-amber-500/10"
          >
            <Sparkles className="w-4 h-4" />
            {generatorOpen ? 'Hide Generator' : 'Generate New Episode Outline'}
          </button>
        </div>

        {/* Outline Generator Drawer */}
        {generatorOpen && (
          <div className="bg-slate-900 border border-amber-500/30 rounded-2xl p-6 sm:p-8 mb-8 shadow-2xl transition-all">
            <div className="flex items-center gap-2 text-amber-400 text-sm font-semibold uppercase tracking-wider mb-2">
              <Sparkles className="w-4 h-4" />
              LangGraph Planner Agent Outline Generator
            </div>
            <h3 className="text-xl font-bold text-white mb-4">
              Draft Episode {episodes.length + 1} Architecture
            </h3>

            {outlineError && (
              <div className="p-4 rounded-xl bg-red-950/50 border border-red-500/40 text-red-300 text-sm mb-6 flex items-start gap-2">
                <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                <span>{outlineError}</span>
              </div>
            )}

            <form onSubmit={handleGenerateOutline} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                    Episode Seed Premise / Conflict Hook
                  </label>
                  <input
                    type="text"
                    required
                    value={premiseInput}
                    onChange={(e) => setPremiseInput(e.target.value)}
                    placeholder="e.g. A midnight caller on the radio broadcast claims to be dialing in from 1947..."
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                    Target Duration (Minutes)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={durationInput}
                    onChange={(e) => setDurationInput(parseInt(e.target.value) || 5)}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={isGenerating}
                  className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-slate-950 bg-amber-500 hover:bg-amber-400 transition-all disabled:opacity-50"
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Synthesizing Narrative Beats...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Generate Structured Outline
                    </>
                  )}
                </button>
              </div>
            </form>

            {/* Generated Outline Output Display */}
            {generatedOutline && (
              <div className="mt-8 pt-8 border-t border-slate-800 space-y-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <span className="px-2.5 py-0.5 rounded text-xs font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      Validated Schema Output
                    </span>
                    <h4 className="text-2xl font-bold text-white font-display mt-1">
                      {generatedOutline.title}
                    </h4>
                    <p className="text-sm text-slate-300 mt-1 italic">
                      "{generatedOutline.logline}"
                    </p>
                  </div>

                  <button
                    onClick={handleSaveEpisode}
                    disabled={isSavingEpisode}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-emerald-500 hover:bg-emerald-400 text-slate-950 transition-all shadow-lg shadow-emerald-500/20"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    {isSavingEpisode ? 'Saving...' : 'Accept & Add to Series'}
                  </button>
                </div>

                {/* Characters Roster */}
                <div>
                  <h5 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                    Character Casting Profile
                  </h5>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {generatedOutline.characters.map((c, i) => (
                      <div key={i} className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-semibold text-white text-sm">{c.name}</span>
                          <span className="text-[10px] uppercase font-bold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                            {c.role}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 flex items-center gap-1 mt-1">
                          <Volume2 className="w-3 h-3 text-amber-500" />
                          {c.vocal_archetype}
                        </p>
                        <p className="text-[11px] text-slate-500 mt-1">
                          Mood: {c.emotional_state}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Scenes Breakdown */}
                <div>
                  <h5 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                    Scene & Acoustic Breakdown
                  </h5>
                  <div className="space-y-3">
                    {generatedOutline.scenes.map((scene, idx) => (
                      <div key={idx} className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-bold text-amber-400">
                            {scene.heading}
                          </span>
                          <span className="text-xs text-slate-500">
                            Characters: {scene.characters_present.join(', ')}
                          </span>
                        </div>
                        <p className="text-xs text-slate-300">
                          <strong className="text-slate-400">Soundscape:</strong> {scene.atmosphere_soundscape}
                        </p>
                        <p className="text-xs text-slate-300">
                          <strong className="text-slate-400">Dramatic Objective:</strong> {scene.dramatic_objective}
                        </p>
                        <div className="pt-2 pl-3 border-l-2 border-slate-800 space-y-1">
                          {scene.beats.map((b) => (
                            <p key={b.beat_number} className="text-xs text-slate-400">
                              <span className="text-amber-500/80 font-mono">Beat {b.beat_number}:</span> {b.description}
                              <span className="text-slate-500 ml-2 italic">({b.stakes})</span>
                            </p>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Cliffhanger Hook */}
                <div className="p-4 bg-amber-950/20 border border-amber-500/20 rounded-xl">
                  <span className="text-xs font-bold text-amber-400 uppercase tracking-wider">
                    Ending Hook / Cliffhanger
                  </span>
                  <p className="text-sm text-amber-200/90 mt-1">
                    {generatedOutline.cliffhanger_or_resolution}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Existing Episodes List */}
        {episodes.length === 0 ? (
          <div className="border border-dashed border-slate-800 rounded-2xl p-8 text-center bg-slate-900/20">
            <Radio className="w-10 h-10 text-slate-600 mx-auto mb-2" />
            <h4 className="text-base font-semibold text-white">No episodes in this series yet</h4>
            <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
              Use the Outline Generator above to design your pilot episode.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {episodes.map((ep) => (
              <div
                key={ep.id}
                onClick={() => navigate(`/episodes/${ep.id}`)}
                className="p-5 bg-slate-900/60 border border-slate-800 hover:border-amber-500/40 rounded-2xl flex items-center justify-between gap-4 transition-all cursor-pointer group hover:bg-slate-900"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center font-mono font-bold text-amber-400 group-hover:scale-105 transition-transform">
                    #{ep.episode_number}
                  </div>
                  <div>
                    <h4 className="text-base font-bold text-white font-display group-hover:text-amber-400 transition-colors">
                      {ep.title}
                    </h4>
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">
                      {ep.premise}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="px-2.5 py-1 text-xs rounded-lg font-mono bg-slate-800 text-slate-400 border border-slate-700/60">
                    {ep.status}
                  </span>
                  <span className="text-xs text-slate-500 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    {ep.duration_minutes_target}m
                  </span>
                  <span className="text-xs text-amber-400 font-semibold hidden sm:inline-block ml-2 group-hover:translate-x-1 transition-transform">
                    Enter Studio →
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};
