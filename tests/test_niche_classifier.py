"""Tests for oh.modules.niche_classifier."""
import unittest
from oh.modules.niche_classifier import (
    classify_profile, compute_niche_match, detect_language,
    extract_niche_keywords, _keyword_match, NicheResult, NICHE_TAXONOMY,
)


# ======================================================================
# _keyword_match
# ======================================================================


class TestKeywordMatch(unittest.TestCase):

    def test_exact_word_match(self):
        self.assertTrue(_keyword_match("fitness", "i love fitness"))

    def test_multi_word_match(self):
        self.assertTrue(_keyword_match("personal training", "certified personal training coach"))

    def test_multi_word_no_match(self):
        self.assertFalse(_keyword_match("personal training", "personal and training"))

    def test_stem_match_long_keyword(self):
        # "training" starts with "trainer" prefix — but actually check:
        # keyword.startswith(word) or word.startswith(keyword)
        # "trainings".startswith("training") → True
        self.assertTrue(_keyword_match("training", "trainings are fun"))

    def test_stem_match_reverse(self):
        # word starts with keyword
        self.assertTrue(_keyword_match("training", "trainings every day"))

    def test_no_false_positive_short_words(self):
        # Short keywords (< 6 chars) should NOT stem-match
        self.assertFalse(_keyword_match("art", "article about science"))

    def test_no_partial_match_short_keyword(self):
        # "gym" should not match "gymnastic" via stem (too short)
        self.assertFalse(_keyword_match("gym", "gymnastics class"))

    def test_empty_keyword(self):
        self.assertFalse(_keyword_match("", "some text"))

    def test_empty_text(self):
        self.assertFalse(_keyword_match("fitness", ""))

    def test_exact_single_word(self):
        self.assertTrue(_keyword_match("yoga", "yoga"))

    def test_strict_mode_exact_only(self):
        self.assertTrue(_keyword_match("fitness", "i love fitness", strict=True))
        self.assertFalse(_keyword_match("fit", "fitness is great", strict=True))


# ======================================================================
# detect_language
# ======================================================================


class TestDetectLanguage(unittest.TestCase):

    def test_polish_text(self):
        result = detect_language("Trenerka personalna, zapisy już otwarte")
        self.assertEqual(result, "pl")

    def test_english_text(self):
        result = detect_language("Personal trainer based in NYC")
        self.assertEqual(result, "en")

    def test_empty_returns_unknown(self):
        self.assertEqual(detect_language(""), "unknown")
        self.assertEqual(detect_language(None), "unknown")
        self.assertEqual(detect_language("   "), "unknown")

    def test_mixed_with_polish_chars(self):
        # Contains Polish chars ą, ę — should be detected as Polish
        result = detect_language("Kochając życie każdego dnia")
        self.assertEqual(result, "pl")


# ======================================================================
# classify_profile
# ======================================================================


class TestClassifyProfile(unittest.TestCase):

    def test_fitness_trainer(self):
        result = classify_profile(
            bio="Certified personal trainer | Gym enthusiast | Workout plans",
            category="Personal Trainer",
            full_name="John Fit Coach",
        )
        self.assertEqual(result.primary_niche, "fitness")
        self.assertGreater(result.confidence, 0.0)
        self.assertIsInstance(result.matched_keywords, list)
        self.assertTrue(len(result.matched_keywords) > 0)

    def test_business_entrepreneur(self):
        result = classify_profile(
            bio="Entrepreneur | Building my startup | Marketing strategy",
            category="Entrepreneur",
            full_name="Jane CEO",
        )
        self.assertEqual(result.primary_niche, "business")

    def test_photographer(self):
        result = classify_profile(
            bio="Portrait and editorial photographer | Booking open",
            category="Photographer",
            full_name="Alex Photography",
        )
        self.assertEqual(result.primary_niche, "photography")

    def test_empty_bio_no_category(self):
        result = classify_profile(bio="", category=None, full_name=None, username=None)
        self.assertEqual(result.primary_niche, "general")
        self.assertEqual(result.confidence, 0.0)

    def test_generic_bio(self):
        result = classify_profile(bio="hello world", full_name="test user")
        self.assertEqual(result.primary_niche, "general")

    def test_fashion_model_category_not_fitness(self):
        # "Fashion Model" category should map to fashion, not fitness
        result = classify_profile(
            bio="Style icon | OOTD daily",
            category="Fashion Model",
        )
        self.assertEqual(result.primary_niche, "fashion")

    def test_art_category(self):
        result = classify_profile(
            bio="Painting and illustration",
            category="Artist",
        )
        self.assertEqual(result.primary_niche, "art")

    def test_single_generic_keyword_below_threshold(self):
        # A single keyword in bio gives 3 points, which is below _MIN_SCORE=6
        result = classify_profile(bio="I enjoy cooking sometimes")
        self.assertEqual(result.primary_niche, "general")

    def test_result_has_all_scores(self):
        result = classify_profile(bio="fitness gym workout")
        self.assertIsInstance(result.all_scores, dict)
        self.assertIn("fitness", result.all_scores)

    def test_result_language_detected(self):
        result = classify_profile(bio="Trener personalny siłownia ćwiczenia")
        self.assertEqual(result.language, "pl")


# ======================================================================
# compute_niche_match
# ======================================================================


class TestComputeNicheMatch(unittest.TestCase):

    def test_same_niche_high_score(self):
        target = classify_profile(
            bio="Certified personal trainer | Gym",
            category="Personal Trainer",
            full_name="FitCoach",
        )
        score = compute_niche_match(
            target,
            candidate_bio="Workout routines | Gym life | Fitness tips",
            candidate_category="Personal Trainer",
        )
        self.assertGreaterEqual(score, 60)

    def test_related_niche_medium_score(self):
        # fitness and nutrition are related
        target = classify_profile(
            bio="Personal trainer | Gym workout plans",
            category="Personal Trainer",
        )
        score = compute_niche_match(
            target,
            candidate_bio="Dietitian | Nutrition plans | Healthy meals",
            candidate_category="Nutritionist",
        )
        self.assertGreaterEqual(score, 30)

    def test_unrelated_niche_low_score(self):
        # fitness vs real_estate — not related
        target = classify_profile(
            bio="Personal trainer | Gym workout",
            category="Personal Trainer",
        )
        score = compute_niche_match(
            target,
            candidate_bio="Luxury homes | Real estate agent | Property listings",
            candidate_category="Real Estate Agent",
        )
        self.assertLessEqual(score, 20)


# ======================================================================
# extract_niche_keywords
# ======================================================================


class TestExtractNicheKeywords(unittest.TestCase):

    def test_extracts_meaningful_words(self):
        keywords = extract_niche_keywords("Professional photographer and designer")
        self.assertIn("professional", keywords)
        self.assertIn("photographer", keywords)
        self.assertIn("designer", keywords)

    def test_filters_stopwords(self):
        keywords = extract_niche_keywords("the best fitness trainer in the world")
        self.assertNotIn("the", keywords)
        self.assertNotIn("in", keywords)
        # "world" is a stopword in the classifier
        self.assertNotIn("world", keywords)

    def test_empty_input(self):
        self.assertEqual(extract_niche_keywords(""), set())
        self.assertEqual(extract_niche_keywords(None), set())
        self.assertEqual(extract_niche_keywords("   "), set())

    def test_filters_short_words(self):
        keywords = extract_niche_keywords("I am a go to expert")
        # Words shorter than 3 chars should be filtered
        self.assertNotIn("I", keywords)
        self.assertNotIn("am", keywords)

    def test_removes_urls_and_mentions(self):
        keywords = extract_niche_keywords("Check https://example.com @someone fitness")
        self.assertNotIn("https", keywords)
        self.assertNotIn("someone", keywords)
        self.assertIn("fitness", keywords)


# ======================================================================
# NICHE_TAXONOMY validation
# ======================================================================


class TestNicheTaxonomy(unittest.TestCase):

    def test_all_niches_have_required_fields(self):
        for name, defn in NICHE_TAXONOMY.items():
            self.assertEqual(defn.name, name)
            self.assertTrue(len(defn.display_name) > 0, f"{name} missing display_name")
            self.assertIsInstance(defn.keywords_pl, list)
            self.assertIsInstance(defn.keywords_en, list)
            self.assertIsInstance(defn.instagram_categories, list)
            self.assertIsInstance(defn.related_niches, list)

    def test_no_empty_keyword_lists(self):
        for name, defn in NICHE_TAXONOMY.items():
            self.assertTrue(len(defn.keywords_pl) > 0, f"{name} has empty keywords_pl")
            self.assertTrue(len(defn.keywords_en) > 0, f"{name} has empty keywords_en")

    def test_related_niches_exist_in_taxonomy(self):
        for name, defn in NICHE_TAXONOMY.items():
            for related in defn.related_niches:
                self.assertIn(
                    related, NICHE_TAXONOMY,
                    f"{name} references unknown related niche '{related}'",
                )


if __name__ == "__main__":
    unittest.main()
