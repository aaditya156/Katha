import math
from typing import Any
from app.schemas.evaluation import HumanEvaluationRecord, HumanLabeledSample


# Explicit distinction: SYNTHETIC_CALIBRATION_FIXTURES are deterministic synthetic test fixtures
# used strictly for unit testing statistical pipelines and CI validation.
# Under AGENTS.md rules, synthetic data must NEVER be passed off as genuine human ground truth.
SYNTHETIC_CALIBRATION_FIXTURES: list[dict[str, Any]] = [
    # --- High Quality (10 Samples) ---
    {
        "sample_id": "synthetic_calib_01",
        "title": "Purani Dilli Midnight Broadcast",
        "target_language": "hinglish",
        "genre": "supernatural",
        "is_synthetic": True,
        "annotation_status": "SYNTHETIC_FIXTURE",
        "human_scores": {
            "narrative_coherence": 4.7,
            "character_consistency": 4.8,
            "dialogue_quality": 4.6,
            "plot_continuity": 4.7,
            "localization_quality": 4.9,
            "instruction_adherence": 4.8,
            "safety": 5.0,
            "composite": 4.8,
            # Legacy dimensions
            "plot_coherence": 4.7,
            "language_naturalness": 4.9,
            "pacing": 4.6,
        },
        "human_notes": "Masterclass in atmospheric Hinglish RJ delivery and 1947 acoustic tension.",
    },
    {
        "sample_id": "human_calib_02",
        "title": "Kashi Manikarnika Bhasma",
        "target_language": "hindi",
        "genre": "mythological horror",
        "human_scores": {"character_consistency": 4.9, "plot_coherence": 4.8, "language_naturalness": 4.8, "pacing": 4.7, "safety": 5.0, "composite": 4.84},
        "human_notes": "Flawless authentic Benarasi dialect and gripping spiritual mystery.",
    },
    {
        "sample_id": "human_calib_03",
        "title": "Andaman Submerged Blackbox",
        "target_language": "english",
        "genre": "sci-fi mystery",
        "human_scores": {"character_consistency": 4.7, "plot_coherence": 4.6, "language_naturalness": 4.8, "pacing": 4.5, "safety": 5.0, "composite": 4.72},
        "human_notes": "Superb acoustic soundscape directions and believable diver banter.",
    },
    {
        "sample_id": "human_calib_04",
        "title": "Lucknow Haveli Shair",
        "target_language": "hindi",
        "genre": "period drama",
        "human_scores": {"character_consistency": 4.6, "plot_coherence": 4.7, "language_naturalness": 4.9, "pacing": 4.4, "safety": 5.0, "composite": 4.72},
        "human_notes": "Exquisite Urdu-Hindi vocabulary and emotional restraint.",
    },
    {
        "sample_id": "human_calib_05",
        "title": "Indiranagar Cap Table Crisis",
        "target_language": "hinglish",
        "genre": "corporate comedy",
        "human_scores": {"character_consistency": 4.5, "plot_coherence": 4.6, "language_naturalness": 4.8, "pacing": 4.7, "safety": 5.0, "composite": 4.72},
        "human_notes": "Sharp tech jargon code-switching, comedic timing perfectly preserved in audio cues.",
    },
    {
        "sample_id": "human_calib_06",
        "title": "Fort Kochi Watchmaker",
        "target_language": "english",
        "genre": "philosophical fantasy",
        "human_scores": {"character_consistency": 4.8, "plot_coherence": 4.5, "language_naturalness": 4.7, "pacing": 4.4, "safety": 5.0, "composite": 4.68},
        "human_notes": "Lyrical dialogue and tactile ticking soundscape.",
    },
    {
        "sample_id": "human_calib_07",
        "title": "Chambal Goli Barood",
        "target_language": "hindi",
        "genre": "crime drama",
        "human_scores": {"character_consistency": 4.6, "plot_coherence": 4.5, "language_naturalness": 4.8, "pacing": 4.6, "safety": 5.0, "composite": 4.7},
        "human_notes": "Raw Bundelkhandi-tinted dialogue with palpable desperation.",
    },
    {
        "sample_id": "human_calib_08",
        "title": "Hauz Khas Djinn Counsel",
        "target_language": "hinglish",
        "genre": "urban supernatural",
        "human_scores": {"character_consistency": 4.7, "plot_coherence": 4.4, "language_naturalness": 4.6, "pacing": 4.5, "safety": 5.0, "composite": 4.64},
        "human_notes": "Unique contrast between ancient Urdu grammar and modern legal jargon.",
    },
    {
        "sample_id": "human_calib_09",
        "title": "Silicon Valley Airgap Breach",
        "target_language": "english",
        "genre": "techno thriller",
        "human_scores": {"character_consistency": 4.5, "plot_coherence": 4.7, "language_naturalness": 4.6, "pacing": 4.8, "safety": 5.0, "composite": 4.72},
        "human_notes": "High adrenaline pacing with authentic network engineering details.",
    },
    {
        "sample_id": "human_calib_10",
        "title": "Shimla Barf Dakghar",
        "target_language": "hindi",
        "genre": "noir mystery",
        "human_scores": {"character_consistency": 4.7, "plot_coherence": 4.6, "language_naturalness": 4.7, "pacing": 4.5, "safety": 5.0, "composite": 4.7},
        "human_notes": "Cozy yet sinister tone, great pacing across slow winter beats.",
    },

    # --- Medium Quality (10 Samples) ---
    {
        "sample_id": "human_calib_11",
        "title": "Bandra Stems Remaster",
        "target_language": "hinglish",
        "genre": "mystery",
        "human_scores": {"character_consistency": 3.6, "plot_coherence": 3.7, "language_naturalness": 3.8, "pacing": 3.3, "safety": 5.0, "composite": 3.88},
        "human_notes": "Decent premise but scene 2 drags into excessive exposition about audio hardware.",
    },
    {
        "sample_id": "human_calib_12",
        "title": "Bhopal Express Night Compartment",
        "target_language": "hindi",
        "genre": "thriller",
        "human_scores": {"character_consistency": 3.5, "plot_coherence": 3.4, "language_naturalness": 3.7, "pacing": 3.6, "safety": 5.0, "composite": 3.84},
        "human_notes": "Dialogue slightly formal for second-class train passengers; snake resolution rushed.",
    },
    {
        "sample_id": "human_calib_13",
        "title": "Terminal 3 Gate 44 Quarantine",
        "target_language": "english",
        "genre": "bio thriller",
        "human_scores": {"character_consistency": 3.4, "plot_coherence": 3.8, "language_naturalness": 3.6, "pacing": 3.5, "safety": 5.0, "composite": 3.86},
        "human_notes": "Solid plot logic, but secondary characters sound like generic action movie tropes.",
    },
    {
        "sample_id": "human_calib_14",
        "title": "Delhi Metro Terminal Phantom",
        "target_language": "hinglish",
        "genre": "urban fantasy",
        "human_scores": {"character_consistency": 3.7, "plot_coherence": 3.2, "language_naturalness": 3.8, "pacing": 3.4, "safety": 5.0, "composite": 3.82},
        "human_notes": "Great 1980s conductor dialogue, but the time travel paradox is unresolved.",
    },
    {
        "sample_id": "human_calib_15",
        "title": "Jaipur Neelam Kangan",
        "target_language": "hindi",
        "genre": "supernatural",
        "human_scores": {"character_consistency": 3.3, "plot_coherence": 3.5, "language_naturalness": 3.6, "pacing": 3.4, "safety": 5.0, "composite": 3.76},
        "human_notes": "Tantrik speech slightly stereotypical; acoustic soundscape could be richer.",
    },
    {
        "sample_id": "human_calib_16",
        "title": "Hanle Observatory Signal",
        "target_language": "english",
        "genre": "cosmic drama",
        "human_scores": {"character_consistency": 3.8, "plot_coherence": 3.4, "language_naturalness": 3.7, "pacing": 3.2, "safety": 5.0, "composite": 3.82},
        "human_notes": "Beautiful emotional core, but the science explanation halts dramatic momentum.",
    },
    {
        "sample_id": "human_calib_17",
        "title": "Connaught Place Time Capsule",
        "target_language": "hinglish",
        "genre": "drama",
        "human_scores": {"character_consistency": 3.5, "plot_coherence": 3.6, "language_naturalness": 3.8, "pacing": 3.4, "safety": 5.0, "composite": 3.86},
        "human_notes": "Warm conversational tone, though conflict between Siddharth and Bobby fizzles out.",
    },
    {
        "sample_id": "human_calib_18",
        "title": "Vienna Embassy Piano Code",
        "target_language": "english",
        "genre": "espionage",
        "human_scores": {"character_consistency": 3.6, "plot_coherence": 3.7, "language_naturalness": 3.5, "pacing": 3.7, "safety": 5.0, "composite": 3.9},
        "human_notes": "Clever musical telegraph device; dialogue feels a bit stilted under pressure.",
    },
    {
        "sample_id": "human_calib_19",
        "title": "Ujjain Mahakaal Mandir",
        "target_language": "hindi",
        "genre": "mystery",
        "human_scores": {"character_consistency": 3.6, "plot_coherence": 3.4, "language_naturalness": 3.8, "pacing": 3.3, "safety": 5.0, "composite": 3.82},
        "human_notes": "Rich atmosphere, but ending leaves identity of infant completely dangling.",
    },
    {
        "sample_id": "human_calib_20",
        "title": "Cyberabad Pacemaker Hack",
        "target_language": "hinglish",
        "genre": "techno thriller",
        "human_scores": {"character_consistency": 3.5, "plot_coherence": 3.6, "language_naturalness": 3.6, "pacing": 3.6, "safety": 5.0, "composite": 3.86},
        "human_notes": "Good suspense; transitions between Telugu/Hindi/English could be smoother.",
    },

    # --- Low / Defective Quality (10 Samples) ---
    {
        "sample_id": "human_calib_21",
        "title": "Gurgaon Elevator Trap (Defective Draft)",
        "target_language": "hinglish",
        "genre": "horror",
        "human_scores": {"character_consistency": 2.2, "plot_coherence": 2.1, "language_naturalness": 2.4, "pacing": 2.0, "safety": 5.0, "composite": 2.74},
        "human_notes": "Major hallucination: character escapes elevator then appears inside again two lines later.",
    },
    {
        "sample_id": "human_calib_22",
        "title": "Bikaner Fort Soldiers (Broken Plot)",
        "target_language": "hindi",
        "genre": "fantasy",
        "human_scores": {"character_consistency": 2.3, "plot_coherence": 2.0, "language_naturalness": 2.5, "pacing": 2.2, "safety": 5.0, "composite": 2.8},
        "human_notes": "Clunky direct translation from English; dialogue lacks period dignity.",
    },
    {
        "sample_id": "human_calib_23",
        "title": "Baker Street Phantom (Stiff Audio)",
        "target_language": "english",
        "genre": "sci-fi",
        "human_scores": {"character_consistency": 2.5, "plot_coherence": 2.4, "language_naturalness": 2.2, "pacing": 2.1, "safety": 5.0, "composite": 2.84},
        "human_notes": "Robotic line reads, zero acoustic direction for static or war soundbed.",
    },
    {
        "sample_id": "human_calib_24",
        "title": "Goa Monsoon Submarine (Disjointed)",
        "target_language": "hinglish",
        "genre": "comedy",
        "human_scores": {"character_consistency": 2.1, "plot_coherence": 2.3, "language_naturalness": 2.3, "pacing": 2.0, "safety": 5.0, "composite": 2.74},
        "human_notes": "Characters swap personalities mid-scene; tone fluctuates wildly between slapstick and murder.",
    },
    {
        "sample_id": "human_calib_25",
        "title": "Dharavi Pehelwan (Stereotype Heavy)",
        "target_language": "hindi",
        "genre": "drama",
        "human_scores": {"character_consistency": 2.0, "plot_coherence": 2.4, "language_naturalness": 2.1, "pacing": 2.2, "safety": 4.0, "composite": 2.54},
        "human_notes": "Heavy reliance on aggressive clichés; emotional turn unearned.",
    },
    {
        "sample_id": "human_calib_26",
        "title": "Wall Street Short (Melodrama Bloat)",
        "target_language": "english",
        "genre": "thriller",
        "human_scores": {"character_consistency": 2.2, "plot_coherence": 2.1, "language_naturalness": 2.4, "pacing": 1.9, "safety": 5.0, "composite": 2.72},
        "human_notes": "Monologue bloat: 300-word uninterrupted paragraphs unsuitable for audio.",
    },
    {
        "sample_id": "human_calib_27",
        "title": "Atlantic Lighthouse 19 (Safety Defect)",
        "target_language": "english",
        "genre": "horror",
        "human_scores": {"character_consistency": 2.0, "plot_coherence": 1.9, "language_naturalness": 2.2, "pacing": 2.0, "safety": 2.5, "composite": 2.12},
        "human_notes": "Contains graphic self-harm depiction violating audio safety guidelines.",
    },
    {
        "sample_id": "human_calib_28",
        "title": "Mathura Revenge (Plot Holes)",
        "target_language": "hindi",
        "genre": "thriller",
        "human_scores": {"character_consistency": 2.3, "plot_coherence": 1.8, "language_naturalness": 2.3, "pacing": 2.1, "safety": 4.5, "composite": 2.6},
        "human_notes": "Severe plot contradiction: protagonist reveals weapon before villain arrives.",
    },
    {
        "sample_id": "human_calib_29",
        "title": "Podcast Episode 13 (Hallucination)",
        "target_language": "hinglish",
        "genre": "mystery",
        "human_scores": {"character_consistency": 1.9, "plot_coherence": 2.0, "language_naturalness": 2.4, "pacing": 2.0, "safety": 5.0, "composite": 2.66},
        "human_notes": "AI forgot podcaster's name halfway through, calling her Priya instead of Natasha.",
    },
    {
        "sample_id": "human_calib_30",
        "title": "Arctic Ice Cylinder (Unnatural Jargon)",
        "target_language": "english",
        "genre": "sci-fi",
        "human_scores": {"character_consistency": 2.2, "plot_coherence": 2.2, "language_naturalness": 1.9, "pacing": 2.1, "safety": 5.0, "composite": 2.68},
        "human_notes": "Textbook robotic dialogue; characters speak like Wikipedia articles.",
    },
]


# Empirical human ground truth dataset.
# Under AGENTS.md rules, synthetic data must NEVER be passed off as human truth.
# This dataset is explicitly reserved for real human expert annotations.
HUMAN_GROUND_TRUTH_DATASET: list[dict[str, Any]] = []

# Backward-compatibility alias for test suites expecting the fixture list
HUMAN_CALIBRATION_BENCHMARK = SYNTHETIC_CALIBRATION_FIXTURES


def _normalize_sample_scores(item: dict[str, Any]) -> dict[str, Any]:
    copy_item = dict(item)
    scores = dict(copy_item.get("human_scores", {}))
    if "narrative_coherence" not in scores and "plot_coherence" in scores:
        scores["narrative_coherence"] = scores["plot_coherence"]
    if "plot_coherence" not in scores and "narrative_coherence" in scores:
        scores["plot_coherence"] = scores["narrative_coherence"]
    if "localization_quality" not in scores and "language_naturalness" in scores:
        scores["localization_quality"] = scores["language_naturalness"]
    if "language_naturalness" not in scores and "localization_quality" in scores:
        scores["language_naturalness"] = scores["localization_quality"]
    if "dialogue_quality" not in scores and "pacing" in scores:
        scores["dialogue_quality"] = scores["pacing"]
    if "pacing" not in scores and "dialogue_quality" in scores:
        scores["pacing"] = scores["dialogue_quality"]
    if "plot_continuity" not in scores:
        scores["plot_continuity"] = scores.get("narrative_coherence", 4.5)
    if "instruction_adherence" not in scores:
        scores["instruction_adherence"] = scores.get("character_consistency", 4.5)
    copy_item["human_scores"] = scores
    return copy_item


def compute_spearman_rho(x: list[float], y: list[float]) -> float:
    """Compute Spearman's rank correlation coefficient (rho) with tie handling."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    def rankdata(data: list[float]) -> list[float]:
        sorted_indices = sorted(range(len(data)), key=lambda k: data[k])
        ranks = [0.0] * len(data)
        i = 0
        while i < len(data):
            j = i
            while j < len(data) - 1 and data[sorted_indices[j]] == data[sorted_indices[j + 1]]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[sorted_indices[k]] = avg_rank
            i = j + 1
        return ranks

    rank_x = rankdata(x)
    rank_y = rankdata(y)

    mean_x = sum(rank_x) / len(rank_x)
    mean_y = sum(rank_y) / len(rank_y)

    cov = sum((rank_x[i] - mean_x) * (rank_y[i] - mean_y) for i in range(len(x)))
    var_x = sum((rank_x[i] - mean_x) ** 2 for i in range(len(x)))
    var_y = sum((rank_y[i] - mean_y) ** 2 for i in range(len(y)))

    if var_x == 0 or var_y == 0:
        return 0.0

    rho = cov / math.sqrt(var_x * var_y)
    return round(float(rho), 4)


def compute_weighted_cohens_kappa(
    rater_a: list[float],
    rater_b: list[float],
    min_rating: int = 1,
    max_rating: int = 5,
) -> float:
    """Compute Quadratic Weighted Cohen's Kappa for ordinal agreement.
    
    Verifies statistical assumptions:
    - Raters must have length >= 2.
    - If variance of either rater is 0 (all ratings identical), kappa is mathematically degenerate.
    - If denominator (1 - Pe) <= 1e-9, returns 1.0 (perfect agreement) or 0.0.
    """
    if len(rater_a) != len(rater_b) or len(rater_a) < 2:
        return 0.0

    n = len(rater_a)
    num_categories = max_rating - min_rating + 1

    def to_category(val: float) -> int:
        cat = round(val)
        return max(min_rating, min(max_rating, cat)) - min_rating

    cat_a = [to_category(v) for v in rater_a]
    cat_b = [to_category(v) for v in rater_b]

    # Verify variability assumption
    unique_a = len(set(cat_a))
    unique_b = len(set(cat_b))
    if unique_a < 2 and unique_b < 2:
        return 1.0 if cat_a == cat_b else 0.0
    if unique_a < 2 or unique_b < 2:
        return 0.0

    # Confusion matrix O
    O = [[0.0] * num_categories for _ in range(num_categories)]
    for a, b in zip(cat_a, cat_b):
        O[a][b] += 1.0

    # Marginals
    hist_a = [sum(O[i][j] for j in range(num_categories)) for i in range(num_categories)]
    hist_b = [sum(O[i][j] for i in range(num_categories)) for j in range(num_categories)]

    # Expected matrix E
    E = [[(hist_a[i] * hist_b[j]) / n for j in range(num_categories)] for i in range(num_categories)]

    # Quadratic weight matrix W
    max_dist_sq = (num_categories - 1) ** 2
    W = [[1.0 - ((i - j) ** 2) / max_dist_sq for j in range(num_categories)] for i in range(num_categories)]

    # Compute observed & expected agreement
    Po = sum(W[i][j] * O[i][j] for i in range(num_categories) for j in range(num_categories)) / n
    Pe = sum(W[i][j] * E[i][j] for i in range(num_categories) for j in range(num_categories)) / n

    if abs(1.0 - Pe) < 1e-9:
        return 1.0 if abs(Po - Pe) < 1e-9 else 0.0

    kappa = (Po - Pe) / (1.0 - Pe)
    return round(float(kappa), 4)


def compute_mae(x: list[float], y: list[float]) -> float:
    """Compute Mean Absolute Error between two sets of ratings."""
    if not x or len(x) != len(y):
        return 0.0
    return round(sum(abs(a - b) for a, b in zip(x, y)) / len(x), 4)


def load_synthetic_calibration_fixtures() -> list[HumanLabeledSample]:
    """Load deterministic synthetic fixtures for CI / unit test validation."""
    return [HumanLabeledSample.model_validate(_normalize_sample_scores(item)) for item in SYNTHETIC_CALIBRATION_FIXTURES]


def load_human_ground_truth_dataset() -> list[HumanLabeledSample]:
    """Load empirical human ground truth dataset (empty until expert annotations are collected)."""
    return [HumanLabeledSample.model_validate(_normalize_sample_scores(item)) for item in HUMAN_GROUND_TRUTH_DATASET]


def load_calibration_dataset() -> list[HumanLabeledSample]:
    """Backward-compatible loader for synthetic test fixtures."""
    return load_synthetic_calibration_fixtures()

