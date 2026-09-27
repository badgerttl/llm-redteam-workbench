"""Shared human-readable catalog metadata for user interfaces."""

PROFILE_DESCRIPTIONS = {
    "baseline": "One technique per case across the full catalog.",
    "unicode": "One Unicode-focused technique per case.",
    "encoding": "One encoding technique per case.",
    "comprehensive": "Full catalog with chains of up to three techniques.",
    "chained": "Only two- or three-technique combinations.",
}

TECHNIQUE_DESCRIPTIONS = {
    "leetspeak": "Letter-to-number and symbol substitutions",
    "homoglyph": "Visually similar Greek and Cyrillic characters",
    "unicode_style": "Mathematical, circled, superscript, and subscript forms",
    "fullwidth": "Full-width compatibility characters",
    "zero_width": "Invisible separators between characters",
    "whitespace": "Spacing-based character fragmentation",
    "punctuation": "Punctuation-based character fragmentation",
    "random_case": "Mixed upper- and lowercase letters",
    "separator": "Visible separators between characters",
    "reverse": "Reversed code-point order",
    "base64": "Base64-encoded UTF-8 text",
    "hex": "Raw, 0xNN, and \\xNN hexadecimal forms",
    "url": "Whole and selective percent encoding",
    "combining": "Unicode combining-mark noise",
    "normalization": "NFC, NFD, NFKC, and NFKD forms",
    "html_entity": "HTML numeric character references",
    "unicode_escape": "\\u, \\U, and \\N{name} escape forms",
}

DISPLAY_NAME_OVERRIDES = {
    "base64": "Base64",
    "html_entity": "HTML Entity",
    "url": "URL",
}


def display_name(name: str) -> str:
    """Return a consistent title for a machine-readable technique name."""
    return DISPLAY_NAME_OVERRIDES.get(name, name.replace("_", " ").title())
