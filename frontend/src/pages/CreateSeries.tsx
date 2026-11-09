import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { ProblemDetails } from '../types';
import { ArrowLeft, Headphones, Loader2, Sparkles } from 'lucide-react';

export const CreateSeries: React.FC = () => {
  const [title, setTitle] = useState('');
  const [genre, setGenre] = useState('drama');
  const [targetLanguage, setTargetLanguage] = useState<'hindi' | 'hinglish' | 'english'>('hindi');
  const [logline, setLogline] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const created = await api.createSeries({
        title,
        genre,
        target_language: targetLanguage,
        logline,
      });
      navigate(`/series/${created.id}`);
    } catch (err) {
      const problem = err as ProblemDetails;
      setError(problem.detail || 'Failed to create series. Please verify your inputs.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-4xl mx-auto px-4 h-16 flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Series Roster
          </Link>
          <div className="flex items-center gap-2">
            <Headphones className="w-5 h-5 text-amber-400" />
            <span className="font-display font-bold text-lg text-white">कथा Studio</span>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-2xl mx-auto px-4 py-12 w-full">
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-amber-500/10 border border-amber-500/20 rounded-full text-xs font-semibold text-amber-400 mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            Story Bible Genesis
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white font-display">
            Create Audio Series
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Establish the world premise, core narrative tension, and target linguistic dialect.
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-950/50 border border-red-500/40 text-red-300 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6 bg-slate-900/40 p-8 rounded-2xl border border-slate-800 backdrop-blur-sm">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Series Title
            </label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Purani Dilli Ki Dastak (पुरानी दिल्ली की दस्तक)"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500 transition-colors"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Genre
              </label>
              <select
                value={genre}
                onChange={(e) => setGenre(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500 transition-colors capitalize"
              >
                <option value="drama">Drama</option>
                <option value="thriller">Psychological Thriller</option>
                <option value="mystery">Crime & Mystery</option>
                <option value="horror">Supernatural Horror</option>
                <option value="mythological">Mythological Fantasy</option>
                <option value="sci-fi">Sci-Fi & Cyberpunk</option>
                <option value="romance">Urban Romance</option>
                <option value="comedy">Dark Comedy</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Linguistic Dialect
              </label>
              <select
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value as any)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500 transition-colors capitalize"
              >
                <option value="hindi">Hindi (हिंदी — Authentic & Idiomatic)</option>
                <option value="hinglish">Hinglish (Urban Conversational Code-Switching)</option>
                <option value="english">English (Dramatic Indian Accented)</option>
              </select>
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="block text-sm font-medium text-slate-300">
                Series Logline & Core Premise
              </label>
              <span className="text-xs text-slate-500">{logline.length}/2000</span>
            </div>
            <textarea
              required
              rows={4}
              maxLength={2000}
              value={logline}
              onChange={(e) => setLogline(e.target.value)}
              placeholder="Describe the central dramatic conflict, the protagonist's dilemma, and the recurring acoustic atmosphere..."
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500 transition-colors resize-none text-sm leading-relaxed"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-3">
            <Link
              to="/"
              className="px-5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-slate-950 bg-amber-500 hover:bg-amber-400 transition-all shadow-lg shadow-amber-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generating Universe...
                </>
              ) : (
                'Create Series'
              )}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
};

