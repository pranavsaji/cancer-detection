"""Binary-classification metrics for the evaluation report. Pure functions, no I/O."""
import math


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _rate(numerator: int, denominator: int) -> dict:
    return {
        "value": numerator / denominator if denominator else None,
        "ci": wilson_interval(numerator, denominator),
        "n": denominator,
    }


def confusion(labels: list[int], probabilities: list[float], threshold: float) -> dict:
    tp = fp = tn = fn = 0
    for y, p in zip(labels, probabilities):
        predicted = p >= threshold
        if predicted and y:
            tp += 1
        elif predicted:
            fp += 1
        elif y:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def rates(c: dict) -> dict:
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    sensitivity = _rate(tp, tp + fn)
    specificity = _rate(tn, tn + fp)
    precision = _rate(tp, tp + fp)
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None
    balanced = (
        (sensitivity["value"] + specificity["value"]) / 2
        if sensitivity["value"] is not None and specificity["value"] is not None
        else None
    )
    return {
        "accuracy": _rate(tp + tn, tp + fp + tn + fn),
        "sensitivity": sensitivity,
        "specificity": specificity,
        "precision": precision,
        "npv": _rate(tn, tn + fn),
        "f1": f1,
        "balanced_accuracy": balanced,
    }


def roc_auc(labels: list[int], probabilities: list[float]) -> float | None:
    """Mann-Whitney AUC with average ranks for ties."""
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    order = sorted(range(len(labels)), key=lambda i: probabilities[i])
    rank_sum = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and probabilities[order[j + 1]] == probabilities[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        rank_sum += average_rank * sum(labels[order[k]] for k in range(i, j + 1))
        i = j + 1
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def roc_curve(labels: list[int], probabilities: list[float]) -> list[dict]:
    positives = sum(labels)
    negatives = len(labels) - positives
    points = [{"threshold": None, "fpr": 0.0, "tpr": 0.0}]
    for threshold in sorted(set(probabilities), reverse=True):
        c = confusion(labels, probabilities, threshold)
        points.append(
            {
                "threshold": threshold,
                "fpr": c["fp"] / negatives if negatives else 0.0,
                "tpr": c["tp"] / positives if positives else 0.0,
            }
        )
    return points


def calibration(labels: list[int], probabilities: list[float], bins: int = 10) -> dict:
    """Reliability table plus expected calibration error and Brier score."""
    table = []
    ece = 0.0
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        members = [
            i for i, p in enumerate(probabilities) if low <= p < high or (b == bins - 1 and p == 1.0)
        ]
        if not members:
            table.append({"low": low, "high": high, "n": 0, "mean_probability": None, "observed": None})
            continue
        mean_p = sum(probabilities[i] for i in members) / len(members)
        observed = sum(labels[i] for i in members) / len(members)
        ece += len(members) / len(labels) * abs(mean_p - observed)
        table.append(
            {"low": low, "high": high, "n": len(members), "mean_probability": mean_p, "observed": observed}
        )
    brier = sum((p - y) ** 2 for y, p in zip(labels, probabilities)) / len(labels) if labels else None
    return {"bins": table, "ece": ece if labels else None, "brier": brier}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
