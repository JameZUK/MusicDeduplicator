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
from tqdm import tqdm
from ratelimit import limits, sleep_and_retry

# Configuration file for storing API key, fuzzy threshold, and batch size
CONFIG_FILE = 'config.json'
CACHE_FILE = 'file_cache.json'

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
BATCH_SIZE = config.get('batch_size', 1000)
SUPPORTED_EXTENSIONS = config.get('supported_extensions', ['.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac'])

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

# Prompt for supported extensions if not set
if 'supported_extensions' not in config:
    ext_input = input("Please enter the supported file extensions (comma-separated, default is .mp3,.flac,.ogg,.wav,.m4a,.aac): ").strip()
    SUPPORTED_EXTENSIONS = [ext.strip().lower() for ext in (ext_input or '.mp3,.flac,.ogg,.wav,.m4a,.aac').split(',')]
    config['supported_extensions'] = SUPPORTED_EXTENSIONS
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

def check_fpcalc():
    """Checks if fpcalc is available."""
    try:
        subprocess.run(['fpcalc', '-version'], check=True, capture_output=True, text=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

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

# Initialize file_cache using Manager.dict() for multiprocessing
manager = Manager()
file_cache = manager.dict(load_cache())  # Use a managed dictionary
cache_lock = manager.Lock()  # Create a lock

# Save cache to file for persistence
def save_cache(cache_lock=None):
    if cache_lock is None:
        cache_lock = threading.Lock() #dummy
    temp_cache_file = CACHE_FILE + ".tmp"
    try:
        with cache_lock:
          with open(temp_cache_file, 'w', encoding='utf-8') as f:
              json.dump(dict(file_cache), f)
        shutil.move(temp_cache_file, CACHE_FILE)
    except Exception as e:
        logging.error(f"Error saving cache: {e}")

def validate_cached_data(file_path, cache_lock):
    """Re-validates cached data only if the file has changed."""
    with cache_lock:
        file_mtime = os.path.getmtime(file_path)
        cached_mtime = file_cache.get(file_path, {}).get('metadata', {}).get('mtime')

    if cached_mtime == file_mtime:
        # No changes, use cached data
        with cache_lock:
            metadata = file_cache[file_path]['metadata']
            acoustid_rid = file_cache[file_path].get('acoustid')
    else:
        # File has changed, re-validate
        metadata = get_file_metadata(file_path, revalidate=True, cache_lock=cache_lock)
        acoustid_rid = get_acoustid(file_path, revalidate=True, cache_lock=cache_lock)
    return metadata, acoustid_rid

def get_file_metadata(file_path, revalidate=False, cache_lock=None):
    """Fetches or re-validates metadata, using and managing the cache lock."""
    if cache_lock is None:
        cache_lock = threading.Lock() #dummy lock
    with cache_lock:
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
        file_metadata['artist'] = audio.get('artist', ['Unknown Artist'])[0].lower()
        file_metadata['title'] = audio.get('title', ['Unknown Title'])[0].lower()
        file_metadata['album'] = audio.get('album', ['Unknown Album'])[0].lower()
        file_metadata['tracknumber'] = audio.get('tracknumber', [0])[0]

        file_extension = os.path.splitext(file_path)[1].lower()
        file_metadata['format'] = file_extension.strip('.')
        with cache_lock:
            summary_stats['files_by_format'].setdefault(file_metadata['format'], 0)
            summary_stats['files_by_format'][file_metadata['format']] += 1

        with cache_lock:
            file_cache.setdefault(file_path, {})
            file_cache[file_path]['metadata'] = file_metadata
        return file_metadata
    except FileNotFoundError as e:
        logging.error(f"File not found: {file_path} - {e}")
        return None
    except Exception as e:
        logging.error(f"Failed to get metadata for {file_path}: {e}")
        return None

@sleep_and_retry
@limits(calls=3, period=1)
def acoustid_lookup(api_key, fingerprint, duration):
    """Performs AcoustID lookup with rate limiting."""
    return acoustid.lookup(api_key, fingerprint, duration, meta='recordings artists')

def get_acoustid(file_path, revalidate=False, cache_lock=None):
    """Fetches/re-validates AcoustID, managing the cache lock."""
    if cache_lock is None:
        cache_lock = threading.Lock() #dummy
    with cache_lock:
        if not revalidate and file_path in file_cache and 'acoustid' in file_cache[file_path]:
            return file_cache[file_path]['acoustid']

    try:
        result = subprocess.run(['fpcalc', '-json', file_path], capture_output=True, text=True, check=True)
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

        # Select the best result based on score and presence of recordings
        best_result = max(results, key=lambda x: (x.get('score', 0), len(x.get('recordings', []))), default=None)
        if not best_result:
            return None

        recordings = best_result.get('recordings', [])
        if not recordings:
            return None

        # Find the recording that best matches the file's metadata
        best_recording = None
        best_score = -1

        metadata = get_file_metadata(file_path, revalidate=revalidate, cache_lock=cache_lock)  # Ensure you have metadata
        if metadata:
            for rec in recordings:
                title_match = fuzz.ratio(metadata.get('title', ''), rec.get('title', '').lower())
                artist_match = fuzz.ratio(metadata.get('artist', ''), rec.get('artists', [{}])[0].get('name', '').lower())  # Consider first artist
                score = (title_match + artist_match) / 2  # Simple average

                if score > best_score:
                    best_score = score
                    best_recording = rec

        rid = best_recording.get('id') if best_recording else None
        if rid is None: return None


        with cache_lock:
            file_cache.setdefault(file_path, {})
            file_cache[file_path]['acoustid'] = rid
        return rid
    except FileNotFoundError as e:
        logging.error(f"File not found: {file_path} - {e}")
        return None
    except subprocess.CalledProcessError as e:
        logging.error(f"fpcalc failed for {file_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"AcoustID lookup failed for {file_path}: {e}")
        return None

def fuzzy_match(metadata1, metadata2):
    """Performs fuzzy matching between two metadata sets."""
    title_match = fuzz.ratio(metadata1['title'], metadata2['title'])
    artist_match = fuzz.ratio(metadata1['artist'], metadata2['artist'])
    album_match = fuzz.ratio(metadata1['album'], metadata2['album'])
    avg_match = (title_match + artist_match + album_match) / 3
    return avg_match

def find_duplicates(directory, verbose=False, use_multiprocessing=True):
    """Scans directory for music files and identifies duplicates (directory-based)."""
    files_by_metadata = {}
    duplicates = []
    start_time = time.time()
    potential_duplicate_dirs = set()

    # Collect all directories containing supported music files
    for root, _, files in os.walk(directory):
        has_music_files = False
        for file in files:
            if file.lower().endswith(tuple(SUPPORTED_EXTENSIONS)):
                has_music_files = True
                break
        if has_music_files:
            potential_duplicate_dirs.add(os.path.abspath(root))

    if use_multiprocessing:
        num_processes = cpu_count()
        ctx = get_context('spawn')
        with ctx.Pool(processes=num_processes) as pool:
            for dir_path in potential_duplicate_dirs:
                for file_name in os.listdir(dir_path):
                    file_path = os.path.join(dir_path, file_name)
                    if not file_name.lower().endswith(tuple(SUPPORTED_EXTENSIONS)):
                        continue
                    if os.path.islink(file_path) and not os.path.exists(file_path):
                        logging.warning(f"Skipping broken symbolic link: {file_path}")
                        continue
                    if not os.path.isfile(file_path):
                        logging.warning(f"Skipping non-file: {file_path}")
                        continue

                    result = pool.apply_async(process_file_metadata, args=(file_path, cache_lock)) #async
                    #get result.get()
                    try:
                      result_value = result.get() #get the result.  Will raise exception if the process failed
                      if result_value:
                          key, file_path_res = result_value
                          files_by_metadata.setdefault(key, []).append(file_path_res)
                          summary_stats['total_files_processed'] += 1
                    except Exception as e:
                      logging.error(f"Error processing file {file_path}: {e}") #log and continue



            # Verbose output during processing
            if verbose:
                elapsed_time = time.time() - start_time
                if summary_stats['total_files_processed'] > 0: #avoid div/0
                  files_per_sec = summary_stats['total_files_processed'] / elapsed_time
                  logging.info(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")

            save_cache(cache_lock)  # Save cache periodically
            gc.collect()

    else:  # Single-threaded processing
        for dir_path in potential_duplicate_dirs:
            for file_name in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file_name)
                if not file_name.lower().endswith(tuple(SUPPORTED_EXTENSIONS)):
                    continue

                if os.path.islink(file_path) and not os.path.exists(file_path):
                    logging.warning(f"Skipping broken symbolic link: {file_path}")
                    continue
                if not os.path.isfile(file_path):
                     logging.warning(f"Skipping non-file: {file_path}")
                     continue

                result = process_file_metadata(file_path, cache_lock)
                if result:
                    key, file_path_res = result
                    files_by_metadata.setdefault(key, []).append(file_path_res)
                    summary_stats['total_files_processed'] += 1

            # Verbose output during processing
            if verbose:
                elapsed_time = time.time() - start_time
                if summary_stats['total_files_processed'] > 0:
                  files_per_sec = summary_stats['total_files_processed'] / elapsed_time
                  logging.info(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")
            save_cache(cache_lock)
            gc.collect()


    # Identify potential duplicates based on metadata (whole directories)
    for file_list in files_by_metadata.values():
        if len(file_list) > 1:
            # Add the entire directory to potential duplicates if any files within it are potential duplicates
            potential_duplicate_dirs.add(os.path.dirname(file_list[0]))

    # Perform AcoustID fingerprinting on potential duplicates (considering whole directories)
    dir_acoustid_results = {}  # Store AcoustID results per directory
    if potential_duplicate_dirs:
        for dir_path in potential_duplicate_dirs:
            file_list = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS)) and os.path.isfile(os.path.join(dir_path,f))]
            if use_multiprocessing:
                num_processes = cpu_count()
                ctx = get_context('spawn')
                with ctx.Pool(processes=num_processes) as pool:
                    if verbose:
                        progress_bar = tqdm(total=len(file_list), desc=f"AcoustID Lookups ({os.path.basename(dir_path)})", unit="file")

                    # Use imap_unordered for asynchronous processing and immediate result handling
                    for result in pool.imap_unordered(process_file_acoustid, [(f, cache_lock) for f in file_list]):
                        if result:
                            rid, file_path = result
                            dir_acoustid_results.setdefault(dir_path, {}).setdefault(rid, []).append(file_path)
                            summary_stats['total_acoustid_lookups'] += 1
                        if verbose:
                            progress_bar.update(1)  # Update progress for each processed file

                    if verbose:
                        progress_bar.close()

            else: #single threaded
                if verbose:
                    progress_bar = tqdm(total=len(file_list), desc=f"AcoustID Lookups ({os.path.basename(dir_path)})", unit="file")

                for file_path in file_list:
                    result = process_file_acoustid((file_path, cache_lock)) #pass the lock
                    if result:
                        rid, file_path_res = result
                        dir_acoustid_results.setdefault(dir_path, {}).setdefault(rid, []).append(file_path_res)
                        summary_stats['total_acoustid_lookups'] += 1

                    if verbose:
                        progress_bar.update(1)
                if verbose:
                    progress_bar.close()


    # Identify duplicate directories based on AcoustID results
    for dir_path, acoustid_results in dir_acoustid_results.items():
        for rid, file_list in acoustid_results.items():
            if len(file_list) > 1:
              duplicates.append(file_list)

    summary_stats['total_duplicates_found'] = len(duplicates)
    return duplicates
def process_file_metadata(file_path, cache_lock):
    """Processes a file, gets metadata, and returns key and file path."""
    metadata = get_file_metadata(file_path, cache_lock=cache_lock)
    if not metadata:
        return None
    metadata_key = (metadata['artist'], metadata['title'], metadata['album'])
    return metadata_key, file_path


def process_file_acoustid(args):
    """Processes a file to obtain its AcoustID (unpacking arguments)."""
    file_path, cache_lock = args
    rid = get_acoustid(file_path, cache_lock=cache_lock)
    if rid:
        return rid, file_path
    return None


def resolve_duplicates(duplicates, action, move_dir, base_dir, verbose, dry_run):
    """Resolves duplicates (list, move, delete) - directory-based."""
    for duplicate_set in duplicates:
        # Determine the best directory to keep (prioritize FLAC and largest total size)
        best_dir = None
        best_dir_size = -1
        dir_stats = {}

        for file_path in duplicate_set:
            dir_path = os.path.dirname(file_path)
            if dir_path not in dir_stats:
                dir_stats[dir_path] = {'size': 0, 'has_flac': False}
                for f in os.listdir(dir_path):
                    f_path = os.path.join(dir_path,f)
                    if os.path.isfile(f_path):
                      dir_stats[dir_path]['size'] += os.path.getsize(f_path)
                      if f.lower().endswith('.flac'):
                          dir_stats[dir_path]['has_flac'] = True

        for dir_path, stats in dir_stats.items():
            if best_dir is None or (stats['has_flac'] and not dir_stats[best_dir]['has_flac']) or \
               (stats['has_flac'] == dir_stats[best_dir]['has_flac'] and stats['size'] > best_dir_size):
                best_dir = dir_path
                best_dir_size = stats['size']

        # Determine directories to delete/move
        dirs_to_remove = [dir_path for dir_path in dir_stats if dir_path != best_dir]

        # Calculate total files and size to remove
        files_to_remove = []
        for dir_path_to_remove in dirs_to_remove:
            for f in os.listdir(dir_path_to_remove):
              file_to_remove = os.path.join(dir_path_to_remove, f)
              if os.path.isfile(file_to_remove):
                files_to_remove.append(file_to_remove)

        summary_stats['total_files_to_remove'] += len(files_to_remove)
        for file_path in files_to_remove:
          if os.path.exists(file_path):
            summary_stats['total_storage_to_save'] += os.path.getsize(file_path)

        if action == 'list':
            logging.info(f"Best directory: {best_dir}")
            for dir_to_remove in dirs_to_remove:
                logging.info(f"To remove (directory): {dir_to_remove}")
        elif action == 'move' and move_dir:
            if not dry_run:
                move_duplicates(dirs_to_remove, best_dir, move_dir, base_dir)
            else:
                logging.info(f"[DRY RUN] Would move directories: {dirs_to_remove} to {move_dir}, keeping {best_dir}")
        elif action == 'delete':
            if not dry_run:
                delete_duplicates(dirs_to_remove)
            else:
                 logging.info(f"[DRY RUN] Would delete directories: {dirs_to_remove}")



def move_duplicates(dirs_to_remove, original_dir, move_dir, base_dir):
    """Moves duplicate directories, preserving structure."""
    for dir_path in dirs_to_remove:
        relative_path = os.path.relpath(dir_path, start=base_dir)
        target_path = os.path.join(move_dir, relative_path)

        if not os.path.exists(target_path):
            os.makedirs(target_path)
        #Move files individually
        for item in os.listdir(dir_path):
          s = os.path.join(dir_path, item)
          d = os.path.join(target_path, item)
          if os.path.isfile(s):
            shutil.move(s, d)
            logging.info(f"Moved {s} to {d}")
          elif os.path.isdir(s): #shouldn't happen, but check
            logging.warning(f"Unexpected directory {s} within duplicate directory.")

        # Clean up empty directory after moving files
        if not os.listdir(dir_path):
          os.rmdir(dir_path)
          logging.info(f"Removed empty directory {dir_path}")




def delete_duplicates(dirs_to_remove):
    """Deletes duplicate directories and their contents."""
    for dir_path in dirs_to_remove:
        logging.info(f"Deleting directory (and contents): {dir_path}")
        try:
            shutil.rmtree(dir_path)  # Delete directory and its contents
        except OSError as e:
            logging.error(f"Error deleting directory {dir_path}: {e}")

def display_summary():
    """Displays the summary statistics."""
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
    parser.add_argument('-p', '--path', required=True, help="Path to the music directory.")
    parser.add_argument('-a', '--action', required=True, choices=['list', 'move', 'delete'], help="Action: list, move, or delete.")
    parser.add_argument('-m', '--move-dir', help="Directory to move duplicates (required if action is 'move').")
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output.")
    parser.add_argument('--log-level', default='INFO', help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).")
    parser.add_argument('--no-multiprocessing', action='store_true', help="Disable multiprocessing.")
    parser.add_argument('--dry-run', action='store_true', help="Perform a dry run without modifying files.")
    args = parser.parse_args()

    log_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(log_level, int):
        print(f"Invalid log level: {args.log_level}")
        return

    setup_logging(log_level)

    if args.action == 'move' and not args.move_dir:
        parser.error("--move-dir is required when action is 'move'")

    if not check_fpcalc():
        logging.error("fpcalc not found. Please ensure it's installed and in your PATH.")
        sys.exit(1)

    start_time = time.time()
    logging.info("Starting music deduplication process...")
    logging.info(f"Scanning directory: {args.path}")

    duplicates = find_duplicates(args.path, verbose=args.verbose, use_multiprocessing=not args.no_multiprocessing)

    if duplicates:
        logging.info(f"Found {len(duplicates)} sets of duplicate directories.")
        resolve_duplicates(duplicates, args.action, args.move_dir, base_dir=os.path.abspath(args.path), verbose=args.verbose, dry_run=args.dry_run)
    else:
        logging.info("No duplicates found.")

    save_cache(cache_lock)
    total_time = time.time() - start_time
    logging.info(f"\nCompleted in {total_time:.2f} seconds.")
    display_summary()

if __name__ == "__main__":
    main()
