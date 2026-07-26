# Prompt taxonomy — GENRE keyed (matches brain world classifier).
# One prompt per genre, generator produces VARIANTS_PER_PROMPT variants via seed variation.

POSTER_PROMPTS = []  # unused now (posters already generated)

MUSIC_PROMPTS = [
    {'mood': 'action_espionage', 'prompt': 'Cinematic action thriller score, propulsive orchestral strings with driving percussion, high-stakes espionage soundtrack, tense and cinematic, no vocals, 30 seconds'},
    {'mood': 'contained_urban',  'prompt': 'Nocturnal urban thriller soundtrack, sparse synth pads with subtle rhythmic pulse and distant city ambience, paranoid and tense film noir underscore, no vocals, 30 seconds'},
    {'mood': 'legal_courtroom',  'prompt': 'Legal drama score, measured piano and string ensemble with gravitas and moral weight, prestige cinematic film soundtrack, no vocals, 30 seconds'},
    {'mood': 'fantasy_satire',   'prompt': 'Whimsical fantasy adventure score, playful orchestral with harpsichord and woodwind flourishes, storybook kingdom court mood, no vocals, 30 seconds'},
    {'mood': 'nightlife_comedy', 'prompt': 'Modern comedy soundtrack, upbeat electronic beat with playful melodic hooks and driving bass, chaotic party energy, no vocals, 30 seconds'},
    {'mood': 'sports_drama',     'prompt': 'Inspirational sports drama score, anthemic rising strings with powerful driving drums, triumphant championship mood, no vocals, 30 seconds'},
    {'mood': 'crime_drama',      'prompt': 'Neo-noir crime score, dark brooding strings with grimy synth bass and sparse guitar, dangerous underworld atmosphere, no vocals, 30 seconds'},
    {'mood': 'drama',            'prompt': 'Contemporary drama score, intimate piano melody with warm string ensemble and soft ambient pads, character-driven emotional underscore, no vocals, 30 seconds'},
]
