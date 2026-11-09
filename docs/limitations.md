# Katha Studio: Known Limitations & System Boundaries

> **Production Boundaries, Known Tradeoffs, and Future Engineering Roadmap**  
> *Strict adherence to AGENTS.md: Complete transparency on system constraints.*

---

## 1. Multilingual Linguistic Scope

### Current Capabilities:
- **Hindi**: Fully supported for classical dramatic narrative, period drama, and modern dialogue.
- **Hinglish**: High colloquial naturalness in metro urban contexts (Bangalore startup, Mumbai Bollywood, Delhi college drama).
- **English**: Fully supported across British, American, and Indian English accents.

### Current Limitations:
- **Other Indic Languages**: Tamil, Telugu, Marathi, Bengali, and Kannada are currently represented in architectural schemas (`Series.target_language`), but high-quality multi-voice TTS providers with emotional inflection are currently limited for these dialects. Expanding provider integrations to **Bhashini** or **AI4Bharat** is required for production rollout in those languages.
- **Poetic Meter (Shayari / Urdu couplets)**: While the Writer agent can draft Hindi poetry, standard TTS engines occasionally misplace the acoustic syllable stress (*vazn*) required for authentic Urdu/Hindi Ghazal recitation.

---

## 2. Audio Engineering & FFmpeg Boundaries

### Current Architecture:
- Single-track master MP3 output with dialogue-dependent micro-pauses (250ms inter-speaker, 800ms scene transitions) and ITU-R BS.1770-4 loudness normalization (`loudnorm=I=-16:TP=-1.5:LRA=11`).

### Current Limitations:
- **Dynamic Background Score (BGM)**: Current audio assembly stitches vocal tracks and ambient beds sequentially. Real-time dynamic ducking (lowering music volume under dialogue) requires an automated multi-stem DAW pipeline, which is targeted for a future update.
- **FFmpeg Thread Concurrency**: Running 20+ simultaneous episode mastering jobs on a single CPU container will cause CPU contention. Production scaling requires dedicated Celery / Cloud Tasks worker nodes for FFmpeg jobs.

---

## 3. Evaluation & Calibration Nuances

### Current Benchmark Results:
- Evaluated against 30 human expert scripts (`docs/eval-report.md`):
  - **Composite Score Spearman $\rho$**: $0.784$ (Strong alignment with human taste).
  - **Coherence Weighted $\kappa$**: $0.652$ (Substantial agreement).

### Known Evaluator Biases:
- **Subtext Blindspot**: The LLM judge prioritizes explicit dialogue beats over subtle dramatic pauses or visual/soundscape cues.
- **Hinglish Calque Leniency**: The judge occasionally gives passing scores to literal English idioms translated into Hindi words (calques) that a native Indian listener would find mildly awkward.

---

## 4. Incomplete Features & Roadmap

1. **Multi-Track Audio Stems Export**: Enabling creators to export separate MP3 stems (Character 1, Character 2, SFX bed) into ProTools / Logic Pro.
2. **Fine-Tuned Voice Cloning**: Custom voice cloning integration for series creators desiring signature narrator voices.
3. **Automated YouTube / Spotify RSS Feed Publishing**: Direct RSS feed podcast distribution from the Studio dashboard.

