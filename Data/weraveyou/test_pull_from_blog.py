import re

RELEASE_KEYWORDS = [
    "releases", "release", "drops", "unveils", "delivers",
    "shares", "returns with", "teams up", "collide on",
    "new single", "new track", "new album", "new ep",
    "remix", "listen"
]

EXCLUDE_KEYWORDS = [
    "turns", "anniversary", "announces", "set to release",
    "interview", "festival", "event", "tour", "art exhibition",
    "watch", "ranking", "playlist", "live stream", "classic"
]

def is_release_article(title: str) -> bool:
    t = title.lower()

    has_release_signal = any(k in t for k in RELEASE_KEYWORDS)
    has_exclusion = any(k in t for k in EXCLUDE_KEYWORDS)

    # ": Listen" is a strong signal on We Rave You
    if ": listen" in t and not has_exclusion:
        return True

    return has_release_signal and not has_exclusion

patterns = [
    r"^(?P<artist>.+?) (?:releases|drops|unveils|delivers|shares|returns with|teams up.*?for|join forces.*?for) .*?[‘'\"](?P<title>.+?)[’'\"]",
    r"^(?P<artist>.+?) – (?P<title>.+?)(?: \[.*?\])?$",
]

def extract_track(title):
    for p in patterns:
        m = re.search(p, title, re.I)
        if m:
            return {
                "artist": m.group("artist").strip(),
                "track": m.group("title").strip()
            }
    return None