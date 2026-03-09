import re

# Auto triggers
ERIKA_RE = re.compile(r"(erika|Erika)")
SHALOM_RE = re.compile(r"shalom", re.IGNORECASE)
QUOI_RE = re.compile(r"\bquoi\.?$", re.IGNORECASE)
PEUR_RE = re.compile(r"\bpeur\.?$", re.IGNORECASE)
WOMEN_RE = re.compile(r"women(?:\.|@daddy_v2_bot)?", re.IGNORECASE)

# Social detection
TWITTER_RE = re.compile(r"https://(?:twitter|x)\.com/\S+", re.IGNORECASE)
TWITTER_CALLBACK_RE = re.compile(r"Twitter - [0-9]")

TIKTOK_RE = re.compile(r"https://(?:\w+\.)?tiktok\.com/\S+", re.IGNORECASE)
TIKTOK_CALLBACK_RE = re.compile(r"Tiktok - [0-9]")

INSTAGRAM_RE = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/[\w.-]+/?", re.IGNORECASE)
INSTAGRAM_CALLBACK_RE = re.compile(r"Instagram - [0-9]")

# Mentioned commands with optional @bot
UNLOCK_RE = re.compile(r"^(/unlock(@daddy_v2_bot)?)$", re.IGNORECASE)
S2T_RE = re.compile(r"^(/s2t(@daddy_v2_bot)?)$", re.IGNORECASE)
I2T_RE = re.compile(r"^(/i2t(@daddy_v2_bot)?)$", re.IGNORECASE)
RESUME_RE = re.compile(r"(/resume(@daddy_v2_bot)?)", re.IGNORECASE)
T2I_RE = re.compile(r"(/t2i(@daddy_v2_bot)?)", re.IGNORECASE)
T2S_RE = re.compile(r"(/t2s(@daddy_v2_bot)?)", re.IGNORECASE)
