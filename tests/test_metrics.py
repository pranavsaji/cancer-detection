import pytest

from tools import metrics
from tools.decisions_client import parse_answers


def test_confusion_counts_at_threshold():
    labels = [1, 1, 0, 0, 1]
    probs = [0.9, 0.4, 0.6, 0.1, 0.5]
    assert metrics.confusion(labels, probs, 0.5) == {"tp": 2, "fp": 1, "tn": 1, "fn": 1}


def test_rates_match_hand_calculation():
    r = metrics.rates({"tp": 40, "fp": 10, "tn": 40, "fn": 10})
    assert r["accuracy"]["value"] == pytest.approx(0.8)
    assert r["sensitivity"]["value"] == pytest.approx(0.8)
    assert r["specificity"]["value"] == pytest.approx(0.8)
    assert r["precision"]["value"] == pytest.approx(0.8)
    assert r["f1"] == pytest.approx(0.8)


def test_rates_with_no_positive_predictions():
    r = metrics.rates({"tp": 0, "fp": 0, "tn": 5, "fn": 5})
    assert r["precision"]["value"] is None
    assert r["sensitivity"]["value"] == 0


def test_wilson_interval_known_value():
    low, high = metrics.wilson_interval(80, 100)
    assert low == pytest.approx(0.7112, abs=1e-3)
    assert high == pytest.approx(0.8666, abs=1e-3)


def test_auc_perfect_random_and_ties():
    assert metrics.roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert metrics.roc_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == 0.0
    assert metrics.roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert metrics.roc_auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)


def test_auc_undefined_for_single_class():
    assert metrics.roc_auc([1, 1], [0.2, 0.9]) is None


def test_roc_curve_runs_from_origin_to_one_one():
    points = metrics.roc_curve([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
    assert (points[0]["fpr"], points[0]["tpr"]) == (0.0, 0.0)
    assert (points[-1]["fpr"], points[-1]["tpr"]) == (1.0, 1.0)


def test_calibration_perfectly_calibrated_bin():
    labels = [1, 0, 1, 0]
    probs = [0.5, 0.5, 0.5, 0.5]
    result = metrics.calibration(labels, probs)
    assert result["ece"] == pytest.approx(0.0)
    assert result["brier"] == pytest.approx(0.25)
    assert sum(b["n"] for b in result["bins"]) == 4


def test_calibration_includes_probability_of_one():
    result = metrics.calibration([1], [1.0])
    assert result["bins"][-1]["n"] == 1


def test_percentile_interpolates():
    assert metrics.percentile([10, 20, 30, 40], 0.5) == 25
    assert metrics.percentile([], 0.5) is None


def test_parse_answers_reads_all_three_questions():
    parsed = parse_answers(
        [
            {"type": "predicate", "name": "malignant", "probability": 0.83},
            {
                "type": "choice",
                "name": "lesion_type",
                "choice": "melanoma",
                "confidence": 0.7,
                "probabilities": [
                    {"value": "melanoma", "probability": 0.8},
                    {"value": "nevus", "probability": 0.2},
                ],
            },
            {"type": "predicate", "name": "is_skin_lesion", "probability": 0.99},
        ]
    )
    assert parsed["malignant_probability"] == 0.83
    assert parsed["lesion_type"] == "melanoma"
    assert parsed["lesion_type_probabilities"] == {"melanoma": 0.8, "nevus": 0.2}
    assert parsed["is_skin_lesion_probability"] == 0.99
    assert parsed["refused"] == []


def test_parse_answers_records_refusals():
    parsed = parse_answers(
        [
            {"type": "refusal", "name": "malignant"},
            {"type": "predicate", "name": "is_skin_lesion", "probability": 0.9},
        ]
    )
    assert parsed["malignant_probability"] is None
    assert parsed["refused"] == ["malignant"]
