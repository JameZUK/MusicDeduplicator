import os
import sys
import json
import shutil
import argparse
import subprocess
import acoustid
from fuzzywuzzy import fuzz
from mutagen import File
import time
import gc  # For garbage collection
from multiprocessing import Pool, cpu_count, Manager, get_context
import threading
import logging

# Configuration file for storing API key, fuzzy threshold, and batch size
CONFIG_FILE = 'config.json'

# Load or initialize configuration
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

# Load configuration parameters
config = load_config()
ACOUSTID_API_KEY = config.get('acoustid_api_key', None)
FUZZY_THRESHOLD = config.get('fuzzy_threshold', 90)  # Default threshold is 90
BATCH_SIZE = config.get('batch_size', None)

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

# If no batch size is set, prompt user to set it
if BATCH_SIZE is None:
    try:
        BATCH_SIZE = int(input("Please enter the batch size for processing files (default is 1000): ").strip() or 1000)
    except ValueError:
        BATCH_SIZE = 1000
    config['batch_size'] = BATCH_SIZE
    save_config(config)

# Set up logging
def setup_logging(log_level):
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Create file handler which logs even debug messages
    fh = logging.FileHandler('music_deduplicate.log', encoding='utf-8')
    fh.setLevel(logging.DEBUG)

    # Create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(log_level)

    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    # Remove existing handlers to prevent duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

# Dictionary to store cached metadata and fingerprints
CACHE_FILE = 'file_cache.json'
file_cache = {}

# Summary statistics
summary_stats = {
    'total_files_processed': 0,
    'total_duplicates_found': 0,
    'total_files_to_remove': 0,
    'total_storage_to_save': 0,
    'files_by_format': {},
    'total_acoustid_lookups': 0
}

# Load cached data if it exists
def load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Cache file is corrupt or unreadable, recreating it: {e}")
    return {}

file_cache = load_cache()

# Save cache to file for persistence
def save_cache():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(file_cache, f)
    except Exception as e:
        logging.error(f"Error saving cache: {e}")

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
            logging.warning(f"Unsupported file format or corrupted file: {file_path}")
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
    except FileNotFoundError as e:
        logging.error(f"File not found: {file_path} - {e}")
        return None
    except Exception as e:
        logging.error(f"Failed to get metadata for {file_path}: {e}")
        return None

def get_acoustid(file_path, revalidate=False):
    """Fetches or re-validates the AcoustID fingerprint and caches it for performance."""
    if not revalidate and file_path in file_cache and 'acoustid' in file_cache[file_path]:
        return file_cache[file_path]['acoustid']

    try:
        # Use fpcalc via subprocess
        result = subprocess.run(['fpcalc', '-json', file_path], capture_output=True, text=True)
        if result.returncode != 0:
            logging.warning(f"fpcalc failed for {file_path}: {result.stderr.strip()}")
            return None

        fingerprint_data = json.loads(result.stdout)
        duration = fingerprint_data['duration']
        fingerprint = fingerprint_data['fingerprint']

        response = acoustid_lookup(ACOUSTID_API_KEY, fingerprint, duration)
        if response['status'] != 'ok':
            error_message = response.get('error', {}).get('message', 'Unknown error')
            logging.warning(f"AcoustID lookup failed for {file_path}: {error_message}")
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
    except FileNotFoundError as e:
        logging.error(f"File not found: {file_path} - {e}")
        return None
    except Exception as e:
        logging.error(f"AcoustID lookup failed for {file_path}: {e}")
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

def find_duplicates(directory, verbose=False, use_multiprocessing=True):
    """Recursively scans directory for music files and identifies duplicates based on metadata matching."""
    files_by_metadata = {}
    duplicates = []
    start_time = time.time()
    file_paths = []

    # Collect all file paths
    for root, _, files in os.walk(directory):
        for file in files:
            # Convert to absolute path and ensure it's properly normalized
            file_path = os.path.abspath(os.path.join(root, file))
            if not file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
                continue
            if os.path.islink(file_path) and not os.path.exists(file_path):
                logging.warning(f"Skipping broken symbolic link: {file_path}")
                continue
            if not os.path.isfile(file_path):
                logging.warning(f"File does not exist or is not a regular file: {file_path}")
                continue
            file_paths.append(file_path)

    if use_multiprocessing:
        num_processes = cpu_count()
        ctx = get_context('spawn')  # Use 'spawn' to start fresh processes
        with ctx.Pool(processes=num_processes) as pool:
            for i in range(0, len(file_paths), BATCH_SIZE):
                batch = file_paths[i:i+BATCH_SIZE]
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
                    logging.info(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")

                save_cache()  # Save cache after each batch
                gc.collect()  # Force garbage collection
    else:
        # Single-threaded processing for debugging
        for i in range(0, len(file_paths), BATCH_SIZE):
            batch = file_paths[i:i+BATCH_SIZE]
            results = map(process_file_metadata, batch)
            for result in results:
                if result:
                    key, file_path = result
                    files_by_metadata.setdefault(key, []).append(file_path)
            summary_stats['total_files_processed'] += len(batch)

            # Verbose output
            if verbose:
                elapsed_time = time.time() - start_time
                files_per_sec = summary_stats['total_files_processed'] / elapsed_time
                logging.info(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")

            save_cache()  # Save cache after each batch
            gc.collect()  # Force garbage collection

    # Identify potential duplicates based on metadata
    potential_duplicates = []
    for file_list in files_by_metadata.values():
        if len(file_list) > 1:
            potential_duplicates.append(file_list)

    # Perform AcoustID fingerprinting on potential duplicates
    if potential_duplicates:
        process_acoustid(potential_duplicates, duplicates, verbose, start_time, use_multiprocessing)

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

def process_acoustid(potential_duplicates, duplicates, verbose, start_time, use_multiprocessing):
    """Processes potential duplicates using AcoustID fingerprinting."""
    acoustid_results = {}
    file_list = [file for sublist in potential_duplicates for file in sublist]

    if use_multiprocessing:
        num_processes = cpu_count()
        ctx = get_context('spawn')  # Use 'spawn' to start fresh processes
        with ctx.Pool(processes=num_processes) as pool:
            results = pool.map(process_file_acoustid, file_list)
    else:
        # Single-threaded processing for debugging
        results = map(process_file_acoustid, file_list)

    for result in results:
        if result:
            rid, file_path = result
            acoustid_results.setdefault(rid, []).append(file_path)
        summary_stats['total_acoustid_lookups'] += 1

        # Verbose output
        if verbose and summary_stats['total_acoustid_lookups'] % 50 == 0:
            elapsed_time = time.time() - start_time
            logging.info(f"Performed {summary_stats['total_acoustid_lookups']} AcoustID lookups in {elapsed_time:.2f} seconds")

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
            logging.info(f"Best file: {best_file}")
            for file in to_delete:
                logging.info(f"To delete: {file}")
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
        logging.info(f"Moved {file_path} to {target_path}")

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path in to_delete:
        logging.info(f"Deleting {file_path}")
        try:
            os.remove(file_path)
        except OSError as e:
            logging.error(f"Error deleting file {file_path}: {e}")

def display_summary():
    """Displays the summary statistics after processing."""
    logging.info("\nSummary:")
    logging.info(f"Total files processed: {summary_stats['total_files_processed']}")
    logging.info(f"Total duplicates found: {summary_stats['total_duplicates_found']}")
    logging.info(f"Total files to remove: {summary_stats['total_files_to_remove']}")
    logging.info(f"Estimated storage saved: {summary_stats['total_storage_to_save'] / (1024 * 1024):.2f} MB")
    logging.info("\nFiles processed by format:")
    for format, count in summary_stats['files_by_format'].items():
        logging.info(f"  {format.upper()}: {count} files")

def main():
    parser = argparse.ArgumentParser(description="Music collection deduplication script.")

    parser.add_argument('-p', '--path', required=True, help="Path to the music directory to scan.")
    parser.add_argument('-a', '--action', required=True, choices=['list', 'move', 'delete'], help="Action to take: list, move, or delete duplicates.")
    parser.add_argument('-m', '--move-dir', help="Directory to move duplicates to (required if action is 'move').")
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output with processing speed.")
    parser.add_argument('--log-level', default='INFO', help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).")
    parser.add_argument('--no-multiprocessing', action='store_true', help="Disable multiprocessing for debugging purposes.")

    args = parser.parse_args()

    # Set up logging
    log_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(log_level, int):
        print(f"Invalid log level: {args.log_level}")
        return

    setup_logging(log_level)

    # Ensure move_dir is provided if action is 'move'
    if args.action == 'move' and not args.move_dir:
        parser.error("--move-dir is required when action is 'move'")

    start_time = time.time()

    logging.info("Starting music deduplication process...")
    logging.info(f"Scanning directory: {args.path}")

    # Run the duplicate finding and processing logic
    duplicates = find_duplicates(args.path, verbose=args.verbose, use_multiprocessing=not args.no_multiprocessing)

    if duplicates:
        logging.info(f"Found {len(duplicates)} sets of duplicates.")
        resolve_duplicates(duplicates, args.action, args.move_dir, base_dir=os.path.abspath(args.path), verbose=args.verbose)
    else:
        logging.info("No duplicates found.")

    # Save cache at the end
    save_cache()

    total_time = time.time() - start_time
    logging.info(f"\nCompleted in {total_time:.2f} seconds.")

    display_summary()

if __name__ == "__main__":
    main()
