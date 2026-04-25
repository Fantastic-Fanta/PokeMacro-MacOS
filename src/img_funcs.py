import re
from typing import Sequence

remove_chronos_event_phrase = lambda text: re.sub(
    r"\s+",
    " ",
    re.sub(r"\b[Cc]hronos\s+[Ee]vent\s+2025\s+is\s+out\b", "", text, flags=re.IGNORECASE),
).strip()


def trim_text_from_username_to_attempts(text: str, username: str) -> str:
    text_lower, username_lower = text.lower(), username.lower()
    if username_lower not in text_lower:
        return text
    username_index = text_lower.find(username_lower)
    if username_index == -1:
        return text
    search_text_lower = text_lower[username_index:]
    attempts_index = search_text_lower.find("attempts")
    if attempts_index == -1:
        return text[username_index:]
    return text[username_index : username_index + attempts_index + len("attempts")]


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
