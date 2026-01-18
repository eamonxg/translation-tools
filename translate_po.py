#!/usr/bin/env python3
"""
Auto-translate empty msgstr entries in .po files using DeepLX
"""

import os
import re
import sys
import argparse
import time
import json
import httpx
from pathlib import Path

# Language code mapping for DeepL
# DeepL uses different language codes than our po files
DEEPL_LANGUAGE_MAP = {
    'zh_Hans': 'ZH',      # Simplified Chinese
    'de': 'DE',           # German
    'es': 'ES',           # Spanish
    'fr': 'FR',           # French
    'it': 'IT',           # Italian
    'ja': 'JA',           # Japanese
    'ko': 'KO',           # Korean
    'ru': 'RU',           # Russian
    'pl': 'PL',           # Polish
    'tr': 'TR',           # Turkish
    'uk': 'UK',           # Ukrainian
    'nl': 'NL',           # Dutch
    'id': 'ID',           # Indonesian
    'pt': 'PT',           # Portuguese
    'sv': 'SV',           # Swedish
    'da': 'DA',           # Danish
    'fi': 'FI',           # Finnish
    'no': 'NB',           # Norwegian
    'cs': 'CS',           # Czech
    'el': 'EL',           # Greek
    'hu': 'HU',           # Hungarian
    'ro': 'RO',           # Romanian
    'sk': 'SK',           # Slovak
    'bg': 'BG',           # Bulgarian
    'lt': 'LT',           # Lithuanian
    'lv': 'LV',           # Latvian
    'et': 'ET',           # Estonian
    'sl': 'SL',           # Slovenian
}

# Language names for display
LANGUAGE_NAMES = {
    'zh_Hans': 'Simplified Chinese',
    'de': 'German',
    'es': 'Spanish',
    'fr': 'French',
    'it': 'Italian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'ru': 'Russian',
    'pl': 'Polish',
    'tr': 'Turkish',
    'uk': 'Ukrainian',
    'nl': 'Dutch',
    'id': 'Indonesian',
}

def parse_po_file(file_path):
    """Parse a .po file and return list of entries"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    entries = []
    # Split by empty lines to get individual entries
    blocks = re.split(r'\n\n+', content)

    for block in blocks:
        if not block.strip():
            continue

        # Extract msgid and msgstr
        msgid_match = re.search(r'msgid\s+"([^"]*)"', block)
        msgstr_match = re.search(r'msgstr\s+"([^"]*)"', block)

        if msgid_match and msgstr_match:
            msgid = msgid_match.group(1)
            msgstr = msgstr_match.group(1)

            # Handle multi-line strings
            if '""' in block:
                # Multi-line msgid
                msgid_lines = re.findall(r'msgid\s+""\n((?:\s*"[^"]*"\n?)+)', block)
                if msgid_lines:
                    msgid = ''.join(re.findall(r'"([^"]*)"', msgid_lines[0]))

                # Multi-line msgstr
                msgstr_lines = re.findall(r'msgstr\s+""\n((?:\s*"[^"]*"\n?)+)', block)
                if msgstr_lines:
                    msgstr = ''.join(re.findall(r'"([^"]*)"', msgstr_lines[0]))

            entries.append({
                'msgid': msgid,
                'msgstr': msgstr,
                'block': block,
                'is_empty': msgstr == ''
            })

    return entries

def find_untranslated_entries(po_dir):
    """Find all untranslated entries in po directory"""
    po_dir = Path(po_dir)
    results = {}

    for lang_dir in po_dir.iterdir():
        if not lang_dir.is_dir():
            continue
        if lang_dir.name == 'templates':
            continue

        lang_code = lang_dir.name
        lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
        deepl_code = DEEPL_LANGUAGE_MAP.get(lang_code)

        if not deepl_code:
            print(f"Warning: Language {lang_code} not supported by DeepL, skipping...")
            continue

        for po_file in lang_dir.glob('*.po'):
            entries = parse_po_file(po_file)
            untranslated = [e for e in entries if e['is_empty'] and e['msgid']]

            if untranslated:
                results[str(po_file)] = {
                    'lang_code': lang_code,
                    'lang_name': lang_name,
                    'deepl_code': deepl_code,
                    'untranslated': untranslated,
                    'total': len(entries)
                }

    return results

def translate_text_deepl(text, target_lang, api_url, endpoint_type="free", max_retries=3):
    """Translate text using DeepL API with retry logic

    Args:
        text: Text to translate
        target_lang: Target language code (e.g., 'ZH', 'DE')
        api_url: API endpoint URL
        endpoint_type: Type of endpoint - 'free', 'pro', or 'official'
        max_retries: Maximum number of retry attempts
    """
    for attempt in range(max_retries):
        try:
            # Prepare request data based on endpoint type
            if endpoint_type == "official":
                # Official endpoint uses array format
                data = {
                    "text": [text],
                    "target_lang": target_lang
                }
            else:
                # Free and Pro endpoints use the same format
                data = {
                    "text": text,
                    "source_lang": "EN",
                    "target_lang": target_lang
                }

            post_data = json.dumps(data)
            response = httpx.post(url=api_url, data=post_data, timeout=30.0)

            if response.status_code == 200:
                result = response.json()

                # Handle different response formats
                if endpoint_type == "official":
                    # Official endpoint returns: {"translations": [{"text": "..."}]}
                    if 'translations' in result and len(result['translations']) > 0:
                        return result['translations'][0]['text']
                else:
                    # Free/Pro endpoints return: {"data": "..."} or {"translations": [...]}
                    if 'data' in result:
                        return result['data']
                    elif 'translations' in result and len(result['translations']) > 0:
                        return result['translations'][0]['text']

                print(f"       ⚠ Unexpected response format: {result}")
                return None

            elif response.status_code == 503:
                # Rate limit hit - use exponential backoff
                wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                print(f"       ⚠ Rate limit hit. Waiting {wait_time}s before retry... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"       ⚠ Error: {error_msg}. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"       ✗ Translation failed after {max_retries} attempts: {error_msg}")
                    return None

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                print(f"       ⚠ Error: {e}. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"       ✗ Translation failed after {max_retries} attempts: {e}")
                return None

    return None

def translate_entries(results, api_url, endpoint_type="free", delay=0.5, dry_run=False):
    """Translate all untranslated entries using DeepL"""
    total_translated = 0
    consecutive_failures = 0
    max_consecutive_failures = 5

    for po_file, data in sorted(results.items()):
        lang_name = data['lang_name']
        lang_code = data['lang_code']
        deepl_code = data['deepl_code']
        untranslated = data['untranslated']

        print(f"\nProcessing: {po_file}")
        print(f"Language: {lang_name} ({lang_code} -> DeepL: {deepl_code})")
        print(f"Endpoint: {endpoint_type}")
        print(f"Untranslated entries: {len(untranslated)}")

        if dry_run:
            print("  [DRY RUN] Skipping actual translation")
            continue

        # Read the original file
        with open(po_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Translate each entry
        for i, entry in enumerate(untranslated, 1):
            msgid = entry['msgid']
            if not msgid:
                continue

            # Check if we should stop due to too many consecutive failures
            if consecutive_failures >= max_consecutive_failures:
                print(f"\n⚠ Stopping translation: {consecutive_failures} consecutive failures detected.")
                print("This usually means:")
                print("  1. Your IP has been rate-limited by DeepL")
                print("  2. The DeepL service is temporarily unavailable")
                print("\nSuggestions:")
                print("  - Wait 30-60 minutes before trying again")
                print("  - Use a longer --delay (e.g., --delay 5.0)")
                print("  - Consider using a different DeepL endpoint or API key")
                print(f"\nProgress saved: {total_translated} entries translated so far")
                return total_translated

            print(f"  [{i}/{len(untranslated)}] Translating: {msgid[:60]}...")

            translation = translate_text_deepl(msgid, deepl_code, api_url, endpoint_type)

            if translation:
                # Replace empty msgstr with translation
                old_block = entry['block']
                new_block = old_block.replace('msgstr ""', f'msgstr "{translation}"')
                content = content.replace(old_block, new_block)
                total_translated += 1
                consecutive_failures = 0  # Reset failure counter on success
                print(f"       → {translation[:60]}...")
            else:
                consecutive_failures += 1
                print(f"       → Failed to translate (consecutive failures: {consecutive_failures})")

            # Add delay between requests to avoid rate limiting
            if i < len(untranslated):
                time.sleep(delay)

        # Write back to file
        if total_translated > 0:
            with open(po_file, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  ✓ Updated {po_file}")

    return total_translated

def print_report(results):
    """Print a report of untranslated entries"""
    print("=" * 80)
    print("Untranslated .po file entries report")
    print("=" * 80)
    print()

    total_untranslated = 0

    for po_file, data in sorted(results.items()):
        lang_name = data['lang_name']
        lang_code = data['lang_code']
        deepl_code = data['deepl_code']
        untranslated_count = len(data['untranslated'])
        total_count = data['total']

        total_untranslated += untranslated_count

        print(f"File: {po_file}")
        print(f"Language: {lang_name} ({lang_code} -> DeepL: {deepl_code})")
        print(f"Untranslated: {untranslated_count}/{total_count}")
        print()

        # Show first 5 untranslated entries as examples
        for i, entry in enumerate(data['untranslated'][:5]):
            print(f"  [{i+1}] msgid: {entry['msgid'][:60]}...")

        if len(data['untranslated']) > 5:
            print(f"  ... and {len(data['untranslated']) - 5} more")
        print()

    print("=" * 80)
    print(f"Total untranslated entries: {total_untranslated}")
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(
        description='Auto-translate empty msgstr entries in .po files using DeepL'
    )
    parser.add_argument(
        '--mode',
        choices=['report', 'translate'],
        default='report',
        help='Mode: report (show untranslated) or translate (auto-translate)'
    )
    parser.add_argument(
        '--api-url',
        default='http://localhost:1188/translate',
        help='DeepL API URL (default: http://localhost:1188/translate for DeepLX)'
    )
    parser.add_argument(
        '--endpoint',
        choices=['free', 'pro', 'official'],
        default='free',
        help='DeepL endpoint type: free (/translate), pro (/v1/translate), or official (/v2/translate)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between translation requests in seconds (default: 0.5)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be translated without actually doing it'
    )

    args = parser.parse_args()

    po_dir = Path(__file__).parent.parent / 'luci-app-aurora-config' / 'po'

    if not po_dir.exists():
        print(f"Error: Directory not found: {po_dir}")
        sys.exit(1)

    print(f"Scanning .po files in: {po_dir}")
    print()

    results = find_untranslated_entries(po_dir)

    if not results:
        print("No untranslated entries found!")
        return

    if args.mode == 'report':
        print_report(results)
    elif args.mode == 'translate':
        print_report(results)
        print()

        if not args.dry_run:
            confirm = input("Proceed with translation? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Translation cancelled")
                return

        total = translate_entries(results, args.api_url, args.endpoint, args.delay, args.dry_run)
        print()
        print("=" * 80)
        print(f"Translation complete! Translated {total} entries")
        print("=" * 80)

if __name__ == '__main__':
    main()


