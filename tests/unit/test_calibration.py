from causegraph.calibration import brier_score, expected_calibration_error


def test_brier_score_is_zero_for_perfect_confidence():
    pairs = [(1.0, True), (0.0, False), (1.0, True)]
    assert brier_score(pairs) == 0.0


def test_brier_score_is_high_for_confidently_wrong_predictions():
    pairs = [(1.0, False), (1.0, False)]
    assert brier_score(pairs) == 1.0


def test_brier_score_empty_is_nan():
    assert brier_score([]) != brier_score([])  # nan != nan


def test_ece_is_zero_when_confidence_matches_accuracy_in_every_bin():
    # All predictions land in the [0.8, 1.0) bin at confidence 0.9, and
    # 90% of them are correct -- confidence matches empirical accuracy.
    pairs = [(0.9, True)] * 9 + [(0.9, False)] * 1
    result = expected_calibration_error(pairs, n_bins=5)
    assert abs(result.expected_calibration_error - 0.0) < 0.01
    assert result.n_samples == 10


def test_ece_is_high_when_overconfident_and_always_wrong():
    pairs = [(0.95, False)] * 10
    result = expected_calibration_error(pairs, n_bins=5)
    assert result.expected_calibration_error > 0.9


def test_ece_reports_bin_details_covering_full_range():
    pairs = [(0.1, False), (0.9, True)]
    result = expected_calibration_error(pairs, n_bins=5)
    assert len(result.bin_details) == 5
    assert result.bin_details[0]["range"] == [0.0, 0.2]
    assert result.bin_details[-1]["range"] == [0.8, 1.0]


def test_ece_empty_pairs_returns_nan_without_crashing():
    result = expected_calibration_error([])
    assert result.n_samples == 0
    assert result.expected_calibration_error != result.expected_calibration_error  # nan
