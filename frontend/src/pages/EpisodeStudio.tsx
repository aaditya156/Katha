import React, { useEffect, useState, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../services/api';
import { CastScript, Episode, PipelineEvent, Series } from '../types';
import {
  ArrowLeft,
  Play,
  RotateCw,
  CheckCircle2,
  Volume2,
  Radio,
  FileText,
  Users,
  Terminal,
  Activity,
  Layers,
  Loader2,
} from 'lucide-react';

const PIPELINE_NODES = [
  { id: 'planner', label: 'Planner', description: 'Dramatic beats & scene structure' },
  { id: 'writer', label: 'Writer', description: 'Multi-character dialogue draft' },
  { id: 'critic', label: 'Critic', description: 'Coherence, pacing & revision loop' },
  { id: 'localizer', label: 'Localizer', description: 'Hindi / Hinglish dialect adaptation' },
  { id: 'voice_caster', label: 'Voice Caster', description: 'Persistent character voice IDs' },
  { id: 'bible_updater', label: 'Bible Updater', description: 'Episodic memory & continuity' },
];

export const EpisodeStudio: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [activeTab, setActiveTab] = useState<'script' | 'cast' | 'outline' | 'logs'>('script');
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentNode, setCurrentNode] = useState<string | null>(null);
  const [completedNodes, setCompletedNodes] = useState<string[]>([]);
  const [eventsLog, setEventsLog] = useState<PipelineEvent[]>([]);
  const [revisionCount, setRevisionCount] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchEpisodeData = async () => {
    if (!id) return;
    try {
      const epData = await api.getEpisode(id);
      setEpisode(epData);
      if (epData.series_id) {
        const seriesData = await api.getSeries(epData.series_id);
        setSeries(seriesData);
      }
    } catch {
      // Error handled in UI
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchEpisodeData();
  }, [id]);

  // Connect to SSE Stream
  useEffect(() => {
    if (!id) return;
    const sseUrl = api.getEpisodeEventsUrl(id);
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed: PipelineEvent = JSON.parse(event.data);
        setEventsLog((prev) => [parsed, ...prev]);

        if (parsed.node) {
          setCurrentNode(parsed.node);
        }

        if (parsed.event_type === 'node_completed' && parsed.node) {
          setCompletedNodes((prev) => Array.from(new Set([...prev, parsed.node!])));
        }

        if (parsed.event_type === 'scene_rewritten') {
          setRevisionCount((prev) => prev + 1);
        }

        if (parsed.event_type === 'pipeline_completed') {
          setIsGenerating(false);
          setCurrentNode(null);
          setCompletedNodes(PIPELINE_NODES.map((n) => n.id));
          fetchEpisodeData(); // Refresh script data
        }

        if (parsed.event_type === 'pipeline_failed') {
          setIsGenerating(false);
          setCurrentNode(null);
          fetchEpisodeData();
        }
      } catch {
        // Parse error ignored
      }
    };

    return () => {
      es.close();
    };
  }, [id]);

  const handleStartGeneration = async () => {
    if (!id) return;
    setIsGenerating(true);
    setCompletedNodes([]);
    setCurrentNode('planner');
    setRevisionCount(0);
    try {
      await api.triggerGeneration(id);
    } catch {
      setIsGenerating(false);
      alert('Failed to trigger generation pipeline.');
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin text-amber-400" />
        <span className="ml-3">Loading Production Studio...</span>
      </div>
    );
  }

  if (!episode) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">
        <p>Episode not found.</p>
      </div>
    );
  }

  const castScript = episode.script as CastScript | undefined;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Studio Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to={series ? `/series/${series.id}` : '/'}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              {series ? series.title : 'Back'}
            </Link>
            <div className="h-4 w-px bg-slate-800" />
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Ep. #{episode.episode_number}
              </span>
              <h1 className="text-base font-bold text-white font-display line-clamp-1">
                {episode.title}
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="px-2.5 py-1 text-xs rounded-lg font-mono bg-slate-800 text-slate-300 border border-slate-700 capitalize">
              {episode.target_language}
            </span>
            <button
              onClick={handleStartGeneration}
              disabled={isGenerating}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 transition-all shadow-md shadow-amber-500/20 disabled:opacity-50"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  Run LangGraph Pipeline
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Main Studio Canvas */}
      <main className="flex-1 max-w-7xl mx-auto px-4 py-6 w-full space-y-6">
        {/* LangGraph Pipeline Visualizer */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Activity className="w-4 h-4 text-amber-400" />
              LangGraph Cyclical State Machine
            </span>
            {revisionCount > 0 && (
              <span className="text-xs font-mono px-2.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center gap-1.5">
                <RotateCw className="w-3 h-3 animate-spin" />
                Revision Loop Active (Cycle {revisionCount}/2)
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {PIPELINE_NODES.map((node) => {
              const isActive = currentNode === node.id;
              const isDone = completedNodes.includes(node.id);
              return (
                <div
                  key={node.id}
                  className={`p-3 rounded-xl border transition-all ${
                    isActive
                      ? 'bg-amber-500/10 border-amber-500/50 shadow-lg shadow-amber-500/10 scale-102 ring-1 ring-amber-500/40'
                      : isDone
                      ? 'bg-emerald-950/20 border-emerald-500/30'
                      : 'bg-slate-950/40 border-slate-800/80 opacity-70'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold text-white">{node.label}</span>
                    {isActive ? (
                      <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
                    ) : isDone ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <div className="w-2 h-2 rounded-full bg-slate-700" />
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 line-clamp-1">{node.description}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-slate-800 gap-6">
          <button
            onClick={() => setActiveTab('script')}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === 'script'
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <FileText className="w-4 h-4" />
            Localized Script ({castScript?.total_lines || 0} Lines)
          </button>
          <button
            onClick={() => setActiveTab('cast')}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === 'cast'
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Users className="w-4 h-4" />
            Voice Casting ({castScript?.cast?.length || 0} Actors)
          </button>
          <button
            onClick={() => setActiveTab('outline')}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === 'outline'
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Layers className="w-4 h-4" />
            Dramatic Architecture
          </button>
          <button
            onClick={() => setActiveTab('logs')}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === 'logs'
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Terminal className="w-4 h-4" />
            Live SSE Stream ({eventsLog.length})
          </button>
        </div>

        {/* Tab Content: Localized Script */}
        {activeTab === 'script' && (
          <div className="space-y-6">
            {!castScript ? (
              <div className="text-center py-16 border border-dashed border-slate-800 rounded-2xl bg-slate-900/20">
                <Radio className="w-10 h-10 text-slate-600 mx-auto mb-2" />
                <h3 className="text-base font-semibold text-white">No Script Generated Yet</h3>
                <p className="text-xs text-slate-400 max-w-sm mx-auto mt-1 mb-4">
                  Run the LangGraph pipeline above to draft, critique, localize, and voice-cast this episode.
                </p>
                <button
                  onClick={handleStartGeneration}
                  disabled={isGenerating}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-semibold bg-amber-500 text-slate-950 hover:bg-amber-400 transition-all"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  Launch Pipeline
                </button>
              </div>
            ) : (
              <div className="space-y-8">
                {castScript.scenes.map((scene) => (
                  <div
                    key={scene.scene_number}
                    className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm space-y-4"
                  >
                    <div className="border-b border-slate-800/80 pb-3 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-sm font-bold text-amber-400">
                        {scene.heading}
                      </span>
                      <span className="text-xs text-slate-400 italic">
                        Bed: {scene.atmosphere_soundscape}
                      </span>
                    </div>

                    <div className="space-y-3">
                      {scene.lines.map((line) => (
                        <div
                          key={line.id}
                          className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800/60 flex items-start gap-3 hover:border-slate-700 transition-colors"
                        >
                          <div className="w-24 shrink-0">
                            <span className="font-semibold text-white text-xs block truncate">
                              {line.character_name}
                            </span>
                            {line.voice_id && (
                              <span className="text-[10px] text-amber-400/80 font-mono block truncate">
                                {line.voice_id}
                              </span>
                            )}
                          </div>

                          <div className="flex-1 space-y-1">
                            <p className="text-sm text-slate-200 leading-relaxed">
                              {line.text_localized}
                            </p>
                            {line.dialect_notes && (
                              <p className="text-[11px] text-slate-500 italic">
                                Note: {line.dialect_notes}
                              </p>
                            )}
                          </div>

                          <div className="shrink-0 flex items-center gap-1.5 text-xs text-slate-500">
                            <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-[10px] capitalize">
                              {line.emotion || 'neutral'}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Content: Cast */}
        {activeTab === 'cast' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {castScript?.cast?.map((actor, idx) => (
              <div
                key={idx}
                className="p-5 bg-slate-900/50 border border-slate-800 rounded-2xl flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-white text-base font-display">
                      {actor.character_name}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      {actor.provider}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 flex items-center gap-1.5 mb-1">
                    <Volume2 className="w-3.5 h-3.5 text-amber-400" />
                    Voice ID: <code className="text-amber-300 font-mono">{actor.voice_id}</code>
                  </p>
                  <p className="text-xs text-slate-400 capitalize">
                    Gender: {actor.gender} • Archetype: {actor.vocal_archetype}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800 text-xs text-slate-500 flex justify-between">
                  <span>Speed: {actor.speed}x</span>
                  <span>Pitch: {actor.pitch >= 0 ? `+${actor.pitch}` : actor.pitch}</span>
                </div>
              </div>
            )) || (
              <p className="text-sm text-slate-500 col-span-full">No voice cast assigned yet.</p>
            )}
          </div>
        )}

        {/* Tab Content: Dramatic Outline */}
        {activeTab === 'outline' && episode.outline && (
          <div className="space-y-6 bg-slate-900/40 p-6 rounded-2xl border border-slate-800">
            <div>
              <h3 className="text-xl font-bold text-white font-display">
                {episode.outline.title}
              </h3>
              <p className="text-sm text-slate-300 mt-1 italic">
                "{episode.outline.logline}"
              </p>
            </div>

            <div className="space-y-4">
              {episode.outline.scenes.map((sc) => (
                <div key={sc.scene_number} className="p-4 bg-slate-950 rounded-xl border border-slate-800">
                  <span className="font-mono text-xs font-bold text-amber-400">{sc.heading}</span>
                  <p className="text-xs text-slate-400 mt-1">Objective: {sc.dramatic_objective}</p>
                  <p className="text-xs text-slate-400">Atmosphere: {sc.atmosphere_soundscape}</p>
                </div>
              ))}
            </div>

            <div className="p-4 bg-amber-950/20 border border-amber-500/20 rounded-xl">
              <span className="text-xs font-bold text-amber-400 uppercase">Cliffhanger</span>
              <p className="text-sm text-amber-200 mt-1">{episode.outline.cliffhanger_or_resolution}</p>
            </div>
          </div>
        )}

        {/* Tab Content: SSE Live Event Stream */}
        {activeTab === 'logs' && (
          <div className="bg-slate-950 rounded-2xl border border-slate-800 p-4 font-mono text-xs space-y-2 max-h-96 overflow-y-auto custom-scrollbar">
            {eventsLog.length === 0 ? (
              <p className="text-slate-600">No events received yet. Run the pipeline to stream events.</p>
            ) : (
              eventsLog.map((ev, i) => (
                <div key={i} className="flex items-start gap-3 border-b border-slate-900 pb-2">
                  <span className="text-slate-500 shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-amber-400 shrink-0">
                    {ev.node || 'pipeline'}
                  </span>
                  <span className="text-slate-300 font-semibold">{ev.event_type}:</span>
                  <span className="text-slate-400 break-all">
                    {JSON.stringify(ev.payload)}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </main>
    </div>
  );
};
