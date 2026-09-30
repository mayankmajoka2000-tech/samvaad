"""Languages Samvaad offers in the interface.

Whisper recognises all of these; Qwen3 translates between them. Speech output uses
the voices installed in Windows (Settings > Time & language > Speech).
"""

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English", "voice": "en-IN"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "voice": "hi-IN"},
    "bn": {"name": "Bengali", "native": "বাংলা", "voice": "bn-IN"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "voice": "ta-IN"},
    "te": {"name": "Telugu", "native": "తెలుగు", "voice": "te-IN"},
    "mr": {"name": "Marathi", "native": "मराठी", "voice": "mr-IN"},
    "gu": {"name": "Gujarati", "native": "ગુજરાતી", "voice": "gu-IN"},
    "kn": {"name": "Kannada", "native": "ಕನ್ನಡ", "voice": "kn-IN"},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "voice": "ml-IN"},
    "pa": {"name": "Punjabi", "native": "ਪੰਜਾਬੀ", "voice": "pa-IN"},
    "ur": {"name": "Urdu", "native": "اردو", "voice": "ur-PK"},
    "es": {"name": "Spanish", "native": "Español", "voice": "es-ES"},
    "fr": {"name": "French", "native": "Français", "voice": "fr-FR"},
    "de": {"name": "German", "native": "Deutsch", "voice": "de-DE"},
    "ar": {"name": "Arabic", "native": "العربية", "voice": "ar-SA"},
    "sw": {"name": "Swahili", "native": "Kiswahili", "voice": "sw-KE"},
    "ja": {"name": "Japanese", "native": "日本語", "voice": "ja-JP"},
    "zh": {"name": "Chinese", "native": "中文", "voice": "zh-CN"},
    "ru": {"name": "Russian", "native": "Русский", "voice": "ru-RU"},
    "pt": {"name": "Portuguese", "native": "Português", "voice": "pt-BR"},
}


def name(code: str) -> str:
    return LANGUAGES.get(code, {}).get("name", code)
