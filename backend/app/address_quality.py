"""Derive address-quality reason codes without retaining the street address."""
import re
import unicodedata

CITIES = {
    "karachi": ("karachi", "کراچی"),
    "lahore": ("lahore", "لاہور"),
    "islamabad": ("islamabad", "اسلام آباد", "اسلاماباد"),
    "rawalpindi": ("rawalpindi", "راولپنڈی", "راول پنڈی", "pindi"),
    "faisalabad": ("faisalabad", "فیصل آباد", "فیصلاباد"),
    "multan": ("multan", "ملتان"),
    "peshawar": ("peshawar", "پشاور"),
    "quetta": ("quetta", "کوئٹہ", "کوئیٹہ"),
    "sialkot": ("sialkot", "سیالکوٹ"),
    "hyderabad": ("hyderabad", "حیدرآباد", "حیدر آباد"),
    "gujranwala": ("gujranwala", "گوجرانوالہ", "گوجرانوالا"),
    "sukkur": ("sukkur", "سکھر"),
    "bahawalpur": ("bahawalpur", "بہاولپور", "بہاول پور"),
    "sargodha": ("sargodha", "سرگودھا"),
}
CITY_BY_ALIAS = {alias: city for city, aliases in CITIES.items() for alias in aliases}
ID_WORD = re.compile(r"\b(?:house|home|flat|plot|shop|street|st|gali|makaan|makan|ghar|"
                     r"مکان|گھر|فلیٹ|پلاٹ|دکان|گلی|سٹریٹ|اسٹریٹ)\s+(?:no\.?\s+|number\s+|نمبر\s+)?"
                     r"#?\s*(?:[a-z]?\d+[a-z]?|[a-z](?=\s*[-/]))\b")
NUMBER_AND_STREET = re.compile(r"(?<!\w)\d+[a-z]?\s+[\w ]{2,35}\b(?:road|lane|street|avenue|گلی|روڈ)\b")
LANDMARK = re.compile(r"\b(?:near|opposite|behind|next to|by|qareeb|samne|paas|masjid|"
                      r"mosque|hospital|school|landmark|قریب|سامنے|پاس|مسجد|ہسپتال|اسکول)\b")
REASONS = {
    "too_short": "Address is too short",
    "missing_identifier": "House or street identifier is missing",
    "landmark_only": "Address relies on a landmark",
    "city_mismatch": "City in the address differs from the order city",
    "city_misspelling": "City in the address may be misspelled",
}
CLARIFICATION = "Please confirm your delivery city and share your house or flat number, street and area."


def normalized(text):
    text = unicodedata.normalize("NFKC", str(text or "")).casefold().translate(str.maketrans("يك", "یک"))
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


def city_key(city):
    text = normalized(city)
    return CITY_BY_ALIAS.get(text, text)


def _one_edit(left, right):
    if len(left) == len(right):
        differing = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        return len(differing) == 1 or (len(differing) == 2 and differing[1] == differing[0] + 1
                                        and left[differing[0]:differing[1]+1] ==
                                        right[differing[0]:differing[1]+1][::-1])
    if len(left) < len(right):
        left, right = right, left
    return len(left) == len(right) + 1 and any(left[:i] + left[i+1:] == right for i in range(len(left)))


def _city_issue(address, expected):
    if not expected:
        return None
    # Prefer a final comma-delimited city, then a recognized one/two-token suffix.
    tail = re.split("[,،;؛]", address)[-1].strip(" .۔")
    tail = re.sub(r"^(?:city|شہر)\s*:?\s+", "", tail)
    tokens = tail.split()
    options = [" ".join(tokens[-length:]) for length in (2, 1) if len(tokens) >= length]
    for candidate in options:
        if candidate in CITY_BY_ALIAS or candidate == expected:
            return "city_mismatch" if city_key(candidate) != expected else None
    aliases = (alias for alias, city in CITY_BY_ALIAS.items() if city == expected and len(alias) >= 4)
    if any(_one_edit(alias, candidate) for alias in aliases for candidate in options):
        return "city_misspelling"
    return None


def classify_address(address, city):
    if address is None:
        return None
    address = normalized(address)
    issues = []
    if len(re.findall(r"\w+", address)) < 4:
        issues.append("too_short")
    if not (ID_WORD.search(address) or NUMBER_AND_STREET.search(address)):
        issues.append("missing_identifier")
        if LANDMARK.search(address):
            issues.append("landmark_only")
    if issue := _city_issue(address, city_key(city)):
        issues.append(issue)
    return issues
