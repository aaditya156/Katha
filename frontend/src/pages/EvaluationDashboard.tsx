import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import {
  BenchmarkExperimentResponse,
  CalibrationReport,
  EvaluationRun,
  EvaluationSummaryMetrics,
  GoldenTestCase,
} from '../types';
import {
  Activity,
  ArrowLeft,
  Award,
  BarChart3,
  CheckCircle2,
  Clock,
  Coins,
  Database,
  Flame,
  FlaskConical,
  Layers,
  Loader2,
  Play,
  RotateCcw,
  Scale,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  XCircle,
} from 'lucide-react';

export const EvaluationDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'runs' | 'experiments' | 'calibration' | 'golden'>('runs');

  // Summary Metrics
  const [summary, setSummary] = useState<EvaluationSummaryMetrics | null>(null);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [goldenCases, setGoldenCases] = useState<GoldenTestCase[]>([]);
  const [calibrationReport, setCalibrationReport] = useState<CalibrationReport | null>(null);

  // Experiment State
  const [runningExperiment, setRunningExperiment] = useState<string | null>(null);
  const [experimentResult, setExperimentResult] = useState<BenchmarkExperimentResponse | null>(null);

  // Calibration State
  const [isCalibrating, setIsCalibrating] = useState(false);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [summaryData, runsData, goldenData] = await Promise.all([
        api.getEvaluationSummary(),
        api.listEvaluationRuns(undefined, undefined, 50),
        api.getGoldenDataset(),
      ]);
      setSummary(summaryData);
      setRuns(runsData);
      setGoldenCases(goldenData);
    } catch (err: any) {
      setError(err?.detail || 'Failed to load evaluation metrics.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const handleRunExperiment = async (
    type: 'critic_on_off' | 'rag_ablation' | 'model_comparison'
  ) => {
    setRunningExperiment(type);
    setError(null);
    try {
      const res = await api.runBenchmarkExperiment(type, 4);
      setExperimentResult(res);
      // Refresh summary to reflect new benchmark runs
      const newSummary = await api.getEvaluationSummary();
      setSummary(newSummary);
      const newRuns = await api.listEvaluationRuns(undefined, undefined, 50);
      setRuns(newRuns);
    } catch (err: any) {
      setError(err?.detail || 'Benchmark experiment execution failed.');
    } finally {
      setRunningExperiment(null);
    }
  };

  const handleTriggerCalibration = async () => {
    setIsCalibrating(true);
    setError(null);
    try {
      const report = await api.getCalibrationReport();
      setCalibrationReport(report);
    } catch (err: any) {
      setError(err?.detail || 'Calibration analysis failed.');
    } finally {
      setIsCalibrating(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to="/"
              className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
              title="Back to Series"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-amber-400" />
              <h1 className="font-display font-bold text-lg text-white">
                Evaluation & Observability Engine
              </h1>
              <span className="px-2 py-0.5 text-xs font-semibold uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full">
                Phase 5 Active
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchDashboardData}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full space-y-8">
        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 flex items-center gap-3 text-sm">
            <ShieldAlert className="w-5 h-5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Top Metric Cards */}
        {summary && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {/* Pass Rate */}
            <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                <span>Pass Rate</span>
                <Award className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-white flex items-baseline gap-2">
                {(summary.pass_rate * 100).toFixed(1)}%
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-sans font-semibold ${
                    summary.pass_rate >= 0.85
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                  }`}
                >
                  {summary.pass_rate >= 0.85 ? 'PASSED' : 'REGRESSION'}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Total Runs: {summary.total_runs} (Target &ge; 85%)
              </p>
            </div>

            {/* Quality Score */}
            <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                <span>Avg Composite</span>
                <Flame className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-white flex items-baseline gap-2">
                {summary.avg_quality_score.toFixed(2)}
                <span className="text-xs text-slate-400 font-sans">/ 5.0</span>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Weighted 5D Rubric (Min pass 3.5)
              </p>
            </div>

            {/* Latency Percentiles */}
            <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                <span>Latency (p50 / p95)</span>
                <Clock className="w-4 h-4 text-sky-400" />
              </div>
              <div className="text-xl font-bold font-mono text-white flex items-baseline gap-2">
                {(summary.p50_latency_ms / 1000).toFixed(1)}s
                <span className="text-slate-500 text-sm">/</span>
                <span className="text-amber-400 font-mono">
                  {(summary.p95_latency_ms / 1000).toFixed(1)}s
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Per-episode generation time
              </p>
            </div>

            {/* Total Cost */}
            <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                <span>Est. Total Cost</span>
                <Coins className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-white">
                ${summary.total_cost_usd.toFixed(4)}
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Tokens: {(summary.total_prompt_tokens + summary.total_completion_tokens).toLocaleString()}
              </p>
            </div>

            {/* TTS Cache & Revision */}
            <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-2xl relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                <span>Efficiency</span>
                <Database className="w-4 h-4 text-purple-400" />
              </div>
              <div className="text-lg font-bold font-mono text-white">
                {(summary.avg_tts_cache_hit_rate * 100).toFixed(0)}% Cache Hit
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Avg Revisions: {summary.avg_revision_count.toFixed(1)} / 2
              </p>
            </div>
          </div>
        )}

        {/* Dimension Radar / Progress Bars */}
        {summary && (
          <div className="bg-slate-900/70 border border-slate-800 p-6 rounded-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-amber-400" />
                Production Rubric Dimension Averages
              </h2>
              <span className="text-xs text-slate-500">
                1.0 (Critical Failure) &mdash; 5.0 (Broadcast Masterpiece)
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
              {Object.entries(summary.dimension_averages).map(([dim, val]) => (
                <div key={dim} className="bg-slate-950/60 p-4 rounded-xl border border-slate-800/80">
                  <div className="flex items-center justify-between text-xs font-medium text-slate-400 mb-1 capitalize">
                    <span>{dim.replace('_', ' ')}</span>
                    <span className="font-mono text-white font-bold">{val.toFixed(2)}</span>
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        val >= 4.0
                          ? 'bg-emerald-400'
                          : val >= 3.5
                          ? 'bg-amber-400'
                          : 'bg-rose-400'
                      }`}
                      style={{ width: `${Math.min(100, (val / 5.0) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Failure Taxonomy */}
            {Object.keys(summary.failure_taxonomy).length > 0 && (
              <div className="pt-2 border-t border-slate-800/60 flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500 font-medium">Failure Taxonomy:</span>
                {Object.entries(summary.failure_taxonomy).map(([reason, count]) => (
                  <span
                    key={reason}
                    className="px-2.5 py-1 text-xs rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20 font-mono"
                  >
                    {reason.replace('_', ' ')}: {count}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Navigation */}
        <div className="border-b border-slate-800 flex items-center gap-6">
          <button
            onClick={() => setActiveTab('runs')}
            className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
              activeTab === 'runs'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Layers className="w-4 h-4" />
            Evaluation Trace Runs ({runs.length})
          </button>

          <button
            onClick={() => setActiveTab('experiments')}
            className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
              activeTab === 'experiments'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <FlaskConical className="w-4 h-4" />
            A/B Ablation Experiments
          </button>

          <button
            onClick={() => setActiveTab('calibration')}
            className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
              activeTab === 'calibration'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Scale className="w-4 h-4" />
            LLM Judge Calibration
          </button>

          <button
            onClick={() => setActiveTab('golden')}
            className={`pb-3 text-sm font-semibold transition border-b-2 flex items-center gap-2 ${
              activeTab === 'golden'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            Golden Dataset ({goldenCases.length})
          </button>
        </div>

        {/* TAB 1: Evaluation Runs */}
        {activeTab === 'runs' && (
          <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <h3 className="font-semibold text-sm text-slate-200">
                Recent Evaluation Traces (Per-Episode Granularity)
              </h3>
              <span className="text-xs text-slate-500">
                Graded via Pydantic 5D Rubric
              </span>
            </div>

            {runs.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-sm">
                No evaluation runs recorded yet. Generate or evaluate an episode to populate traces.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm text-slate-300">
                  <thead className="bg-slate-950/60 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
                    <tr>
                      <th className="py-3 px-4">Verdict</th>
                      <th className="py-3 px-4">Composite</th>
                      <th className="py-3 px-4">Char</th>
                      <th className="py-3 px-4">Plot</th>
                      <th className="py-3 px-4">Lang</th>
                      <th className="py-3 px-4">Pacing</th>
                      <th className="py-3 px-4">Safety</th>
                      <th className="py-3 px-4">Latency</th>
                      <th className="py-3 px-4">Cost</th>
                      <th className="py-3 px-4">Model</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono text-xs">
                    {runs.map((r) => (
                      <tr key={r.id} className="hover:bg-slate-800/30 transition">
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-sans font-semibold ${
                              r.passed
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                            }`}
                          >
                            {r.passed ? (
                              <CheckCircle2 className="w-3 h-3" />
                            ) : (
                              <XCircle className="w-3 h-3" />
                            )}
                            {r.verdict}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-bold text-white">
                          {r.composite_score.toFixed(2)}
                        </td>
                        <td className="py-3 px-4">{r.character_consistency.toFixed(1)}</td>
                        <td className="py-3 px-4">{r.plot_coherence.toFixed(1)}</td>
                        <td className="py-3 px-4">{r.language_naturalness.toFixed(1)}</td>
                        <td className="py-3 px-4">{r.pacing.toFixed(1)}</td>
                        <td className="py-3 px-4">
                          <span
                            className={r.safety < 4.0 ? 'text-rose-400 font-bold' : ''}
                          >
                            {r.safety.toFixed(1)}
                          </span>
                        </td>
                        <td className="py-3 px-4">{(r.latency_ms / 1000).toFixed(2)}s</td>
                        <td className="py-3 px-4 text-emerald-400">
                          ${r.estimated_cost_usd.toFixed(5)}
                        </td>
                        <td className="py-3 px-4 text-slate-400 font-sans">{r.model_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: A/B Experiments */}
        {activeTab === 'experiments' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Experiment 1: Critic Loop */}
              <div className="bg-slate-900/70 border border-slate-800 p-6 rounded-2xl flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center gap-2 text-amber-400 text-xs font-semibold uppercase tracking-wider mb-2">
                    <FlaskConical className="w-4 h-4" />
                    Experiment 1
                  </div>
                  <h3 className="font-bold text-base text-white">
                    Critic Feedback Loop: ON vs OFF
                  </h3>
                  <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                    Quantifies quality uplift of the LangGraph conditional revision loop vs raw single-pass generation. Measures bounded revision costs.
                  </p>
                </div>
                <button
                  onClick={() => handleRunExperiment('critic_on_off')}
                  disabled={runningExperiment !== null}
                  className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {runningExperiment === 'critic_on_off' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4 fill-current" />
                  )}
                  Run Critic Ablation
                </button>
              </div>

              {/* Experiment 2: RAG Retrieval */}
              <div className="bg-slate-900/70 border border-slate-800 p-6 rounded-2xl flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center gap-2 text-sky-400 text-xs font-semibold uppercase tracking-wider mb-2">
                    <FlaskConical className="w-4 h-4" />
                    Experiment 2
                  </div>
                  <h3 className="font-bold text-base text-white">
                    Story Bible RAG: pgvector ON vs OFF
                  </h3>
                  <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                    Evaluates multi-episode lore and character development continuity when hybrid vector retrieval is enabled vs cold start.
                  </p>
                </div>
                <button
                  onClick={() => handleRunExperiment('rag_ablation')}
                  disabled={runningExperiment !== null}
                  className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-sky-500 hover:bg-sky-400 text-slate-950 transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {runningExperiment === 'rag_ablation' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4 fill-current" />
                  )}
                  Run RAG Ablation
                </button>
              </div>

              {/* Experiment 3: Model Comparison */}
              <div className="bg-slate-900/70 border border-slate-800 p-6 rounded-2xl flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center gap-2 text-purple-400 text-xs font-semibold uppercase tracking-wider mb-2">
                    <FlaskConical className="w-4 h-4" />
                    Experiment 3
                  </div>
                  <h3 className="font-bold text-base text-white">
                    Model A vs Model B (Pro vs Flash)
                  </h3>
                  <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                    Direct benchmark pitting Gemini 1.5 Pro against Gemini 2.0 Flash to evaluate quality/cost tradeoffs on audio drama writing.
                  </p>
                </div>
                <button
                  onClick={() => handleRunExperiment('model_comparison')}
                  disabled={runningExperiment !== null}
                  className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-purple-500 hover:bg-purple-400 text-slate-950 transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {runningExperiment === 'model_comparison' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4 fill-current" />
                  )}
                  Run Model Comparison
                </button>
              </div>
            </div>

            {/* Experiment Result View */}
            {experimentResult && (
              <div className="bg-slate-900/90 border border-amber-500/30 p-6 rounded-2xl space-y-6">
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div>
                    <span className="text-xs font-semibold uppercase text-amber-400">
                      Experiment Complete
                    </span>
                    <h3 className="text-lg font-bold text-white mt-1">
                      {experimentResult.title}
                    </h3>
                  </div>
                  <span className="text-xs font-mono text-slate-400">
                    ID: {experimentResult.experiment_id.slice(0, 8)}
                  </span>
                </div>

                {/* Variant Comparison Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {experimentResult.variants.map((v, idx) => (
                    <div
                      key={v.variant_name}
                      className="bg-slate-950/70 border border-slate-800 p-5 rounded-xl space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold uppercase text-slate-400">
                          Variant {idx === 0 ? 'A' : 'B'}
                        </span>
                        <span className="text-xs font-bold text-white font-mono">
                          {v.sample_count} runs
                        </span>
                      </div>
                      <h4 className="font-bold text-base text-white">{v.variant_name}</h4>

                      <div className="grid grid-cols-2 gap-3 text-xs font-mono pt-2 border-t border-slate-800/80">
                        <div>
                          <span className="text-slate-500 block">Avg Composite</span>
                          <span className="text-base font-bold text-amber-400">
                            {v.avg_composite_score.toFixed(2)}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-500 block">Pass Rate</span>
                          <span className="text-base font-bold text-emerald-400">
                            {(v.pass_rate * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-500 block">Avg Latency</span>
                          <span>{(v.avg_latency_ms / 1000).toFixed(2)}s</span>
                        </div>
                        <div>
                          <span className="text-slate-500 block">Cost / Ep</span>
                          <span className="text-emerald-400">
                            ${v.avg_cost_usd.toFixed(5)}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Delta Analysis */}
                <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 text-xs space-y-2">
                  <div className="font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                    Delta & Tradeoff Analysis
                  </div>
                  <pre className="text-slate-300 font-mono overflow-x-auto p-2 bg-slate-900 rounded">
                    {JSON.stringify(experimentResult.delta_analysis, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: LLM Judge Calibration */}
        {activeTab === 'calibration' && (
          <div className="bg-slate-900/60 border border-slate-800 p-6 rounded-2xl space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h3 className="font-bold text-base text-white">
                  Ground-Truth Human Calibration Workflow
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Computes Spearman rank correlation (&rho;), quadratic weighted Cohen&apos;s kappa (&kappa;), and MAE against 30 expert human-labeled audio scripts.
                </p>
              </div>

              <button
                onClick={handleTriggerCalibration}
                disabled={isCalibrating}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-500 hover:bg-emerald-400 text-slate-950 transition disabled:opacity-50"
              >
                {isCalibrating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Scale className="w-4 h-4" />
                )}
                Run Calibration Analysis
              </button>
            </div>

            {calibrationReport ? (
              <div className="space-y-6">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="p-4 bg-slate-950/70 border border-slate-800 rounded-xl">
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Calibration Status
                    </span>
                    <span className="text-lg font-bold text-emerald-400 mt-1 block">
                      {calibrationReport.calibration_status}
                    </span>
                    <span className="text-xs text-slate-500">
                      Tested on {calibrationReport.total_samples} human samples
                    </span>
                  </div>

                  <div className="p-4 bg-slate-950/70 border border-slate-800 rounded-xl">
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Spearman &rho; (Composite)
                    </span>
                    <span className="text-lg font-bold text-amber-400 mt-1 font-mono block">
                      {calibrationReport.spearman_correlation.composite?.toFixed(4) || 'N/A'}
                    </span>
                    <span className="text-xs text-slate-500">
                      Rank monotonicity with human critics
                    </span>
                  </div>

                  <div className="p-4 bg-slate-950/70 border border-slate-800 rounded-xl">
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">
                      Weighted Cohen&apos;s &kappa; (Coherence)
                    </span>
                    <span className="text-lg font-bold text-sky-400 mt-1 font-mono block">
                      {calibrationReport.weighted_cohens_kappa.plot_coherence?.toFixed(4) || 'N/A'}
                    </span>
                    <span className="text-xs text-slate-500">
                      Inter-rater agreement index
                    </span>
                  </div>
                </div>

                {/* Per Dimension Correlation Table */}
                <div className="overflow-x-auto rounded-xl border border-slate-800">
                  <table className="w-full text-left text-xs font-mono text-slate-300">
                    <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider">
                      <tr>
                        <th className="py-2.5 px-4">Dimension</th>
                        <th className="py-2.5 px-4">Spearman &rho;</th>
                        <th className="py-2.5 px-4">Weighted Cohen&apos;s &kappa;</th>
                        <th className="py-2.5 px-4">Mean Abs Error (MAE)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 bg-slate-950/40">
                      {Object.keys(calibrationReport.spearman_correlation).map((dim) => (
                        <tr key={dim} className="hover:bg-slate-800/30">
                          <td className="py-2.5 px-4 font-sans font-semibold capitalize text-white">
                            {dim.replace('_', ' ')}
                          </td>
                          <td className="py-2.5 px-4 text-amber-400">
                            {calibrationReport.spearman_correlation[dim]?.toFixed(4)}
                          </td>
                          <td className="py-2.5 px-4 text-sky-400">
                            {calibrationReport.weighted_cohens_kappa[dim]?.toFixed(4)}
                          </td>
                          <td className="py-2.5 px-4 text-emerald-400">
                            {calibrationReport.mean_absolute_error[dim]?.toFixed(4)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Recommendations and Weaknesses */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="p-4 bg-slate-950/60 rounded-xl border border-slate-800 space-y-2">
                    <span className="font-semibold text-rose-400 uppercase tracking-wider block">
                      Identified Weaknesses & Biases
                    </span>
                    <ul className="space-y-1 text-slate-400 list-disc list-inside">
                      {calibrationReport.identified_weaknesses.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="p-4 bg-slate-950/60 rounded-xl border border-slate-800 space-y-2">
                    <span className="font-semibold text-emerald-400 uppercase tracking-wider block">
                      Engineering Recommendations
                    </span>
                    <ul className="space-y-1 text-slate-400 list-disc list-inside">
                      {calibrationReport.recommendations.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-12 text-slate-500 text-sm">
                Click &quot;Run Calibration Analysis&quot; above to grade the 30 ground-truth human benchmark scripts and inspect statistical correlation coefficients.
              </div>
            )}
          </div>
        )}

        {/* TAB 4: Golden Dataset */}
        {activeTab === 'golden' && (
          <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden space-y-4 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-bold text-base text-white">
                  Curated Multilingual Golden Dataset
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  35–50 standardized premises spanning Hindi, Hinglish, and English across genres (supernatural, corporate, drama, romance, sci-fi).
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {goldenCases.map((gc) => (
                <div
                  key={gc.id}
                  className="bg-slate-950/70 border border-slate-800 p-4 rounded-xl flex flex-col justify-between space-y-3"
                >
                  <div>
                    <div className="flex items-center justify-between text-xs mb-2">
                      <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-semibold uppercase">
                        {gc.target_language}
                      </span>
                      <span className="text-slate-500 font-mono">{gc.genre}</span>
                    </div>
                    <h4 className="font-bold text-sm text-white">{gc.title}</h4>
                    <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                      {gc.premise}
                    </p>
                  </div>

                  <div className="pt-2 border-t border-slate-800/80 text-[11px] text-slate-500 flex items-center justify-between">
                    <span>Target: {gc.target_duration_minutes} min</span>
                    <span>Cast: {gc.expected_characters.join(', ')}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
