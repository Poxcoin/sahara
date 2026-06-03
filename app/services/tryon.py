"""Category detection helper (try-on removed — use fashn.py instead)."""


def detect_category(title: str, description: str = "") -> str:
    text = f"{title} {description}".lower()
    if any(w in text for w in ["сукня", "плаття", "dress", "elbise", "abiye", "комбінезон"]):
        return "dress"
    if any(w in text for w in ["штани", "джинси", "спідниця", "шорти",
                                "pantolon", "etek", "şort", "tayt", "eşofman alt"]):
        return "bottoms"
    return "tops"
