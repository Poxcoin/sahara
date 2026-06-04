"""
Генерація промптів для hero изображень на основі теми та фото користувача.
"""

HERO_TEMPLATES = {
    "editorial": {
        "title": "SAHARA Editorial",
        "prompt_base": "Luxury fashion editorial photoshoot for SAHARA brand",
        "style": "high-end fashion magazine aesthetic, natural lighting, minimalist background",
    },
    "collection": {
        "title": "New Collection",
        "prompt_base": "Fashion collection showcase for SAHARA clothing brand",
        "style": "modern minimalist, studio lighting, neutral background, elegant composition",
    },
    "lookbook": {
        "title": "Seasonal Lookbook",
        "prompt_base": "Seasonal fashion lookbook for SAHARA brand",
        "style": "lifestyle photography, soft natural light, editorial styling, trendy poses",
    },
    "minimal": {
        "title": "Minimalist Series",
        "prompt_base": "Minimalist fashion photography for SAHARA brand",
        "style": "clean composition, neutral tones, geometric shapes, contemporary aesthetic",
    },
}


def generate_hero_prompt(theme: str = "editorial", user_photo_desc: str = "") -> str:
    """
    Генерує промпт для AI генератора hero изображення.

    theme: "editorial", "collection", "lookbook", "minimal"
    user_photo_desc: опис фото користувача для інкорпорації (напр. "dark long hair, elegant woman")
    """
    template = HERO_TEMPLATES.get(theme, HERO_TEMPLATES["editorial"])

    base = template["prompt_base"]
    style = template["style"]

    if user_photo_desc:
        prompt = (
            f"{base}\n"
            f"Featuring a model with {user_photo_desc}\n"
            f"Style: {style}\n"
            f"Quality: 8k, professional photography, sharp focus, intricate details\n"
            f"Composition: Full body or 3/4 shot, confident pose, looking at camera"
        )
    else:
        prompt = (
            f"{base}\n"
            f"Style: {style}\n"
            f"Quality: 8k, professional photography, sharp focus, intricate details\n"
            f"Composition: Full body or 3/4 shot, confident model, elegant styling"
        )

    return prompt


def get_banner_rotation(season: str = "spring") -> dict:
    """
    Повертає конфіг для ротації банерів по сезонах.
    """
    configs = {
        "spring": {
            "prompt_suffix": ", light pastel colors, floral elements, fresh aesthetic",
            "overlay_color": "rgba(240, 232, 215, 0.2)",
        },
        "summer": {
            "prompt_suffix": ", bright sunlit, vibrant colors, beachy vibes, flowing fabrics",
            "overlay_color": "rgba(255, 220, 100, 0.15)",
        },
        "fall": {
            "prompt_suffix": ", warm earth tones, cozy atmosphere, layered clothing, texture",
            "overlay_color": "rgba(200, 140, 80, 0.2)",
        },
        "winter": {
            "prompt_suffix": ", cool tones, metallic accents, luxury feel, minimalist lines",
            "overlay_color": "rgba(220, 220, 220, 0.25)",
        },
    }
    return configs.get(season, configs["spring"])


# Попередньо генеровані теми для швидкого старту
PRESET_THEMES = {
    "sahara_desert": "sandy desert landscape at sunset, luxury fashion model in elegant SAHARA clothing, golden hour lighting, cinematic quality",
    "minimalist_luxury": "white studio background, luxury fashion woman in minimalist SAHARA outfit, professional lighting, editorial style, 8k quality",
    "urban_editorial": "modern city backdrop, fashionable woman in SAHARA clothing, street style editorial, natural daylight, magazine quality",
    "elegant_studio": "soft studio lighting, elegant woman in SAHARA collection, neutral background, professional fashion photography, sharp focus",
}
