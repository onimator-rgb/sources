"""
Comprehensive tests for FBRCalculator — per-source Follow-Back Ratio analytics.

Covers:
  1. Normal FBR calculation (follows + followbacks)
  2. Edge cases: FBR = 0%, FBR = 100%
  3. Empty data.db (no follows)
  4. Missing data.db
  5. Per-source FBR breakdown with multiple sources
  6. Quality flag based on thresholds (min_follows + min_fbr_pct)
  7. Anomaly detection (followbacks > follows)
  8. Multiple sources with different FBR rates
  9. Large dataset performance
  10. Schema validation (missing table, missing columns)
  11. NULL / empty / "none" source filtering
"""
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

from oh.models.fbr import FBRAnalysisResult, SourceFBRRecord
from oh.modules.fbr_calculator import FBRCalculator


# ======================================================================
# Helpers
# ======================================================================

def _create_data_db(db_path: Path, rows: Optional[List[Tuple]] = None) -> None:
    """
    Create a data.db at *db_path* with the expected 'sources' table and insert rows.

    Each row is a tuple: (source, followback)
    where followback is 'True' or 'False' (string, matching Onimator convention).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            source      TEXT,
            followback  TEXT DEFAULT 'False'
        )
    """)
    if rows:
        conn.executemany(
            "INSERT INTO sources (source, followback) VALUES (?, ?)",
            rows,
        )
    conn.commit()
    conn.close()


# ======================================================================
# FBRCalculator Tests
# ======================================================================

class TestFBRCalculator(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.calculator = FBRCalculator(
            bot_root=self.tmp_dir,
            min_follows=100,
            min_fbr_pct=10.0,
        )
        self.device_id = "device_abc"
        self.username = "testaccount"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _data_db_path(self) -> Path:
        return Path(self.tmp_dir) / self.device_id / self.username / "data.db"

    def _insert_sources(self, rows: List[Tuple[str, str]]) -> None:
        """Convenience: create data.db and insert rows."""
        _create_data_db(self._data_db_path(), rows)

    # ------------------------------------------------------------------
    # Missing / empty database
    # ------------------------------------------------------------------

    def test_missing_data_db(self):
        """data.db doesn't exist — result reports schema_valid=False."""
        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("not found", result.schema_error)
        self.assertFalse(result.has_data)
        self.assertEqual(result.total_count, 0)

    def test_empty_sources_table(self):
        """data.db exists but sources table has no rows."""
        self._insert_sources([])
        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.schema_valid)
        self.assertIsNone(result.schema_error)
        self.assertFalse(result.has_data)
        self.assertEqual(result.total_count, 0)
        self.assertEqual(result.quality_count, 0)

    # ------------------------------------------------------------------
    # Normal FBR calculation
    # ------------------------------------------------------------------

    def test_normal_fbr(self):
        """100 follows from source_a, 20 followbacks => FBR = 20%."""
        rows = []
        for i in range(100):
            fb = "True" if i < 20 else "False"
            rows.append(("source_a", fb))
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.has_data)
        self.assertEqual(result.total_count, 1)

        rec = result.records[0]
        self.assertEqual(rec.source_name, "source_a")
        self.assertEqual(rec.follow_count, 100)
        self.assertEqual(rec.followback_count, 20)
        self.assertAlmostEqual(rec.fbr_percent, 20.0)
        self.assertIsNone(rec.anomaly)

    # ------------------------------------------------------------------
    # FBR = 0% (follows but zero followbacks)
    # ------------------------------------------------------------------

    def test_fbr_zero_percent(self):
        """All follows, no followbacks => FBR = 0%."""
        rows = [("zero_source", "False") for _ in range(50)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.has_data)
        rec = result.records[0]
        self.assertEqual(rec.follow_count, 50)
        self.assertEqual(rec.followback_count, 0)
        self.assertAlmostEqual(rec.fbr_percent, 0.0)
        self.assertFalse(rec.is_quality)
        self.assertIsNone(rec.anomaly)

    # ------------------------------------------------------------------
    # FBR = 100% (all follows got followback)
    # ------------------------------------------------------------------

    def test_fbr_hundred_percent(self):
        """All follows got followback => FBR = 100%, no anomaly."""
        rows = [("perfect_src", "True") for _ in range(120)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertEqual(rec.follow_count, 120)
        self.assertEqual(rec.followback_count, 120)
        self.assertAlmostEqual(rec.fbr_percent, 100.0)
        self.assertIsNone(rec.anomaly)
        self.assertTrue(rec.is_quality)

    # ------------------------------------------------------------------
    # Per-source FBR breakdown with multiple sources
    # ------------------------------------------------------------------

    def test_multiple_sources(self):
        """Multiple sources produce separate records."""
        rows = (
            [("src_a", "True" if i < 10 else "False") for i in range(60)]
            + [("src_b", "True" if i < 5 else "False") for i in range(80)]
        )
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(result.total_count, 2)
        names = {r.source_name for r in result.records}
        self.assertEqual(names, {"src_a", "src_b"})

    def test_multiple_sources_different_fbr_rates(self):
        """Sources with varied FBR rates are computed independently."""
        rows = (
            [("high_fbr", "True" if i < 40 else "False") for i in range(200)]   # 20%
            + [("low_fbr", "True" if i < 5 else "False") for i in range(150)]   # ~3.3%
            + [("mid_fbr", "True" if i < 15 else "False") for i in range(100)]  # 15%
        )
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        by_name = {r.source_name: r for r in result.records}

        self.assertAlmostEqual(by_name["high_fbr"].fbr_percent, 20.0)
        self.assertAlmostEqual(by_name["low_fbr"].fbr_percent, 100 * 5 / 150, places=1)
        self.assertAlmostEqual(by_name["mid_fbr"].fbr_percent, 15.0)

    # ------------------------------------------------------------------
    # Quality flag thresholds
    # ------------------------------------------------------------------

    def test_quality_both_thresholds_met(self):
        """Source meets both min_follows (100) and min_fbr_pct (10%) => is_quality."""
        rows = [("quality_src", "True" if i < 15 else "False") for i in range(100)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertTrue(rec.is_quality)
        self.assertEqual(result.quality_count, 1)

    def test_not_quality_below_min_follows(self):
        """Fewer follows than min_follows => not quality, even if FBR% is high."""
        rows = [("small_src", "True") for _ in range(50)]  # 50 < 100
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertFalse(rec.is_quality)
        self.assertAlmostEqual(rec.fbr_percent, 100.0)
        self.assertEqual(result.below_volume_count, 1)

    def test_not_quality_below_min_fbr_pct(self):
        """FBR% below threshold => not quality, even if volume is high."""
        # 200 follows, 5 followbacks => FBR = 2.5%
        rows = [("low_fbr", "True" if i < 5 else "False") for i in range(200)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertFalse(rec.is_quality)
        self.assertAlmostEqual(rec.fbr_percent, 2.5)

    def test_quality_with_custom_thresholds(self):
        """Custom thresholds change what counts as quality."""
        calc = FBRCalculator(
            bot_root=self.tmp_dir,
            min_follows=10,
            min_fbr_pct=5.0,
        )
        rows = [("src", "True" if i < 3 else "False") for i in range(20)]
        self._insert_sources(rows)

        result = calc.calculate(self.device_id, self.username)
        rec = result.records[0]
        # 20 follows >= 10, FBR 15% >= 5%
        self.assertTrue(rec.is_quality)

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def test_anomaly_followback_exceeds_follows(self):
        """
        Test anomaly detection via _build_record directly.

        Under normal SQL, followback_count cannot exceed follow_count because
        followback_count is a SUM of a CASE over COUNT(*). The anomaly guard
        handles corrupt data. We test _build_record with a crafted dict.
        """
        result = FBRAnalysisResult(
            device_id=self.device_id,
            username=self.username,
            min_follows=100,
            min_fbr_pct=10.0,
        )

        class DictRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, key):
                return self._d[key]

        fake_row = DictRow({
            "source_name": "anomaly_src",
            "follow_count": 5,
            "followback_count": 10,
        })

        rec = self.calculator._build_record(fake_row, result)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.anomaly, "followback_exceeds_follows")
        self.assertFalse(rec.is_quality)
        self.assertAlmostEqual(rec.fbr_percent, 100.0)  # capped
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("anomaly_src", result.warnings[0])

    def test_anomaly_source_not_quality(self):
        """A source with an anomaly flag is never marked as quality."""
        result = FBRAnalysisResult(
            device_id=self.device_id,
            username=self.username,
            min_follows=1,
            min_fbr_pct=1.0,
        )

        class DictRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, key):
                return self._d[key]

        fake_row = DictRow({
            "source_name": "bad_data",
            "follow_count": 100,
            "followback_count": 200,
        })

        calc = FBRCalculator(bot_root=self.tmp_dir, min_follows=1, min_fbr_pct=1.0)
        rec = calc._build_record(fake_row, result)
        self.assertIsNotNone(rec)
        self.assertFalse(rec.is_quality)

    def test_no_anomaly_when_fbr_exactly_100(self):
        """FBR = 100% (followback == follows) is not an anomaly."""
        rows = [("perfect", "True") for _ in range(100)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertIsNone(rec.anomaly)
        self.assertEqual(result.anomaly_count, 0)
        self.assertEqual(len(result.warnings), 0)

    # ------------------------------------------------------------------
    # Source filtering (NULL, empty, "none", "null")
    # ------------------------------------------------------------------

    def test_filters_null_empty_none_sources(self):
        """NULL, empty, 'none', 'null' sources are excluded."""
        rows = [
            (None, "False"),
            ("", "False"),
            ("none", "False"),
            ("None", "False"),
            ("null", "False"),
            ("NULL", "False"),
            ("  ", "False"),
            ("real_source", "True"),
        ]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.records[0].source_name, "real_source")

    def test_source_names_trimmed(self):
        """Leading/trailing whitespace in source names is trimmed."""
        rows = [
            ("  trimmed_src  ", "True"),
            ("  trimmed_src  ", "False"),
        ]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.records[0].source_name, "trimmed_src")
        self.assertEqual(result.records[0].follow_count, 2)

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    def test_invalid_schema_no_sources_table(self):
        """data.db exists but has no 'sources' table."""
        db_path = self._data_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (col TEXT)")
        conn.close()

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("sources", result.schema_error)

    def test_invalid_schema_missing_columns(self):
        """data.db has 'sources' table but missing required columns."""
        db_path = self._data_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sources (source TEXT)")  # missing 'followback'
        conn.close()

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("missing column", result.schema_error)
        self.assertIn("followback", result.schema_error)

    def test_valid_schema_extra_columns_ok(self):
        """Extra columns beyond the required ones are fine."""
        db_path = self._data_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sources (
                source TEXT,
                followback TEXT,
                follow TEXT,
                username TEXT,
                extra_col TEXT
            )
        """)
        conn.execute("INSERT INTO sources (source, followback) VALUES ('src', 'True')")
        conn.commit()
        conn.close()

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.has_data)

    # ------------------------------------------------------------------
    # Result identity fields
    # ------------------------------------------------------------------

    def test_result_identity_fields(self):
        """Result carries device_id, username, and thresholds."""
        self._insert_sources([])
        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(result.device_id, self.device_id)
        self.assertEqual(result.username, self.username)
        self.assertEqual(result.min_follows, 100)
        self.assertAlmostEqual(result.min_fbr_pct, 10.0)

    # ------------------------------------------------------------------
    # Summary helpers on result
    # ------------------------------------------------------------------

    def test_best_source_by_fbr(self):
        """best_source_by_fbr returns highest FBR among qualifying sources."""
        rows = (
            [("big_good", "True" if i < 30 else "False") for i in range(200)]   # 15%
            + [("big_great", "True" if i < 50 else "False") for i in range(150)]  # 33%
            + [("tiny_great", "True") for _ in range(10)]                         # 100% but < min_follows
        )
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        best = result.best_source_by_fbr
        self.assertIsNotNone(best)
        self.assertEqual(best.source_name, "big_great")

    def test_best_source_by_fbr_none_when_all_below_volume(self):
        """No source meets min_follows => best_source_by_fbr is None."""
        rows = [("tiny", "True") for _ in range(5)]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertIsNone(result.best_source_by_fbr)

    def test_highest_volume_source(self):
        """highest_volume_source returns source with most follows."""
        rows = (
            [("small", "True") for _ in range(20)]
            + [("large", "False") for _ in range(300)]
        )
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        highest = result.highest_volume_source
        self.assertIsNotNone(highest)
        self.assertEqual(highest.source_name, "large")
        self.assertEqual(highest.follow_count, 300)

    # ------------------------------------------------------------------
    # Ordering of results
    # ------------------------------------------------------------------

    def test_records_ordered_by_follow_count_desc(self):
        """Records are ordered by follow_count DESC, then source_name ASC."""
        rows = (
            [("alpha", "False") for _ in range(50)]
            + [("beta", "False") for _ in range(200)]
            + [("gamma", "False") for _ in range(200)]
        )
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(len(result.records), 3)
        # beta and gamma tied at 200, alpha at 50
        # Tied sources ordered alphabetically
        self.assertEqual(result.records[0].source_name, "beta")
        self.assertEqual(result.records[1].source_name, "gamma")
        self.assertEqual(result.records[2].source_name, "alpha")

    # ------------------------------------------------------------------
    # Never raises
    # ------------------------------------------------------------------

    def test_corrupt_db_raises_database_error(self):
        """
        Corrupt data.db must be handled gracefully — calculate() should
        never raise, returning a result with schema_valid=False instead.
        """
        db_path = self._data_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"this is not a sqlite database")

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("Cannot read data.db", result.schema_error)

    # ------------------------------------------------------------------
    # Large dataset performance
    # ------------------------------------------------------------------

    def test_large_dataset_performance(self):
        """10 sources x 1000 rows each = 10,000 rows completes quickly."""
        rows = []
        for src_idx in range(10):
            source_name = f"source_{src_idx:03d}"
            for i in range(1000):
                fb = "True" if i < (src_idx * 50) else "False"
                rows.append((source_name, fb))
        self._insert_sources(rows)

        start = time.monotonic()
        result = self.calculator.calculate(self.device_id, self.username)
        elapsed = time.monotonic() - start

        self.assertTrue(result.schema_valid)
        self.assertEqual(result.total_count, 10)
        self.assertEqual(
            sum(r.follow_count for r in result.records), 10_000,
        )
        # Should complete well under 2 seconds
        self.assertLess(elapsed, 2.0, f"Took {elapsed:.2f}s for 10k rows")

    # ------------------------------------------------------------------
    # Followback value variations
    # ------------------------------------------------------------------

    def test_followback_true_case_insensitive(self):
        """Only exact 'True' (after trim) counts as followback."""
        rows = [
            ("src", "True"),       # counts
            ("src", " True "),     # counts (trimmed in SQL)
            ("src", "true"),       # does NOT count (case-sensitive match)
            ("src", "FALSE"),      # does NOT count
            ("src", "False"),      # does NOT count
            ("src", "1"),          # does NOT count
        ]
        self._insert_sources(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertEqual(rec.follow_count, 6)
        # Only 'True' and ' True ' match TRIM(followback) = 'True'
        self.assertEqual(rec.followback_count, 2)


if __name__ == "__main__":
    unittest.main()
