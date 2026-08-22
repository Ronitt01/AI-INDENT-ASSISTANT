"""Placeholder Hindi/Hinglish driver phrases for Phase 0 validation.

REPLACE THESE before trusting any accuracy/latency number that comes out of
local_prototype.py. These are generic logistics-domain guesses, not real
driver transcripts. See docs/OPEN_QUESTIONS.md.
"""

SYSTEM_PROMPT = """\
Aap AB Logistics ke liye ek voice assistant hain jo drivers se indent (load booking) \
lete hain. Chhote, seedhe jawab dein — jaise ek dispatcher call par bolta hai, \
lambi speeches nahi. Hindi aur Hinglish dono mein baat kar sakte hain, jaisa driver bole.
"""

# (driver utterance, what it's testing)
TEST_PHRASES: list[tuple[str, str]] = [
    ("Bhaiya load ready hai kya, pickup kab ka hai?", "basic status query, code-mixing"),
    ("Mera vehicle number MH12 AB 1234 hai, indent confirm karna hai", "vehicle number + shorthand 'indent'"),
    ("Pincode 411001 pe delivery hai, kitna time lagega", "pincode + ETA ask"),
    ("Load 18 tonne ka hai, container milega ya open truck", "logistics domain terms"),
    ("Maine already POD bhej diya hai WhatsApp pe", "logistics shorthand: POD"),
    ("Route change ho gaya hai, ab Nashik se Pune jaana hai", "mid-conversation update"),
    ("Advance payment kab tak milega loading ke baad", "payments query"),
    ("Traffic hai bahut, ETA 2 ghante late hoga", "delay reporting"),
    ("GR number kya hoga is trip ka", "logistics shorthand: GR (goods receipt)"),
    ("Halt charges lagenge kya agar factory pe wait karna pada", "domain-specific billing term"),
]

# Canned agent-side replies used only for the TTS voice A/B (--voice-ab), so the
# character mix (Devanagari + numerals) resembles what the agent will actually say.
AB_TEST_REPLIES: list[str] = [
    "Aapka indent confirm ho gaya hai. Pickup kal subah 9 baje hoga.",
    "Dhanyavaad, vehicle number note kar liya hai. Aage ki jaankari SMS se milegi.",
    "Delivery mein lagbhag do ghante lagenge, traffic ke hisaab se.",
    "POD receive ho gaya hai. Payment 48 ghanton mein process hoga.",
]

# Candidate Bulbul v3 speakers to A/B — replace with whichever names dashboard.sarvam.ai
# lists as available on your plan; these are placeholders pending Phase 0.
CANDIDATE_SPEAKERS: list[str] = ["shubh", "anushka", "manisha"]
