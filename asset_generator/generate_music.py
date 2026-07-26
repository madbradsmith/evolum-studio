#!/usr/bin/env python3
"""Autonomous music bed library generator via FAL MusicGen."""
import os, sys, json, time, hashlib
from pathlib import Path

# Load .env BEFORE importing fal_client
for line in open('/opt/evolum/.env').read().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip('"').strip("'")
os.environ.setdefault('FAL_KEY', os.environ.get('FAL_API_KEY', ''))

import fal_client
import requests

sys.path.insert(0, '/opt/evolum/asset_generator')
from prompts import MUSIC_PROMPTS

OUT_DIR = Path('/opt/evolum/static/asset_library/music')
OUT_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST = Path('/opt/evolum/static/asset_library/music_manifest.json')

MODEL = 'fal-ai/stable-audio'  # ~$0.02/sec, use minimum duration
VARIANTS_PER_PROMPT = 4  # 8 moods × 2 variants = 16 tracks
DURATION_SECONDS = 30

if MANIFEST.exists():
    try:
        manifest = json.loads(MANIFEST.read_text())
    except Exception:
        manifest = {'tracks': []}
else:
    manifest = {'tracks': []}

existing_slugs = {t['slug'] for t in manifest.get('tracks', [])}
print(f'>> resuming with {len(existing_slugs)} existing tracks')

generated, failures = 0, 0
budget_exhausted = False

for prompt_i, entry in enumerate(MUSIC_PROMPTS):
    if budget_exhausted:
        break
    for v in range(1, VARIANTS_PER_PROMPT + 1):
        slug = f"{entry['mood']}_v{v}"
        if slug in existing_slugs:
            continue
        out_path = OUT_DIR / f'{slug}.mp3'
        phash = hashlib.md5(entry['prompt'].encode()).hexdigest()[:8]
        seed = int(hashlib.md5((slug + phash).encode()).hexdigest()[:8], 16) % 2147483647
        try:
            print(f'\n>> [{prompt_i+1}/{len(MUSIC_PROMPTS)}] {slug} (seed={seed})...')
            result = fal_client.subscribe(
                MODEL,
                arguments={
                    'prompt': entry['prompt'],
                    'seconds_total': DURATION_SECONDS,
                    'steps': 100,
                    'seed': seed,
                },
                with_logs=False,
            )
            audio_url = result['audio_file']['url']
            audio_bytes = requests.get(audio_url, timeout=90).content
            out_path.write_bytes(audio_bytes)
            manifest['tracks'].append({
                'slug': slug,
                'mood': entry['mood'],
                'prompt_hash': phash,
                'seed': seed,
                'duration': DURATION_SECONDS,
                'path': f'/static/asset_library/music/{slug}.mp3',
                'size_bytes': len(audio_bytes),
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            })
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            generated += 1
            print(f'   ✓ saved {len(audio_bytes)/1024:.0f} KB')
            time.sleep(0.5)
        except Exception as e:
            failures += 1
            err = str(e)
            print(f'   ✗ FAILED: {err}')
            if any(t in err.lower() for t in ['balance', 'limit', 'quota', 'insufficient']):
                print('!! FAL budget likely exhausted — stopping music run')
                budget_exhausted = True
                break
            time.sleep(1.5)

print(f'\n=== DONE ===')
print(f'generated: {generated}   failures: {failures}   total in manifest: {len(manifest["tracks"])}')
