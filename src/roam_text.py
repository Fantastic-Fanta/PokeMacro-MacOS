import pyautogui


def capture_full_screen_to_file(output_path: str) -> bool:
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(output_path)
        return True
    except Exception:
        return False


def capture_sprite_region_to_file(left: int, top: int, width: int, height: int, output_path: str) -> None:
    try:
        screenshot = pyautogui.screenshot(region=(left, top, width, height))
        screenshot.save(output_path)
    except Exception:
        pass


def is_text_in_wishlist(text: str, wishlist_items: list) -> bool:
    text_lower = text.lower()
    return any(item.lower() in text_lower for item in wishlist_items)


def find_closest_roaming(roaming_name: str, roaming_list: list) -> str:
    if not roaming_name or not roaming_list:
        return roaming_name.strip().lower() if roaming_name else ""
    clean = roaming_name.strip().lower()
    if not clean:
        return ""
    list_lower = [r.lower() for r in roaming_list]
    if clean in list_lower:
        return clean
    best = ""
    for item in list_lower:
        if item in clean and len(item) > len(best):
            best = item
    if best:
        return best
    for item in list_lower:
        if clean in item:
            return item
    return clean


def is_special_roaming(
    chat_text: str,
    roaming_name: str,
    special_variants: list,
    roaming_list: list = None,
) -> bool:
    if not chat_text or not roaming_name:
        return False
    if roaming_list:
        roaming_name = find_closest_roaming(roaming_name, roaming_list)
    chat_lower = chat_text.lower()
    roaming_lower = roaming_name.strip().lower() if isinstance(roaming_name, str) else ""
    if not roaming_lower:
        return False
    pos = chat_lower.rfind(roaming_lower)
    if pos == -1:
        return False
    left_text = chat_text[:pos].strip()
    words = left_text.split()
    words_before = words[-2:] if len(words) >= 2 else words
    words_before_lower = [w.lower() for w in words_before]
    for variant in special_variants:
        v_lower = variant.lower()
        for w in words_before_lower:
            if w == v_lower or (len(v_lower) > 1 and v_lower in w):
                return True
    return False
