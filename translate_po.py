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

def translate_text_deepl(text, target_lang, api_url, endpoint_type="free", max_retries=3, request_delay=1.0):
    """Translate text using DeepL API with retry logic

    Args:
        text: Text to translate (string or list of strings for batch)
        target_lang: Target language code (e.g., 'ZH', 'DE')
        api_url: API endpoint URL
        endpoint_type: Type of endpoint - 'free', 'pro', or 'official'
        max_retries: Maximum number of retry attempts
        request_delay: Delay between individual requests in free endpoint batch mode

    Returns:
        Translated text (string) or list of translated texts for batch
    """
    # Check if batch translation
    is_batch = isinstance(text, list)

    # Free endpoint doesn't support batch - translate one by one
    if is_batch and endpoint_type == "free":
        print(f"       [INFO] Free endpoint doesn't support batch, translating {len(text)} texts individually...")
        print(f"       [INFO] Using {request_delay}s delay between requests")
        results = []
        for i, single_text in enumerate(text, 1):
            if i > 1:
                time.sleep(request_delay)  # Use configurable delay to avoid rate limiting
            result = translate_text_deepl(single_text, target_lang, api_url, endpoint_type, max_retries, request_delay)
            if result is None:
                return None
            results.append(result)
            if i % 10 == 0:
                print(f"       [INFO] Progress: {i}/{len(text)} texts translated")
        return results

    for attempt in range(max_retries):
        try:
            # Prepare request data based on endpoint type
            if endpoint_type == "official":
                # Official endpoint supports array format for batch
                data = {
                    "text": text if is_batch else [text],
                    "target_lang": target_lang
                }
            else:
                # Free and Pro endpoints
                if is_batch:
                    # Batch mode - use array format (for pro endpoint)
                    data = {
                        "text": text,
                        "source_lang": "EN",
                        "target_lang": target_lang
                    }
                else:
                    # Single text - use string format (as per official docs)
                    data = {
                        "text": text,  # text is already a string here
                        "source_lang": "EN",
                        "target_lang": target_lang
                    }

            response = httpx.post(url=api_url, json=data, timeout=30.0)

            if response.status_code == 200:
                result = response.json()

                # Handle different response formats
                # All endpoints should return: {"translations": [{"text": "..."}]}
                if 'translations' in result and len(result['translations']) > 0:
                    if is_batch:
                        return [t['text'] for t in result['translations']]
                    else:
                        return result['translations'][0]['text']
                # Fallback for older DeepLX versions that return {"data": "..."}
                elif 'data' in result:
                    # This format doesn't support batch translation properly
                    if is_batch:
                        print(f"       ⚠ Warning: API returned single 'data' field for batch request")
                        return None
                    else:
                        return result['data']

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

def translate_entries(results, api_url, endpoint_type="free", batch_size=10, delay=0.5, dry_run=False):
    """Translate all untranslated entries using DeepL with batch support

    Args:
        results: Dictionary of po files and their untranslated entries
        api_url: DeepL API endpoint URL
        endpoint_type: Type of endpoint ('free', 'pro', 'official')
        batch_size: Number of entries to translate in one request
        delay: Delay between batch requests in seconds
        dry_run: If True, don't actually translate
    """
    total_translated = 0
    consecutive_failures = 0
    max_consecutive_failures = 3

    for po_file, data in sorted(results.items()):
        lang_name = data['lang_name']
        lang_code = data['lang_code']
        deepl_code = data['deepl_code']
        untranslated = data['untranslated']

        print(f"\nProcessing: {po_file}")
        print(f"Language: {lang_name} ({lang_code} -> DeepL: {deepl_code})")
        print(f"Endpoint: {endpoint_type}")
        print(f"Batch size: {batch_size}")
        print(f"Untranslated entries: {len(untranslated)}")

        if dry_run:
            print("  [DRY RUN] Skipping actual translation")
            continue

        # Read the original file
        with open(po_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Process in batches
        total_batches = (len(untranslated) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
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

            # Get batch of entries
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(untranslated))
            batch_entries = untranslated[start_idx:end_idx]

            # Extract msgids for batch translation
            batch_msgids = [entry['msgid'] for entry in batch_entries if entry['msgid']]

            if not batch_msgids:
                continue

            print(f"  Batch [{batch_idx + 1}/{total_batches}] Translating {len(batch_msgids)} entries...")

            # Translate batch
            translations = translate_text_deepl(batch_msgids, deepl_code, api_url, endpoint_type, request_delay=delay)

            if translations and len(translations) == len(batch_msgids):
                # Apply translations to entries
                for idx, entry in enumerate(batch_entries):
                    if entry['msgid'] and idx < len(translations):
                        translation = translations[idx]
                        old_block = entry['block']
                        new_block = old_block.replace('msgstr ""', f'msgstr "{translation}"')
                        content = content.replace(old_block, new_block)
                        total_translated += 1

                consecutive_failures = 0  # Reset failure counter on success
                print(f"       ✓ Successfully translated {len(translations)} entries")
            else:
                consecutive_failures += 1
                print(f"       ✗ Failed to translate batch (consecutive failures: {consecutive_failures})")

            # Add delay between batch requests
            if batch_idx < total_batches - 1:
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
        default='http://localhost:1188/v2/translate',
        help='DeepL API URL (default: http://localhost:1188/v2/translate for DeepLX official endpoint)'
    )
    parser.add_argument(
        '--endpoint',
        choices=['free', 'pro', 'official'],
        default='official',
        help='DeepL endpoint type: free (/translate), pro (/v1/translate), or official (/v2/translate)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Number of entries to translate in one batch request (default: 10)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between batch requests in seconds (default: 0.5, increase if rate limited)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be translated without actually doing it'
    )
    parser.add_argument(
        '--yes',
        '-y',
        action='store_true',
        help='Skip confirmation prompt and proceed with translation'
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

        if not args.dry_run and not args.yes:
            confirm = input("Proceed with translation? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Translation cancelled")
                return

        total = translate_entries(results, args.api_url, args.endpoint, args.batch_size, args.delay, args.dry_run)
        print()
        print("=" * 80)
        print(f"Translation complete! Translated {total} entries")
        print("=" * 80)

if __name__ == '__main__':
    main()


