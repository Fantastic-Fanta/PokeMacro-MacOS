import re
from typing import Sequence

remove_chronos_event_phrase = lambda text: re.sub(
    r"\s+",
    " ",
    re.sub(r"\b[Cc]hronos\s+[Ee]vent\s+2025\s+is\s+out\b", "", text, flags=re.IGNORECASE),
).strip()


def trim_text_from_username_to_attempts(text: str, username: str) -> str:
    text_lower, username_lower = text.lower(), username.lower()
    username_index = text_lower.find(username_lower)
    if username_index == -1:
        return text
    search_text_lower = text_lower[username_index:]
    attempts_index = search_text_lower.find("attempts")
    if attempts_index == -1:
        return text[username_index:]
    return text[username_index : username_index + attempts_index + len("attempts")]


def trim_text_from_username_to_pokemon(text: str, username: str, pokemon_name: str) -> str:
    """Return the slice of text spanning from username through pokemon_name, or empty string."""
    text_lower = text.lower()
    username_index = text_lower.find(username.lower())
    if username_index == -1:
        return ""
    search_start = username_index + len(username)
    pokemon_index = text_lower.find(pokemon_name.lower(), search_start)
    if pokemon_index == -1:
        return text[username_index:]
    return text[username_index : pokemon_index + len(pokemon_name)]


def matches_chat_config(
    segment: str,
    reskins: Sequence[str],
    gradients: Sequence[str],
    is_reskin: bool,
    is_shiny: bool,
    is_gradient: bool,
    is_any: bool,
    is_good: bool,
) -> bool:
    """Check whether a chat segment (username…pokemon) matches the configured filters."""
    seg = segment.lower()
    has_reskin   = any(r.lower() in seg for r in reskins)
    has_gradient = any(g.lower() in seg for g in gradients)
    has_shiny    = "shiny" in seg
    if not any([is_any, is_reskin, is_shiny, is_gradient, is_good]):
        return False
    if is_good and (
        (has_shiny and has_gradient)
        or (has_reskin and has_gradient)
        or (has_shiny and has_reskin)
    ):
        return True
    if is_any and (has_reskin or has_gradient):
        return True
    if is_reskin and has_reskin:
        return True
    if is_shiny and has_shiny:
        return True
    if is_gradient and has_gradient:
        return True
    return False


def matches_config(
    text: str,
    username: str,
    reskins: Sequence[str],
    gradients: Sequence[str],
    is_reskin: bool,
    is_shiny: bool,
    is_gradient: bool,
    is_any: bool,
    is_good: bool,
) -> bool:
    text_lower, username_lower = text.lower(), username.lower()
    if "attemp" not in text_lower or username_lower not in text_lower:
        return False
    comma_count = text.count(",")
    if comma_count >= 2:
        return True
    if comma_count == 1:
        before_comma = text.split(",", 1)[0].strip()
        word_before_comma = before_comma.split()[-1].lower() if before_comma else ""
        if word_before_comma == "shiny":
            return is_good
        return is_any
    has_reskin = any(reskin.lower() in text_lower for reskin in reskins)
    has_gradient = any(gradient.lower() in text_lower for gradient in gradients)
    has_shiny = "shiny" in text_lower
    if not any([is_any, is_reskin, is_shiny, is_gradient, is_good]):
        return False
    matches = []
    if is_reskin:
        matches.append(has_reskin)
    if is_shiny:
        matches.append(has_shiny)
    if is_gradient:
        matches.append(has_gradient)
    return any(matches)
