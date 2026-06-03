"""
Translate Turkish product titles to Ukrainian and English using Claude API.
Writes results back to the SQLite DB.
"""

import sqlite3
import json
import time
import os
import sys

import anthropic

DB_PATH = "data/sahara.db"
API_KEY = os.environ.get("ANTHROPIC_API_KEY") or ""

# Load from .env if not set
if not API_KEY:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not found")
    sys.exit(1)

client = anthropic.Anthropic(api_key=API_KEY)


def translate_title(title: str) -> dict:
    prompt = (
        f'Translate this Turkish clothing product name to Ukrainian and English. '
        f'Return ONLY valid JSON: {{"uk": "...", "en": "..."}}\n'
        f'Keep translations SHORT and clean (max 60 chars each). Fashion store style.\n'
        f'Turkish: {title}'
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    # Extract JSON even if surrounded by extra text
    start = raw.find("{")
    end = raw.rfind("}") + 1
    return json.loads(raw[start:end])


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT id, title FROM products WHERE title_ua IS NULL OR title_en IS NULL")
    products = c.fetchall()
    print(f"Found {len(products)} products to translate.")

    ok = 0
    errors = 0
    for i, row in enumerate(products, 1):
        pid = row["id"]
        title = row["title"]
        print(f"[{i}/{len(products)}] id={pid}: {title[:60]}")
        try:
            result = translate_title(title)
            ua = result.get("uk", "")[:60]
            en = result.get("en", "")[:60]
            print(f"           ua: {ua}")
            print(f"           en: {en}")
            c.execute(
                "UPDATE products SET title_ua=?, title_en=? WHERE id=?",
                (ua, en, pid),
            )
            conn.commit()
            ok += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
        # Small delay to avoid rate limits
        if i < len(products):
            time.sleep(0.3)

    conn.close()
    print(f"\nDone. Translated: {ok}, Errors: {errors}")


if __name__ == "__main__":
    main()
