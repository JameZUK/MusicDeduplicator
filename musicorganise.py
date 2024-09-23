import os
import json
import shutil
import argparse
import subprocess
import acoustid
from fuzzywuzzy import fuzz
from mutagen import File
import time
import gc  # For garbage collection
from multiprocessing import Pool, cpu_count, Manager
import threading

# Configuration file for storing API key and fuzzy threshold
CONFIG_FILE = 'config.json'

# Load or initialize configuration
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Load AcoustID API key and Fuzzy Threshold from config
config = load_config()
ACOUSTID_API_KEY = config.get('acoustid_api_key', None)
FUZZY_THRESHOLD = config.get('fuzzy_threshold', 90)  # Default threshold is 90

# If no API key, prompt user and save it to the config file
if not ACOUSTID_API_KEY:
    ACOUSTID_API_KEY = input("Please enter your AcoustID API key: ").strip()
    config['acoustid_api_key'] = ACOUSTID_API_KEY
    save_config(config)

# If no fuzzy threshold exists, prompt user to set it
if 'fuzzy_threshold' not in config:
    try:
        FUZZY_THRESHOLD = int(input("Please enter the fuzzy match threshold (default is 90): ").strip() or 90)
    except ValueError:
        FUZZY_THRESHOLD = 90
    config['fuzzy_threshold'] = FUZZY_THRESHOLD
    save_config(config)

# Dictionary to store cached metadata and fingerprints
CACHE_FILE = 'file_cache.json'
file_cache = {}

# Summary statistics
summary_stats = Manager().dict({
    'total_files_processed': 0,
    'total_duplicates_found': 0,
    'total_files_to_remove': 0,
    'total_storage_to_save': 0,
    'files_by_format': Manager().dict(),
    'total_acoustid_lookups': 0
})

# Load cached data if it exists
def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Cache file is corrupt or unreadable, recreating it: {e}")
    return {}

file_cache = load_cache()

# Save cache to file for persistence
def save_cache():
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(file_cache, f)
    except Exception as e:
        print(f"Error saving cache: {e}")

def validate_cached_data(file_path):
    """Re-validates cached data only if the file has changed."""
    file_mtime = os.path.getmtime(file_path)
    cached_mtime = file_cache.get(file_path, {}).get('metadata', {}).get('mtime')
    if cached_mtime == file_mtime:
        # No changes, use cached data
        metadata = file_cache[file_path]['metadata']
        acoustid_rid = file_cache[file_path].get('acoustid')
    else:
        # File has changed, re-validate
        metadata = get_file_metadata(file_path, revalidate=True)
        acoustid_rid = get_acoustid(file_path, revalidate=True)
    return metadata, acoustid_rid

def get_file_metadata(file_path, revalidate=False):
    """Fetches or re-validates metadata of the music file using Mutagen and caches it for performance."""
    if not revalidate and file_path in file_cache and 'metadata' in file_cache[file_path]:
        return file_cache[file_path]['metadata']

    try:
        audio = File(file_path, easy=True)
        if audio is None:
            return None

        file_metadata = {}
        file_metadata['size'] = os.path.getsize(file_path)
        file_metadata['mtime'] = os.path.getmtime(file_path)

        # Normalize case by converting artist, title, and album to lowercase for case-insensitive comparison
        file_metadata['artist'] = audio.get('artist', ['Unknown Artist'])[0].lower()
        file_metadata['title'] = audio.get('title', ['Unknown Title'])[0].lower()
        file_metadata['album'] = audio.get('album', ['Unknown Album'])[0].lower()
        file_metadata['tracknumber'] = audio.get('tracknumber', [0])[0]

        file_extension = os.path.splitext(file_path)[1].lower()
        file_metadata['format'] = file_extension.strip('.')
        summary_stats['files_by_format'].setdefault(file_metadata['format'], 0)
        summary_stats['files_by_format'][file_metadata['format']] += 1

        # Update or add the cached metadata
        file_cache.setdefault(file_path, {})
        file_cache[file_path]['metadata'] = file_metadata
        return file_metadata
    except Exception as e:
        print(f"Failed to get metadata for {file_path}: {e}")
        return None

def get_acoustid(file_path, revalidate=False):
    """Fetches or re-validates the AcoustID fingerprint and caches it for performance."""
    if not revalidate and file_path in file_cache and 'acoustid' in file_cache[file_path]:
        return file_cache[file_path]['acoustid']

    try:
        # Use fpcalc via subprocess
        result = subprocess.run(['fpcalc', '-json', file_path], capture_output=True, text=True)
        if result.returncode != 0:
            # print(f"fpcalc failed for {file_path}: {result.stderr.strip()}")
            return None

        fingerprint_data = json.loads(result.stdout)
        duration = fingerprint_data['duration']
        fingerprint = fingerprint_data['fingerprint']

        response = acoustid_lookup(ACOUSTID_API_KEY, fingerprint, duration)
        if response['status'] != 'ok':
            error_message = response.get('error', {}).get('message', 'Unknown error')
            # print(f"AcoustID lookup failed for {file_path}: {error_message}")
            return None

        results = response.get('results', [])
        if not results:
            return None

        # Get the best match (highest score)
        best_result = max(results, key=lambda x: x.get('score', 0))

        # Extract recording information
        recordings = best_result.get('recordings', [])
        if not recordings:
            return None

        recording = recordings[0]  # Use the first recording
        rid = recording.get('id')

        # Cache the AcoustID result
        file_cache.setdefault(file_path, {})
        file_cache[file_path]['acoustid'] = rid
        return rid
    except Exception as e:
        # print(f"AcoustID lookup failed for {file_path}: {e}")
        return None

def acoustid_lookup(api_key, fingerprint, duration):
    """Performs AcoustID lookup synchronously."""
    return acoustid.lookup(api_key, fingerprint, duration, meta='recordings artists')

def fuzzy_match(metadata1, metadata2):
    """Performs fuzzy matching between two metadata sets (title, artist, album) and returns the similarity percentage."""
    title_match = fuzz.ratio(metadata1['title'], metadata2['title'])
    artist_match = fuzz.ratio(metadata1['artist'], metadata2['artist'])
    album_match = fuzz.ratio(metadata1['album'], metadata2['album'])

    # Average percentage match across title, artist, and album
    avg_match = (title_match + artist_match + album_match) / 3

    return avg_match

def find_duplicates(directory, verbose=False):
    """Recursively scans directory for music files and identifies duplicates based on metadata matching."""
    manager = Manager()
    files_by_metadata = manager.dict()
    duplicates = manager.list()
    start_time = time.time()
    file_paths = []

    # Collect all file paths
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if not file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
                continue
            file_paths.append(file_path)

    batch_size = 1000  # Adjust batch size as needed
    num_processes = cpu_count()

    with Pool(processes=num_processes) as pool:
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i+batch_size]
            results = pool.map(process_file_metadata, batch)
            for result in results:
                if result:
                    key, file_path = result
                    files_by_metadata.setdefault(key, []).append(file_path)
            summary_stats['total_files_processed'] += len(batch)

            # Verbose output
            if verbose:
                elapsed_time = time.time() - start_time
                files_per_sec = summary_stats['total_files_processed'] / elapsed_time
                print(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")

            save_cache()  # Save cache after each batch
            gc.collect()  # Force garbage collection

    # Identify potential duplicates based on metadata
    potential_duplicates = []
    for file_list in files_by_metadata.values():
        if len(file_list) > 1:
            potential_duplicates.append(file_list)

    # Perform AcoustID fingerprinting on potential duplicates
    if potential_duplicates:
        process_acoustid(potential_duplicates, duplicates, verbose, start_time)

    # Update summary statistics
    summary_stats['total_duplicates_found'] = len(duplicates)

    return duplicates

def process_file_metadata(file_path):
    """Processes a file to extract metadata for duplicate detection."""
    metadata = get_file_metadata(file_path)
    if not metadata:
        return None

    # Use metadata key
    metadata_key = (metadata['artist'], metadata['title'], metadata['album'])
    return metadata_key, file_path

def process_acoustid(potential_duplicates, duplicates, verbose, start_time):
    """Processes potential duplicates using AcoustID fingerprinting."""
    manager = Manager()
    acoustid_results = manager.dict()
    file_list = [file for sublist in potential_duplicates for file in sublist]
    num_processes = cpu_count()

    with Pool(processes=num_processes) as pool:
        results = pool.map(process_file_acoustid, file_list)
        for result in results:
            if result:
                rid, file_path = result
                acoustid_results.setdefault(rid, []).append(file_path)
            summary_stats['total_acoustid_lookups'] += 1

            # Verbose output
            if verbose and summary_stats['total_acoustid_lookups'] % 50 == 0:
                elapsed_time = time.time() - start_time
                print(f"Performed {summary_stats['total_acoustid_lookups']} AcoustID lookups in {elapsed_time:.2f} seconds")

    # Identify duplicates based on AcoustID
    for file_list in acoustid_results.values():
        if len(file_list) > 1:
            duplicates.append(file_list)

def process_file_acoustid(file_path):
    """Processes a file to obtain its AcoustID."""
    rid = get_acoustid(file_path)
    if rid:
        return rid, file_path
    return None

def resolve_duplicates(duplicates, action='list', move_dir=None, base_dir=None, verbose=False):
    """Resolves duplicates by either listing, moving, or deleting them."""
    for duplicate_set in duplicates:
        best_file = None
        best_metadata = None
        to_delete = []

        # Re-validate before taking action
        for file_path in duplicate_set:
            metadata, _ = validate_cached_data(file_path)
            if not metadata:
                continue

            if best_file is None or (metadata['format'] == 'flac' and (best_metadata is None or metadata['size'] > best_metadata['size'])):
                if best_file:
                    to_delete.append(best_file)
                best_file = file_path
                best_metadata = metadata
            else:
                to_delete.append(file_path)

        # Update summary statistics
        summary_stats['total_files_to_remove'] += len(to_delete)
        summary_stats['total_storage_to_save'] += sum(os.path.getsize(f) for f in to_delete if os.path.exists(f))

        if action == 'list':
            print(f"Best file: {best_file}")
            for file in to_delete:
                print(f"To delete: {file}")
        elif action == 'move' and move_dir:
            move_duplicates(to_delete, best_file, move_dir, base_dir)
        elif action == 'delete':
            delete_duplicates(to_delete)

def move_duplicates(to_delete, original_file, move_dir, base_dir):
    """Moves duplicate files to a new directory while keeping the folder structure intact."""
    for file_path in to_delete:
        # Create the relative path based on the base directory
        relative_path = os.path.relpath(file_path, start=base_dir)

        # Construct the full target path in the move directory
        target_path = os.path.join(move_dir, relative_path)
        target_dir_path = os.path.dirname(target_path)

        # Ensure the target directory exists
        if not os.path.exists(target_dir_path):
            os.makedirs(target_dir_path)

        # Move the file to the target directory
        shutil.move(file_path, target_path)

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path in to_delete:
        print(f"Deleting {file_path}")
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"Error deleting file {file_path}: {e}")

def display_summary():
    """Displays the summary statistics after processing."""
    print("\nSummary:")
    print(f"Total files processed: {summary_stats['total_files_processed']}")
    print(f"Total duplicates found: {summary_stats['total_duplicates_found']}")
    print(f"Total files to remove: {summary_stats['total_files_to_remove']}")
    print(f"Estimated storage saved: {summary_stats['total_storage_to_save'] / (1024 * 1024):.2f} MB")
    print("\nFiles processed by format:")
    for format, count in summary_stats['files_by_format'].items():
        print(f"  {format.upper()}: {count} files")

def main():
    parser = argparse.ArgumentParser(description="Music collection deduplication script.")

    parser.add_argument('-p', '--path', required=True, help="Path to the music directory to scan.")
    parser.add_argument('-a', '--action', required=True, choices=['list', 'move', 'delete'], help="Action to take: list, move, or delete duplicates.")
    parser.add_argument('-m', '--move-dir', help="Directory to move duplicates to (required if action is 'move').")
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output with processing speed.")

    args = parser.parse_args()

    # Ensure move_dir is provided if action is 'move'
    if args.action == 'move' and not args.move_dir:
        parser.error("--move-dir is required when action is 'move'")

    start_time = time.time()

    # Run the duplicate finding and processing logic
    duplicates = find_duplicates(args.path, verbose=args.verbose)

    if duplicates:
        print(f"Found {len(duplicates)} sets of duplicates.")
        resolve_duplicates(duplicates, args.action, args.move_dir, base_dir=args.path, verbose=args.verbose)
    else:
        print("No duplicates found.")

    # Save cache at the end
    save_cache()

    total_time = time.time() - start_time
    print(f"\nCompleted in {total_time:.2f} seconds.")

    display_summary()

if __name__ == "__main__":
    main()
