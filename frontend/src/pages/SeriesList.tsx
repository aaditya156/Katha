import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { Series } from '../types';
import {
  Headphones,
  Plus,
  LogOut,
  Trash2,
  Globe,
  Radio,
  Sparkles,
  Loader2,
  Activity,
} from 'lucide-react';

export const SeriesList: React.FC = () => {
  const { user, logout } = useAuth();
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const fetchSeries = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.listSeries();
      setSeriesList(data);
    } catch (err) {
      setError('Failed to fetch series list.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSeries();
  }, []);

  const handleDelete = async (id: string, title: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`Are you sure you want to delete "${title}" and all its episodes?`)) {
      try {
        await api.deleteSeries(id);
        setSeriesList((prev) => prev.filter((s) => s.id !== id));
      } catch {
        alert('Failed to delete series.');
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/10 rounded-xl border border-amber-500/20 text-amber-400">
              <Headphones className="w-5 h-5" />
            </div>
            <div>
              <span className="font-display font-bold text-xl tracking-tight text-white">
                कथा Studio
              </span>
              <span className="ml-2 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-full">
                Phase 1 Scaffolding
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-400 hidden sm:inline-block">
              {user?.full_name || user?.email}
            </span>
            <Link
              to="/evaluations"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
              title="Evaluation & Observability Dashboard"
            >
              <Activity className="w-4 h-4 text-amber-400" />
              <span className="hidden md:inline">Evaluations & Metrics</span>
            </Link>
            <Link
              to="/series/new"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 transition-all shadow-md shadow-amber-500/10"
            >
              <Plus className="w-4 h-4" />
              New Series
            </Link>
            <button
              onClick={logout}
              title="Sign Out"
              className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 w-full">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Audio Drama Series</h1>
            <p className="text-sm text-slate-400 mt-1">
              Manage your episodic story worlds, character rosters, and multivoice narratives.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-slate-500">
            <Loader2 className="w-8 h-8 animate-spin text-amber-400" />
            <span className="ml-3 text-sm">Loading studio series...</span>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-950/40 border border-red-500/30 rounded-xl text-red-300 text-sm">
            {error}
          </div>
        ) : seriesList.length === 0 ? (
          <div className="border border-dashed border-slate-800 rounded-2xl p-12 text-center bg-slate-900/30">
            <div className="w-16 h-16 mx-auto mb-4 bg-amber-500/10 text-amber-400 rounded-2xl flex items-center justify-center border border-amber-500/20">
              <Sparkles className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-semibold text-white">No Series Yet</h3>
            <p className="text-sm text-slate-400 mt-1 max-w-sm mx-auto">
              Start by launching your first audio saga in Hindi, Hinglish, or English.
            </p>
            <Link
              to="/series/new"
              className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 transition-all shadow-lg shadow-amber-500/20"
            >
              <Plus className="w-4 h-4" />
              Create First Series
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {seriesList.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate(`/series/${item.id}`)}
                className="group relative bg-slate-900/60 hover:bg-slate-900 border border-slate-800 hover:border-amber-500/40 rounded-2xl p-6 transition-all cursor-pointer shadow-lg hover:shadow-amber-500/5 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <span className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-slate-800 text-amber-400 border border-slate-700 capitalize">
                      {item.genre}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1 text-xs text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded-md">
                        <Globe className="w-3 h-3" />
                        <span className="capitalize">{item.target_language}</span>
                      </span>
                      <button
                        onClick={(e) => handleDelete(item.id, item.title, e)}
                        className="text-slate-500 hover:text-red-400 transition-colors p-1"
                        title="Delete Series"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  <h3 className="text-lg font-bold text-white group-hover:text-amber-400 transition-colors line-clamp-1 font-display">
                    {item.title}
                  </h3>

                  <p className="text-sm text-slate-400 mt-2 line-clamp-3 leading-relaxed">
                    {item.logline}
                  </p>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <Radio className="w-3.5 h-3.5 text-amber-400" />
                    Audio Series
                  </span>
                  <span className="inline-flex items-center gap-1 text-amber-400 group-hover:translate-x-1 transition-transform font-medium">
                    Open Studio →
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
