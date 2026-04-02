"""
NicheClassifier — local keyword-based profile niche classification.

Classifies Instagram profiles into one of ~20 predefined niches using
keyword matching on bio, category, full_name, and username. No API calls.

Also provides:
  - Language detection (PL vs EN)
  - Niche match scoring between profiles
  - Niche keyword extraction
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Text cleaning patterns ─────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50"
    "]+",
    flags=re.UNICODE,
)

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+")

# ── Stopwords for keyword extraction ───────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "am", "not", "no",
    "and", "or", "but", "if", "for", "nor", "so", "yet", "at", "by",
    "from", "in", "into", "of", "on", "to", "with", "as", "its", "it",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "how", "when", "where",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "than", "too", "very", "just", "also", "about",
    "new", "get", "like", "follow", "dm", "link", "bio", "check", "out",
    "based", "love", "life", "world", "official", "real", "page",
    "contact", "info", "available", "click", "below", "here",
    # Polish common words
    "więcej", "kontakt", "zapisy", "współpraca", "cennik", "oferta",
    "oraz", "dla", "jest", "się", "nie", "też", "przez", "przy",
    "nad", "pod", "jak", "już", "tylko", "tak", "może", "będzie",
    "każdy", "nasz", "swój", "tego", "tej", "ten", "tym", "ale", "aby",
    "czy", "lub",
}

# ── Polish language detection helpers ──────────────────────────────

_POLISH_CHARS = set("ąęóśżźćłń")

_POLISH_WORDS = {
    "jest", "się", "nie", "dla", "ale", "czy", "też", "już",
    "lub", "przy", "nad", "pod", "jak", "oraz", "tego", "tej",
    "tym", "aby", "więcej", "kontakt", "zapisy", "oferta",
    "współpraca", "cennik", "trener", "trenerka", "personalny",
    "dietetyk", "fotograf", "kosmetyczka", "restauracja",
}


# ── Dataclasses ────────────────────────────────────────────────────

@dataclass
class NicheDefinition:
    """Definition of a single niche with keywords and metadata."""
    name: str                          # "fitness"
    display_name: str                  # "Fitness & Training"
    keywords_pl: List[str]             # Polish keywords
    keywords_en: List[str]             # English keywords
    instagram_categories: List[str]    # Instagram category strings that map here
    related_niches: List[str]          # names of related niches


@dataclass
class NicheResult:
    """Result of classifying a profile into a niche."""
    primary_niche: str                 # "fitness"
    display_name: str                  # "Fitness & Training"
    confidence: float                  # 0.0 - 1.0
    matched_keywords: List[str]        # keywords that matched
    language: str                      # "pl", "en", "unknown"
    secondary_niche: Optional[str] = None
    all_scores: Dict[str, float] = field(default_factory=dict)


# ── Niche taxonomy ─────────────────────────────────────────────────

NICHE_TAXONOMY: Dict[str, NicheDefinition] = {
    "fitness": NicheDefinition(
        name="fitness",
        display_name="Fitness & Training",
        keywords_pl=[
            "trener", "trenerka", "personalny", "siłownia", "crossfit",
            "yoga", "pilates", "bieganie", "ćwiczenia", "trening",
            "kulturystyka", "fitness", "gym",
        ],
        keywords_en=[
            "trainer", "fitness", "gym", "workout", "crossfit", "yoga",
            "pilates", "running", "exercise", "bodybuilding",
            "personal training", "coach", "fitlife",
        ],
        instagram_categories=[
            "Personal Trainer", "Fitness Model",
            "Gym/Physical Fitness Centre", "Sports & Recreation",
            "Yoga Studio",
        ],
        related_niches=["nutrition", "wellness", "sport"],
    ),
    "beauty": NicheDefinition(
        name="beauty",
        display_name="Beauty & Cosmetics",
        keywords_pl=[
            "makijaż", "kosmetyki", "uroda", "wizaż", "pielęgnacja",
            "makijażystka", "paznokcie", "manicure", "brwi", "rzęsy",
            "kosmetyczka", "beauty", "skincare",
        ],
        keywords_en=[
            "makeup", "beauty", "cosmetics", "skincare", "nails",
            "manicure", "lashes", "brows", "mua", "beautician",
            "glam", "concealer", "foundation",
        ],
        instagram_categories=[
            "Beauty Salon", "Makeup Artist", "Beauty, Cosmetic & Personal Care",
            "Nail Salon", "Skin Care Service",
        ],
        related_niches=["fashion", "wellness", "lifestyle"],
    ),
    "fashion": NicheDefinition(
        name="fashion",
        display_name="Fashion & Style",
        keywords_pl=[
            "moda", "styl", "odzież", "ubrania", "butik", "stylizacja",
            "outfit", "fashion", "sukienki", "kolekcja", "projektant",
            "trendy", "lookbook",
        ],
        keywords_en=[
            "fashion", "style", "outfit", "clothing", "boutique",
            "designer", "wardrobe", "lookbook", "ootd", "streetwear",
            "collection", "apparel", "trend",
        ],
        instagram_categories=[
            "Fashion Designer", "Fashion Model", "Clothing Store",
            "Fashion Company", "Boutique",
        ],
        related_niches=["beauty", "lifestyle", "art"],
    ),
    "food": NicheDefinition(
        name="food",
        display_name="Food & Cooking",
        keywords_pl=[
            "gotowanie", "przepisy", "kuchnia", "jedzenie", "restauracja",
            "szef kuchni", "ciasta", "pieczenie", "gastronomia",
            "potrawy", "smacznego", "foodie", "catering",
        ],
        keywords_en=[
            "cooking", "recipes", "food", "restaurant", "chef",
            "baking", "cuisine", "foodie", "gastronomy", "homemade",
            "delicious", "kitchen", "catering",
        ],
        instagram_categories=[
            "Restaurant", "Food & Beverage Company", "Chef",
            "Bakery", "Caterer",
        ],
        related_niches=["nutrition", "lifestyle", "wellness"],
    ),
    "nutrition": NicheDefinition(
        name="nutrition",
        display_name="Nutrition & Diet",
        keywords_pl=[
            "dieta", "dietetyk", "odżywianie", "kalorie", "zdrowe",
            "suplementy", "białko", "makro", "posiłki", "jadłospis",
            "dietetyczka", "żywienie", "metabolizm",
        ],
        keywords_en=[
            "nutrition", "diet", "dietitian", "calories", "healthy",
            "supplements", "protein", "macros", "mealprep", "nutrients",
            "metabolism", "nutritionist", "wellness",
        ],
        instagram_categories=[
            "Nutritionist", "Health Food Store",
            "Vitamin/Supplement Shop", "Dietitian",
            "Health & Wellness Website",
        ],
        related_niches=["fitness", "wellness", "food"],
    ),
    "wellness": NicheDefinition(
        name="wellness",
        display_name="Wellness & Health",
        keywords_pl=[
            "zdrowie", "wellness", "mindfulness", "medytacja", "relaks",
            "masaż", "terapia", "psycholog", "rozwój", "harmonia",
            "równowaga", "detox", "spa",
        ],
        keywords_en=[
            "wellness", "health", "mindfulness", "meditation", "relax",
            "massage", "therapy", "psychologist", "selfcare", "balance",
            "holistic", "detox", "spa",
        ],
        instagram_categories=[
            "Health & Wellness Website", "Spa", "Massage Service",
            "Mental Health Service", "Alternative & Holistic Health Service",
        ],
        related_niches=["fitness", "nutrition", "coaching"],
    ),
    "photography": NicheDefinition(
        name="photography",
        display_name="Photography",
        keywords_pl=[
            "fotograf", "fotografia", "sesja", "zdjęcia", "portret",
            "plener", "studio", "obiektyw", "aparat", "retusz",
            "lightroom", "fotoreporter", "fotorelacja",
        ],
        keywords_en=[
            "photographer", "photography", "photoshoot", "portrait",
            "studio", "lens", "camera", "retouch", "lightroom",
            "editorial", "photos", "shooting", "creative",
        ],
        instagram_categories=[
            "Photographer", "Photography Studio",
            "Camera/Photo",
        ],
        related_niches=["wedding", "art", "fashion"],
    ),
    "wedding": NicheDefinition(
        name="wedding",
        display_name="Wedding & Events",
        keywords_pl=[
            "ślub", "wesele", "panna młoda", "dekoracje", "florystyka",
            "zaproszenia", "ceremonia", "plener ślubny", "bukiet",
            "fotograf ślubny", "organizacja", "wedding", "imprezy",
        ],
        keywords_en=[
            "wedding", "bride", "groom", "bridal", "ceremony",
            "decoration", "florist", "bouquet", "engagement",
            "weddingplanner", "venue", "reception", "event",
        ],
        instagram_categories=[
            "Wedding Planning Service", "Event Planner",
            "Florist", "Wedding Venue", "Bridal Shop",
        ],
        related_niches=["photography", "fashion", "interior"],
    ),
    "real_estate": NicheDefinition(
        name="real_estate",
        display_name="Real Estate",
        keywords_pl=[
            "nieruchomości", "mieszkanie", "dom", "sprzedaż", "wynajem",
            "deweloper", "inwestycje", "działka", "agent", "pośrednik",
            "apartament", "kredyt hipoteczny", "remont",
        ],
        keywords_en=[
            "realestate", "property", "apartment", "house", "realtor",
            "investment", "mortgage", "rental", "agent", "broker",
            "luxury homes", "listing", "developer",
        ],
        instagram_categories=[
            "Real Estate Agent", "Real Estate Company",
            "Property Management Company", "Real Estate Developer",
            "Commercial Real Estate Agency",
        ],
        related_niches=["interior", "business", "automotive"],
    ),
    "automotive": NicheDefinition(
        name="automotive",
        display_name="Automotive & Cars",
        keywords_pl=[
            "samochody", "motoryzacja", "auto", "warsztat", "detailing",
            "tuning", "mechanik", "salon", "części", "silnik",
            "przegląd", "naprawa", "dealership",
        ],
        keywords_en=[
            "cars", "automotive", "auto", "detailing", "tuning",
            "mechanic", "dealership", "engine", "vehicle", "carwash",
            "supercar", "luxury cars", "motorsport",
        ],
        instagram_categories=[
            "Automotive Dealership", "Car Dealership",
            "Automotive Repair Shop", "Automotive Company",
            "Motor Vehicle Company",
        ],
        related_niches=["business", "photography", "sport"],
    ),
    "education": NicheDefinition(
        name="education",
        display_name="Education & Teaching",
        keywords_pl=[
            "edukacja", "nauczyciel", "szkoła", "kurs", "lekcje",
            "nauka", "korepetycje", "wiedza", "studia", "akademia",
            "szkolenie", "warsztat", "certyfikat",
        ],
        keywords_en=[
            "education", "teacher", "school", "course", "lessons",
            "learning", "tutoring", "knowledge", "academy", "training",
            "workshop", "certificate", "online course",
        ],
        instagram_categories=[
            "Education", "School", "Tutor/Teacher",
            "Educational Research Center", "College & University",
        ],
        related_niches=["coaching", "business", "art"],
    ),
    "coaching": NicheDefinition(
        name="coaching",
        display_name="Coaching & Personal Development",
        keywords_pl=[
            "coaching", "rozwój osobisty", "motywacja", "mentor",
            "sukces", "cele", "mindset", "przedsiębiorczość",
            "lider", "przywództwo", "konsultacje", "sesje", "growth",
        ],
        keywords_en=[
            "coaching", "personal development", "motivation", "mentor",
            "success", "goals", "mindset", "entrepreneurship",
            "leadership", "consulting", "growth", "lifecoach", "empower",
        ],
        instagram_categories=[
            "Coach", "Motivational Speaker", "Consulting Agency",
            "Personal Coach", "Business Consultant",
        ],
        related_niches=["business", "education", "wellness"],
    ),
    "business": NicheDefinition(
        name="business",
        display_name="Business & Entrepreneurship",
        keywords_pl=[
            "biznes", "firma", "przedsiębiorca", "marketing", "startup",
            "zarządzanie", "sprzedaż", "strategia", "marka", "branding",
            "ecommerce", "social media", "reklama",
        ],
        keywords_en=[
            "business", "company", "entrepreneur", "marketing", "startup",
            "management", "sales", "strategy", "branding",
            "ecommerce", "social media", "advertising",
        ],
        instagram_categories=[
            "Entrepreneur", "Business Service",
            "Marketing Agency", "Consulting Agency",
            "Small Business",
        ],
        related_niches=["coaching", "education", "real_estate"],
    ),
    "travel": NicheDefinition(
        name="travel",
        display_name="Travel & Tourism",
        keywords_pl=[
            "podróże", "wakacje", "turystyka", "zwiedzanie", "hotel",
            "plaża", "góry", "wycieczka", "lot", "bagaż",
            "backpacking", "travel", "krajobraz",
        ],
        keywords_en=[
            "travel", "vacation", "tourism", "traveler", "hotel",
            "beach", "mountains", "backpacking", "flight",
            "wanderlust", "adventure", "destination",
        ],
        instagram_categories=[
            "Travel Agency", "Travel Company", "Hotel",
            "Tour Guide", "Tourist Information Center",
        ],
        related_niches=["photography", "lifestyle", "food"],
    ),
    "interior": NicheDefinition(
        name="interior",
        display_name="Interior Design & Home",
        keywords_pl=[
            "wnętrza", "projektowanie", "aranżacja", "meble", "dekoracje",
            "dom", "mieszkanie", "kuchnia", "łazienka", "salon",
            "remont", "architektura", "design",
        ],
        keywords_en=[
            "interior", "design", "furniture", "decor", "home",
            "apartment", "kitchen", "bathroom", "renovation",
            "architecture", "homedecor", "interiordesign", "styling",
        ],
        instagram_categories=[
            "Interior Design Studio", "Home Decor",
            "Furniture Store", "Architect",
            "Home Improvement",
        ],
        related_niches=["real_estate", "art", "wedding"],
    ),
    "medical": NicheDefinition(
        name="medical",
        display_name="Medical & Healthcare",
        keywords_pl=[
            "lekarz", "medycyna", "klinika", "zdrowie", "pacjent",
            "chirurg", "stomatolog", "dermatolog", "ortopeda",
            "fizjoterapeuta", "gabinet", "diagnostyka", "rehabilitacja",
        ],
        keywords_en=[
            "doctor", "medical", "clinic", "health", "patient",
            "surgeon", "dentist", "dermatologist", "orthopedic",
            "physiotherapy", "healthcare", "diagnostics", "rehab",
        ],
        instagram_categories=[
            "Doctor", "Medical Center", "Dentist & Dental Office",
            "Hospital", "Medical & Health",
        ],
        related_niches=["wellness", "beauty", "fitness"],
    ),
    "pet": NicheDefinition(
        name="pet",
        display_name="Pets & Animals",
        keywords_pl=[
            "pies", "kot", "zwierzęta", "pupil", "weterynarz",
            "hodowla", "groomer", "karma", "adopcja", "schronisko",
            "akwarium", "pielęgnacja", "rasa",
        ],
        keywords_en=[
            "dog", "cat", "pets", "animals", "veterinary",
            "breeder", "groomer", "petfood", "adoption", "shelter",
            "aquarium", "petcare", "puppy",
        ],
        instagram_categories=[
            "Pet Service", "Veterinarian", "Pet Store",
            "Animal Shelter", "Pet Groomer",
        ],
        related_niches=["lifestyle", "photography", "medical"],
    ),
    "art": NicheDefinition(
        name="art",
        display_name="Art & Design",
        keywords_pl=[
            "sztuka", "grafika", "ilustracja", "malarstwo", "rysunek",
            "galeria", "plakat", "obraz", "kreacja", "artysta",
            "wystawia", "portret", "ceramika",
        ],
        keywords_en=[
            "art", "graphic", "illustration", "painting", "drawing",
            "gallery", "poster", "artwork", "creative", "artist",
            "exhibition", "portrait", "ceramics",
        ],
        instagram_categories=[
            "Artist", "Art", "Art Gallery", "Graphic Designer",
            "Art Museum", "Visual Arts",
        ],
        related_niches=["photography", "fashion", "interior"],
    ),
    "sport": NicheDefinition(
        name="sport",
        display_name="Sport & Teams",
        keywords_pl=[
            "sport", "drużyna", "mecz", "liga", "piłka nożna",
            "koszykówka", "siatkówka", "tenis", "pływanie", "boks",
            "stadion", "zawodnik", "mistrzostwa",
        ],
        keywords_en=[
            "sport", "team", "match", "league", "football",
            "basketball", "volleyball", "tennis", "swimming", "boxing",
            "stadium", "athlete", "championship",
        ],
        instagram_categories=[
            "Sports Team", "Sports League", "Athlete",
            "Stadium, Arena & Sports Venue", "Sports Club",
        ],
        related_niches=["fitness", "coaching", "photography"],
    ),
    "lifestyle": NicheDefinition(
        name="lifestyle",
        display_name="Lifestyle & Inspiration",
        keywords_pl=[
            "lifestyle", "inspiracja", "codzienność", "styl życia",
            "motywacja", "porady", "blog", "vlog", "influencer",
            "mama", "rodzina", "minimalizm", "organizacja",
        ],
        keywords_en=[
            "lifestyle", "inspiration", "daily", "blogger", "vlogger",
            "influencer", "mom", "family", "minimalism", "organize",
            "tips", "motivation", "aesthetic",
        ],
        instagram_categories=[
            "Blogger", "Public Figure", "Creator",
            "Video Creator", "Personal Blog",
        ],
        related_niches=["fashion", "beauty", "travel"],
    ),
}

# ── General niche fallback ─────────────────────────────────────────

_GENERAL_RESULT_TEMPLATE = NicheResult(
    primary_niche="general",
    display_name="General",
    confidence=0.0,
    matched_keywords=[],
    language="unknown",
)


# ── Text cleaning ──────────────────────────────────────────────────

def _clean_text(text: Optional[str]) -> str:
    """Normalize text: lowercase, remove emoji/URLs/mentions."""
    if not text:
        return ""
    text = text.lower()
    text = _EMOJI_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(" ", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _keyword_match(keyword: str, text: str, strict: bool = False) -> bool:
    """Check if keyword matches in text.

    For multi-word keywords: exact substring match.
    For single-word keywords: word boundary match (whole word or stem).

    Args:
        keyword: The keyword to search for (lowercase).
        text: The text to search in (lowercase).
        strict: If True, require exact whole-word match only (for categories).
    """
    if not keyword or not text:
        return False

    # Multi-word keyword: exact substring match
    if " " in keyword:
        return keyword in text

    # Strict mode: whole word only (for category matching)
    if strict:
        words = text.split()
        return keyword in words

    # Single-word: check whole words in text
    words = text.split()
    for word in words:
        # Exact word match
        if word == keyword:
            return True
        # Stem matching: only if keyword >= 6 chars AND same language root
        # (keyword is start of word OR word is start of keyword)
        if len(keyword) >= 6 and len(word) >= 6:
            if word.startswith(keyword) or keyword.startswith(word):
                return True
    return False


# ── Core classification ────────────────────────────────────────────

def classify_profile(
    bio: Optional[str] = None,
    category: Optional[str] = None,
    full_name: Optional[str] = None,
    username: Optional[str] = None,
) -> NicheResult:
    """Classify an Instagram profile into a niche using keyword matching.

    Args:
        bio: Profile biography text.
        category: Instagram category string (e.g. "Personal Trainer").
        full_name: Display name on the profile.
        username: Instagram handle.

    Returns:
        NicheResult with primary niche, confidence, and matched keywords.
    """
    clean_bio = _clean_text(bio)
    clean_category = _clean_text(category)
    clean_name = _clean_text(full_name)
    clean_user = _clean_text(username)

    # Split username on separators for word-level matching
    username_parts = re.split(r"[_.\-]", clean_user) if clean_user else []
    username_text = " ".join(username_parts)

    scores: Dict[str, float] = {}
    matched: Dict[str, List[str]] = {}

    for niche_name, definition in NICHE_TAXONOMY.items():
        score = 0.0
        niche_matched: List[str] = []
        all_keywords = definition.keywords_pl + definition.keywords_en

        # Category match (highest weight) — exact match only
        if clean_category:
            clean_cat_lower = clean_category.strip()
            for cat in definition.instagram_categories:
                cat_lower = cat.lower()
                # Full category string match (e.g., "personal trainer" == "personal trainer")
                if cat_lower == clean_cat_lower or cat_lower in clean_cat_lower:
                    score += 10
                    niche_matched.append(cat)
                    break

        # Keyword matching across fields
        for kw in all_keywords:
            kw_lower = kw.lower()

            if clean_bio and _keyword_match(kw_lower, clean_bio):
                score += 3
                if kw_lower not in niche_matched:
                    niche_matched.append(kw_lower)

            if clean_name and _keyword_match(kw_lower, clean_name):
                score += 5
                if kw_lower not in niche_matched:
                    niche_matched.append(kw_lower)

            if username_text and _keyword_match(kw_lower, username_text):
                score += 2
                if kw_lower not in niche_matched:
                    niche_matched.append(kw_lower)

        scores[niche_name] = score
        matched[niche_name] = niche_matched

    # Find best and second-best
    sorted_niches = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # Minimum score threshold: require at least 6 points to classify
    # (1 category match = 10, 2 bio keywords = 6, 1 name keyword = 5)
    _MIN_SCORE = 6
    if not sorted_niches or sorted_niches[0][1] < _MIN_SCORE:
        result = NicheResult(
            primary_niche="general",
            display_name="General",
            confidence=0.0,
            matched_keywords=[],
            language=detect_language(clean_bio),
            all_scores=scores,
        )
        logger.debug("No niche match for profile (username=%s)", username)
        return result

    best_name, best_score = sorted_niches[0]
    second_name, second_score = sorted_niches[1] if len(sorted_niches) > 1 else ("", 0.0)

    # Determine secondary niche
    secondary: Optional[str] = None
    if second_score > 0 and second_score > (best_score * 0.5):
        secondary = second_name

    # Confidence calculation
    if second_score > 0:
        confidence = best_score / (best_score + second_score)
    else:
        confidence = 0.9

    # Clamp confidence
    confidence = max(0.0, min(1.0, confidence))

    definition = NICHE_TAXONOMY[best_name]
    lang = detect_language(clean_bio)

    result = NicheResult(
        primary_niche=best_name,
        display_name=definition.display_name,
        confidence=round(confidence, 3),
        matched_keywords=matched[best_name],
        language=lang,
        secondary_niche=secondary,
        all_scores=scores,
    )

    logger.debug(
        "Classified profile (username=%s) as %s (%.1f%% confidence)",
        username, best_name, confidence * 100,
    )
    return result


# ── Niche match scoring ────────────────────────────────────────────

def compute_niche_match(
    target_result: NicheResult,
    candidate_bio: Optional[str] = None,
    candidate_category: Optional[str] = None,
    candidate_full_name: Optional[str] = None,
    candidate_username: Optional[str] = None,
) -> float:
    """Compute a 0-100 niche match score between a target and candidate profile.

    Args:
        target_result: NicheResult of the target profile.
        candidate_bio: Candidate profile bio.
        candidate_category: Candidate Instagram category.
        candidate_full_name: Candidate display name.
        candidate_username: Candidate Instagram handle.

    Returns:
        Float score 0-100 indicating niche similarity.
    """
    candidate_result = classify_profile(
        bio=candidate_bio,
        category=candidate_category,
        full_name=candidate_full_name,
        username=candidate_username,
    )

    target_niche = target_result.primary_niche
    candidate_niche = candidate_result.primary_niche

    # Base score from niche relationship
    if target_niche == candidate_niche:
        base = 60.0
    else:
        target_def = NICHE_TAXONOMY.get(target_niche)
        candidate_def = NICHE_TAXONOMY.get(candidate_niche)

        target_related = target_def.related_niches if target_def else []
        candidate_related = candidate_def.related_niches if candidate_def else []

        if candidate_niche in target_related:
            base = 40.0
        elif target_niche in candidate_related:
            base = 35.0
        else:
            base = 10.0

    # Bonus: shared keywords (+2 per shared keyword, max +20)
    target_kw_set = set(target_result.matched_keywords)
    candidate_kw_set = set(candidate_result.matched_keywords)
    shared = target_kw_set & candidate_kw_set
    keyword_bonus = min(len(shared) * 2.0, 20.0)

    # Bonus: same Instagram category (+10)
    category_bonus = 0.0
    if candidate_category and target_result.primary_niche != "general":
        target_def = NICHE_TAXONOMY.get(target_niche)
        if target_def:
            clean_cat = _clean_text(candidate_category)
            for cat in target_def.instagram_categories:
                if _keyword_match(cat.lower(), clean_cat):
                    category_bonus = 10.0
                    break

    # Bonus: both high confidence (+10)
    confidence_bonus = 0.0
    if target_result.confidence >= 0.7 and candidate_result.confidence >= 0.7:
        confidence_bonus = 10.0

    score = base + keyword_bonus + category_bonus + confidence_bonus
    return min(score, 100.0)


# ── Language detection ─────────────────────────────────────────────

def detect_language(text: Optional[str]) -> str:
    """Detect language of text using simple heuristics.

    Returns "pl" for Polish, "en" for English, "unknown" if text is empty.
    """
    if not text or not text.strip():
        return "unknown"

    text_lower = text.lower()
    polish_score = 0

    # Count Polish-specific characters
    for ch in text_lower:
        if ch in _POLISH_CHARS:
            polish_score += 1

    # Count Polish words
    words = text_lower.split()
    for word in words:
        if word in _POLISH_WORDS:
            polish_score += 1

    if polish_score >= 2:
        return "pl"
    return "en"


# ── Keyword extraction ─────────────────────────────────────────────

def extract_niche_keywords(
    text: Optional[str],
    language: str = "auto",
) -> Set[str]:
    """Extract niche-relevant keywords from text.

    Args:
        text: Raw text to extract keywords from.
        language: "pl", "en", or "auto" (auto-detects).

    Returns:
        Set of lowercase keyword strings.
    """
    if not text or not text.strip():
        return set()

    cleaned = _clean_text(text)
    words = cleaned.split()

    result: Set[str] = set()
    for word in words:
        # Filter: length >= 3, alphabetic, not a stopword
        if len(word) >= 3 and word.isalpha() and word not in _STOPWORDS:
            result.add(word)

    return result
