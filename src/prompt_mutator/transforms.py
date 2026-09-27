from __future__ import annotations

import base64
import random
import unicodedata
from dataclasses import dataclass
from typing import Callable, TypeAlias
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class Mutation:
    text: str
    positions: tuple[int, ...]
    parameters: dict[str, object]


Transform: TypeAlias = Callable[[str, random.Random, str], Mutation]


_INTENSITY = {"low": 0.15, "medium": 0.40, "high": 0.75, "max": 1.0}
_LEET = {
    "a": ("4", "@"), "e": ("3",), "i": ("1", "!"),
    "o": ("0",), "s": ("5", "$"), "t": ("7", "+"),
}
_HOMOGLYPH = {
    "A": "А", "B": "В", "C": "Ϲ", "E": "Ε", "H": "Н",
    "I": "І", "K": "Κ", "M": "Μ", "O": "Ο", "P": "Р",
    "T": "Τ", "X": "Χ", "a": "а", "c": "с", "e": "е",
    "i": "і", "j": "ј", "o": "о", "p": "р", "s": "ѕ", "x": "х",
}


def technique_names() -> tuple[str, ...]:
    return tuple(_TRANSFORMS)


def mutate(
    name: str,
    prompt: str,
    seed: int,
    intensity: str,
    variant_index: int = 0,
    extensions: dict[str, Transform] | None = None,
) -> Mutation:
    try:
        transform = _TRANSFORMS[name]
    except KeyError as exc:
        if extensions is None or name not in extensions:
            raise ValueError(f"unknown technique: {name}") from exc
        transform = extensions[name]
    rng = random.Random(f"{name}:{seed}:{variant_index}:{prompt}")
    if name == "leetspeak":
        leet_variant = ("basic", "symbol-heavy", "mixed")[variant_index % 3]
        if leet_variant == "basic":
            base_mapping = {key: values[0] for key, values in _LEET.items()}
        elif leet_variant == "symbol-heavy":
            base_mapping = {key: values[-1] for key, values in _LEET.items()}
        else:
            base_mapping = dict(_LEET)
        mapping = {**base_mapping, **{key.upper(): value for key, value in base_mapping.items()}}
        mutation = _replace(prompt, mapping, rng, intensity, leet_variant)
    elif name == "normalization":
        form = ("NFD", "NFC", "NFKD", "NFKC")[variant_index % 4]
        text = unicodedata.normalize(form, prompt)
        positions = tuple(range(len(prompt))) if text != prompt else ()
        mutation = Mutation(
            text,
            positions,
            {"variant": form, "unicode_version": unicodedata.unidata_version},
        )
    elif name == "unicode_style":
        mutation = _unicode_style_variant(prompt, rng, intensity, variant_index % 4)
    elif name == "unicode_escape" and variant_index % 3 == 1:
        eligible = [i for i, char in enumerate(prompt) if unicodedata.name(char, "")]
        positions = _selected(prompt, eligible, rng, intensity)
        chosen = set(positions)
        text = "".join(
            f"\\N{{{unicodedata.name(char)}}}" if index in chosen else char
            for index, char in enumerate(prompt)
        )
        mutation = Mutation(text, positions, {"variant": "unicode-name", "intensity": intensity})
    elif name == "unicode_escape" and variant_index % 3 == 2:
        positions = _selected(prompt, [i for i, char in enumerate(prompt) if not char.isspace()], rng, intensity)
        chosen = set(positions)
        text = "".join(f"\\U{ord(char):08X}" if index in chosen else char for index, char in enumerate(prompt))
        mutation = Mutation(text, positions, {"variant": "unicode-32-bit", "intensity": intensity})
    elif name == "url" and variant_index > 0:
        positions = _selected(prompt, list(range(len(prompt))), rng, intensity)
        chosen = set(positions)
        text = "".join(
            "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
            if index in chosen
            else char
            for index, char in enumerate(prompt)
        )
        mutation = Mutation(
            text,
            positions,
            {"variant": "mixed", "format": "%NN", "intensity": intensity},
        )
    elif name == "hex" and variant_index == 0:
        positions = tuple(i for i, char in enumerate(prompt) if char == " ")
        mutation = Mutation(
            prompt.replace(" ", r"\x20"),
            positions,
            {"variant": "spaces", "format": "\\xNN"},
        )
    else:
        mutation = transform(prompt, rng, intensity)
    return Mutation(
        mutation.text,
        mutation.positions,
        {**mutation.parameters, "sample": variant_index},
    )


def _selected(
    prompt: str,
    eligible: list[int],
    rng: random.Random,
    intensity: str,
) -> tuple[int, ...]:
    if not eligible:
        return ()
    fraction = _INTENSITY[intensity]
    count = max(1, round(len(eligible) * fraction))
    return tuple(sorted(rng.sample(eligible, min(count, len(eligible)))))


def _replace(
    prompt: str,
    mapping: dict[str, str | tuple[str, ...]],
    rng: random.Random,
    intensity: str,
    variant: str,
) -> Mutation:
    positions = _selected(prompt, [i for i, c in enumerate(prompt) if c in mapping], rng, intensity)
    output = list(prompt)
    for index in positions:
        replacement = mapping[prompt[index]]
        if isinstance(replacement, tuple):
            replacement = replacement[rng.randrange(len(replacement))]
        output[index] = replacement
    return Mutation("".join(output), positions, {"variant": variant, "intensity": intensity})


def _leetspeak(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    mapping = {key: value for key, value in _LEET.items()}
    mapping.update({key.upper(): value for key, value in _LEET.items()})
    return _replace(prompt, mapping, rng, intensity, "mixed")


def _homoglyph(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    mutation = _replace(prompt, _HOMOGLYPH, rng, intensity, "curated-confusables-v1")
    return Mutation(mutation.text, mutation.positions, {**mutation.parameters, "scripts": ["Cyrillic", "Greek"]})


def _unicode_style(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    return _unicode_style_variant(prompt, rng, intensity, 0)


def _unicode_style_variant(
    prompt: str,
    rng: random.Random,
    intensity: str,
    variant: int,
) -> Mutation:
    mapping: dict[str, str] = {}
    if variant == 0:
        for char in prompt:
            if "A" <= char <= "Z":
                mapping[char] = chr(0x1D400 + ord(char) - ord("A"))
            elif "a" <= char <= "z":
                mapping[char] = chr(0x1D41A + ord(char) - ord("a"))
            elif "0" <= char <= "9":
                mapping[char] = chr(0x1D7CE + ord(char) - ord("0"))
        label = "mathematical-bold"
    elif variant == 1:
        for char in prompt:
            if "A" <= char <= "Z":
                mapping[char] = chr(0x24B6 + ord(char) - ord("A"))
            elif "a" <= char <= "z":
                mapping[char] = chr(0x24D0 + ord(char) - ord("a"))
            elif char == "0":
                mapping[char] = "⓪"
            elif "1" <= char <= "9":
                mapping[char] = chr(0x2460 + ord(char) - ord("1"))
        label = "circled"
    elif variant == 2:
        mapping = {
            "A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ", "G": "ᴳ",
            "H": "ᴴ", "I": "ᴵ", "J": "ᴶ", "K": "ᴷ", "M": "ᴹ",
            "N": "ᴺ", "O": "ᴼ", "P": "ᴾ", "R": "ᴿ", "T": "ᵀ",
            "U": "ᵁ", "V": "ⱽ", "W": "ᵂ",
            "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
            "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ",
            "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ",
            "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
            "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
            "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
        }
        label = "superscript"
    else:
        mapping = {
            "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
            "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
            "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
            "v": "ᵥ", "x": "ₓ", "0": "₀", "1": "₁", "2": "₂",
            "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇",
            "8": "₈", "9": "₉",
        }
        label = "subscript"
    return _replace(prompt, mapping, rng, intensity, label)


def _fullwidth(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    mapping = {chr(code): chr(code + 0xFEE0) for code in range(0x21, 0x7F)}
    mapping[" "] = "\u3000"
    return _replace(prompt, mapping, rng, intensity, "fullwidth")


def _insert_after(prompt: str, rng: random.Random, intensity: str, inserted: str, variant: str) -> Mutation:
    positions = _selected(prompt, list(range(len(prompt))), rng, intensity)
    chosen = set(positions)
    text = "".join(char + (inserted if index in chosen else "") for index, char in enumerate(prompt))
    return Mutation(text, positions, {"variant": variant, "inserted": f"U+{ord(inserted):04X}", "intensity": intensity})


def _zero_width(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    return _insert_after(prompt, rng, intensity, "\u200b", "zero-width-space")


def _whitespace(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    eligible = [i for i, char in enumerate(prompt) if not char.isspace()]
    positions = _selected(prompt, eligible, rng, intensity)
    chosen = set(positions)
    return Mutation("".join(char + (" " if i in chosen else "") for i, char in enumerate(prompt)), positions, {"variant": "character-fragmentation", "intensity": intensity})


def _punctuation(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    return _insert_after(prompt, rng, intensity, ".", "period-fragmentation")


def _random_case(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    eligible = [i for i, char in enumerate(prompt) if char.isalpha()]
    positions = _selected(prompt, eligible, rng, intensity)
    output = list(prompt)
    for index in positions:
        output[index] = output[index].swapcase()
    return Mutation("".join(output), positions, {"variant": "swap-selected", "intensity": intensity})


def _separator(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    return _insert_after(prompt, rng, intensity, "·", "middle-dot")


def _reverse(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    del rng, intensity
    return Mutation(prompt[::-1], tuple(range(len(prompt))), {"variant": "codepoint-reverse"})


def _base64(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    del rng, intensity
    text = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    return Mutation(text, tuple(range(len(prompt))), {"variant": "utf8-whole-string"})


def _hex(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    # The first form intentionally targets the common "spaces only" bypass.
    selector = rng.randrange(4)
    if selector == 0:
        positions = tuple(i for i, char in enumerate(prompt) if char == " ")
        return Mutation(prompt.replace(" ", r"\x20"), positions, {"variant": "spaces", "format": "\\xNN"})
    if selector == 1:
        positions = tuple(range(len(prompt)))
        text = "".join(f"\\x{byte:02x}" for byte in prompt.encode("utf-8"))
        return Mutation(text, positions, {"variant": "whole", "format": "\\xNN-lower"})
    if selector == 2:
        positions = tuple(range(len(prompt)))
        text = " ".join(f"0x{byte:02X}" for byte in prompt.encode("utf-8"))
        return Mutation(text, positions, {"variant": "whole", "format": "0xNN-upper-spaced"})
    eligible = [i for i, char in enumerate(prompt) if ord(char) < 128]
    positions = _selected(prompt, eligible, rng, intensity)
    chosen = set(positions)
    text = "".join(f"\\x{ord(char):02x}" if i in chosen and ord(char) < 128 else char for i, char in enumerate(prompt))
    return Mutation(text, positions, {"variant": "mixed", "format": "\\xNN-lower"})


def _url(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    del rng, intensity
    text = quote(prompt, safe="")
    return Mutation(text, tuple(i for i, char in enumerate(prompt) if not char.isalnum()), {"variant": "percent-utf8"})


def _combining(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    return _insert_after(prompt, rng, intensity, "\u0338", "combining-long-solidus-overlay")


def _normalization(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    del rng, intensity
    text = unicodedata.normalize("NFD", prompt)
    positions = tuple(i for i, (a, b) in enumerate(zip(prompt, text)) if a != b)
    if text != prompt and not positions:
        positions = tuple(range(len(prompt)))
    return Mutation(text, positions, {"variant": "NFD", "unicode_version": unicodedata.unidata_version})


def _html_entity(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    positions = _selected(prompt, [i for i, c in enumerate(prompt) if c.isalpha()], rng, intensity)
    chosen = set(positions)
    text = "".join(f"&#x{ord(char):X};" if i in chosen else char for i, char in enumerate(prompt))
    return Mutation(text, positions, {"variant": "hex-numeric-reference", "intensity": intensity})


def _unicode_escape(prompt: str, rng: random.Random, intensity: str) -> Mutation:
    positions = _selected(prompt, [i for i, c in enumerate(prompt) if not c.isspace()], rng, intensity)
    chosen = set(positions)
    def escaped(char: str) -> str:
        return f"\\u{ord(char):04X}" if ord(char) <= 0xFFFF else f"\\U{ord(char):08X}"
    text = "".join(escaped(char) if i in chosen else char for i, char in enumerate(prompt))
    return Mutation(text, positions, {"variant": "python-style", "intensity": intensity})


_TRANSFORMS: dict[str, Transform] = {
    "leetspeak": _leetspeak,
    "homoglyph": _homoglyph,
    "unicode_style": _unicode_style,
    "fullwidth": _fullwidth,
    "zero_width": _zero_width,
    "whitespace": _whitespace,
    "punctuation": _punctuation,
    "random_case": _random_case,
    "separator": _separator,
    "reverse": _reverse,
    "base64": _base64,
    "hex": _hex,
    "url": _url,
    "combining": _combining,
    "normalization": _normalization,
    "html_entity": _html_entity,
    "unicode_escape": _unicode_escape,
}
