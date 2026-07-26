#!/usr/bin/env python3
"""Autonomous poster silhouette library generator."""
import os, sys, json, time, hashlib
from pathlib import Path

# Load .env BEFORE importing fal_client so credentials are in place
for line in open('/opt/evolum/.env').read().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v.strip('"').strip("'")
# fal_client looks for FAL_KEY, but our .env uses FAL_API_KEY — alias it
os.environ.setdefault('FAL_KEY', os.environ.get('FAL_API_KEY', ''))

import fal_client
import requests

sys.path.insert(0, '/opt/evolum/asset_generator')
from prompts import POSTER_PROMPTS

OUT_DIR = Path('/opt/evolum/static/asset_library/posters')
OUT_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST = Path('/opt/evolum/static/asset_library/posters_manifest.json')

# Model choice — schnell is ~$0.003/image, dev is ~$0.025/image
# Use schnell for volume + variants, dev for hero shots (skip dev for now given budget)
MODEL = 'fal-ai/flux/schnell'
VARIANTS_PER_PROMPT = 3  # 3 variants per prompt = 23 prompts × 3 = 69 images
IMAGE_SIZE = 'portrait_16_9'  # closest to poster aspect

# Load existing manifest to resume mid-run
if MANIFEST.exists():
    try:
        manifest = json.loads(MANIFEST.read_text())
    except Exception:
        manifest = {'posters': []}
else:
    manifest = {'posters': []}

existing_slugs = {p['slug'] for p in manifest.get('posters', [])}
print(f'>> resuming with {len(existing_slugs)} existing posters')

failures = 0
generated = 0

for prompt_i, entry in enumerate(POSTER_PROMPTS):
    for v in range(1, VARIANTS_PER_PROMPT + 1):
        slug = f"{entry['genre']}_{entry['tone']}_v{v}"
        if slug in existing_slugs:
            continue
        out_path = OUT_DIR / f'{slug}.jpg'
        # Prompt hash so we know when a prompt changes
        phash = hashlib.md5(entry['prompt'].encode()).hexdigest()[:8]
        seed = int(hashlib.md5((slug + phash).encode()).hexdigest()[:8], 16) % 2147483647
        try:
            print(f'\n>> [{prompt_i+1}/{len(POSTER_PROMPTS)}] {slug} (seed={seed})...')
            result = fal_client.subscribe(
                MODEL,
                arguments={
                    'prompt': entry['prompt'],
                    'image_size': IMAGE_SIZE,
                    'num_inference_steps': 4,  # schnell default
                    'seed': seed,
                    'enable_safety_checker': False,
                },
                with_logs=False,
            )
            img_url = result['images'][0]['url']
            img_bytes = requests.get(img_url, timeout=60).content
            out_path.write_bytes(img_bytes)
            manifest['posters'].append({
                'slug': slug,
                'genre': entry['genre'],
                'tone': entry['tone'],
                'prompt_hash': phash,
                'seed': seed,
                'path': f'/static/asset_library/posters/{slug}.jpg',
                'size_bytes': len(img_bytes),
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            })
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            generated += 1
            print(f'   ✓ saved {len(img_bytes)/1024:.0f} KB')
            time.sleep(0.4)  # be nice to the API
        except Exception as e:
            failures += 1
            print(f'   ✗ FAILED: {e}')
            if 'balance' in str(e).lower() or 'limit' in str(e).lower() or 'quota' in str(e).lower():
                print('!! FAL budget likely exhausted — stopping image run')
                break
            time.sleep(1.5)
    else:
        continue
    break

print(f'\n=== DONE ===')
print(f'generated: {generated}   failures: {failures}   total in manifest: {len(manifest["posters"])}')
