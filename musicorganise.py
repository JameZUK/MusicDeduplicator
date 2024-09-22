import os
import json
import shutil
import argparse
import acoustid
from fuzzywuzzy import fuzz
from mutagen import File
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.mp4 import MP4
import time

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
    ACOUSTID_API_KEY = input("Please enter your AcoustID API key: ")
    config['acoustid_api_key'] = ACOUSTID_API_KEY
    save_config(config)

# If no fuzzy threshold exists, prompt user to set it
if 'fuzzy_threshold' not in config:
    try:
        FUZZY_THRESHOLD = int(input(f"Please enter the fuzzy match threshold (default is 90): ") or 90)
    except ValueError:
        FUZZY_THRESHOLD = 90
    config['fuzzy_threshold'] = FUZZY_THRESHOLD
    save_config(config)

# Dictionary to store cached metadata and fingerprints
CACHE_FILE = 'file_cache.json'
file_cache = {}

# Summary statistics
summary_stats = {
    'total_files_processed': 0,
    'total_duplicates_found': 0,
    'total_files_to_remove': 0,
    'total_storage_to_save': 0,
    'folders_deleted': 0,
    'folders_moved': 0,
    'files_by_format': {
        'mp3': 0,
        'flac': 0,
        'ogg': 0,
        'wav': 0,
        'aac': 0,
        'm4a': 0,
    }
}

# Load cached data if it exists
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'r') as f:
        file_cache = json.load(f)

# Save cache to file for persistence
def save_cache():
    with open(CACHE_FILE, 'w') as f:
        json.dump(file_cache, f)

def validate_cached_data(file_path):
    """Re-validates the cached metadata and AcoustID fingerprint."""
    if file_path in file_cache:
        metadata = get_file_metadata(file_path, revalidate=True)
        acoustid_rid = get_acoustid(file_path, revalidate=True)
        return metadata, acoustid_rid
    return get_file_metadata(file_path), get_acoustid(file_path)

def get_file_metadata(file_path, revalidate=False):
    """Fetches or re-validates metadata of the music file using Mutagen and caches it for performance."""
    if file_path in file_cache and not revalidate:
        return file_cache[file_path].get('metadata')
    
    file_metadata = {}
    file_metadata['size'] = os.path.getsize(file_path)
    file_metadata['mtime'] = os.path.getmtime(file_path)
    
    audio = File(file_path, easy=True)
    
    if audio is None:
        return None

    # Normalize case by converting artist, title, and album to lowercase for case-insensitive comparison
    file_metadata['artist'] = audio.get('artist', ['Unknown Artist'])[0].lower()
    file_metadata['title'] = audio.get('title', ['Unknown Title'])[0].lower()
    file_metadata['album'] = audio.get('album', ['Unknown Album'])[0].lower()
    file_metadata['tracknumber'] = audio.get('tracknumber', [0])[0]
    
    file_extension = os.path.splitext(file_path)[1].lower()

    if file_extension == '.flac':
        file_metadata['bitrate'] = FLAC(file_path).info.bitrate
        file_metadata['format'] = 'lossless'
        summary_stats['files_by_format']['flac'] += 1
    elif file_extension == '.mp3':
        file_metadata['bitrate'] = MP3(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
        summary_stats['files_by_format']['mp3'] += 1
    elif file_extension == '.ogg':
        file_metadata['bitrate'] = OggVorbis(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
        summary_stats['files_by_format']['ogg'] += 1
    elif file_extension == '.wav':
        file_metadata['bitrate'] = WAVE(file_path).info.bitrate
        file_metadata['format'] = 'uncompressed'
        summary_stats['files_by_format']['wav'] += 1
    elif file_extension in ['.m4a', '.aac']:
        file_metadata['bitrate'] = MP4(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
        summary_stats['files_by_format']['aac'] += 1
        summary_stats['files_by_format']['m4a'] += 1
    else:
        return None

    # Update or add the cached metadata
    file_cache[file_path] = {'metadata': file_metadata}
    save_cache()
    return file_metadata
    
def get_acoustid(file_path, revalidate=False):
    """Fetches or re-validates the AcoustID fingerprint and caches it."""
    if file_path in file_cache and 'acoustid' in file_cache[file_path] and not revalidate:
        return file_cache[file_path]['acoustid']
    
    try:
        # Generate fingerprint and duration
        duration, fingerprint = acoustid.fingerprint_file(file_path)
        
        # Perform AcoustID lookup
        response = acoustid.lookup(ACOUSTID_API_KEY, fingerprint, duration)
        
        # Check if the response is successful
        if response['status'] != 'ok':
            error_message = response.get('error', {}).get('message', 'Unknown error')
            print(f"AcoustID lookup failed for {file_path}: {error_message}")
            return None
        
        results = response.get('results', [])
        if not results:
            print(f"No AcoustID results for {file_path}")
            return None
        
        # Get the best match (highest score)
        best_result = max(results, key=lambda x: x.get('score', 0))
        
        # Extract recording information
        recordings = best_result.get('recordings', [])
        if not recordings:
            print(f"No recordings found for {file_path}")
            return None
        
        recording = recordings[0]  # Use the first recording
        rid = recording.get('id')
        title = recording.get('title', 'Unknown Title')
        
        # Extract the artist if available
        artists = recording.get('artists', [])
        artist_name = 'Unknown Artist'
        if artists:
            artist_name = artists[0].get('name', 'Unknown Artist')
        
        print(f"AcoustID: {rid}, Title: {title}, Artist: {artist_name}")
        
        # Cache the AcoustID result
        file_cache[file_path]['acoustid'] = rid
        save_cache()
        return rid
    except Exception as e:
        print(f"AcoustID lookup failed for {file_path}: {e}")
        return None
        
def fuzzy_match(metadata1, metadata2):
    """Performs fuzzy matching between two metadata sets (title, artist, album) and returns the similarity percentage."""
    title_match = fuzz.ratio(metadata1['title'], metadata2['title'])
    artist_match = fuzz.ratio(metadata1['artist'], metadata2['artist'])
    album_match = fuzz.ratio(metadata1['album'], metadata2['album'])
    
    # Average percentage match across title, artist, and album
    avg_match = (title_match + artist_match + album_match) / 3
    
    return avg_match

def find_duplicates(directory, verbose=False):
    """Recursively scans directory for music files and identifies duplicates based on fuzzy metadata matching and AcoustID."""
    files_by_song = {}
    duplicates = []
    start_time = time.time()

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if not file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
                continue

            metadata, acoustid_rid = validate_cached_data(file_path)
            if not metadata:
                continue

            # Use AcoustID for exact matching when available, fall back on fuzzy matching if no AcoustID is found
            if acoustid_rid:
                key = (acoustid_rid, metadata['artist'], metadata['title'], metadata['album'])
            else:
                key = (None, metadata['artist'], metadata['title'], metadata['album'])

            # Find potential duplicates by AcoustID or fuzzy matching
            duplicate_found = False
            for existing_key, file_list in files_by_song.items():
                if acoustid_rid and existing_key[0] == acoustid_rid:
                    file_list.append((file_path, 100, 'AcoustID'))  # Exact AcoustID match
                    duplicate_found = True
                    break
                elif fuzzy_match(metadata, {'artist': existing_key[1], 'title': existing_key[2], 'album': existing_key[3]}) >= FUZZY_THRESHOLD:
                    file_list.append((file_path, fuzz.ratio(metadata['title'], existing_key[2]), 'Fuzzy'))  # Fuzzy match based on metadata
                    duplicate_found = True
                    break

            if not duplicate_found:
                files_by_song[key] = [(file_path, 100, 'AcoustID' if acoustid_rid else 'Fuzzy')]  # Add the first file

            summary_stats['total_files_processed'] += 1

            # Verbose output
            if verbose and summary_stats['total_files_processed'] % 100 == 0:
                elapsed_time = time.time() - start_time
                files_per_sec = summary_stats['total_files_processed'] / elapsed_time
                print(f"Processed {summary_stats['total_files_processed']} files. Speed: {files_per_sec:.2f} files/sec")

    # Identify duplicates
    for file_list in files_by_song.values():
        if len(file_list) > 1:
            duplicates.append(file_list)
            summary_stats['total_duplicates_found'] += 1

    return duplicates

def resolve_duplicates(duplicates, action='list', move_dir=None, base_dir=None, verbose=False):
    """Resolves duplicates by either listing, moving, or deleting them."""
    for duplicate_set in duplicates:
        best_file = None
        best_metadata = None
        to_delete = []

        for file_path, match_percentage, match_type in duplicate_set:
            # Revalidate metadata and acoustid before taking action
            metadata, _ = validate_cached_data(file_path)

            if best_file is None or (metadata['format'] == 'lossless' and (best_metadata is None or metadata['bitrate'] > best_metadata['bitrate'])):
                if best_file:
                    to_delete.append((best_file, match_percentage, match_type))
                best_file = file_path
                best_metadata = metadata
            else:
                to_delete.append((file_path, match_percentage, match_type))

        # Update summary statistics
        summary_stats['total_files_to_remove'] += len(to_delete)
        summary_stats['total_storage_to_save'] += sum(os.path.getsize(f[0]) for f in to_delete)

        if action == 'list':
            print(f"Best file: {best_file}")
            for file, percentage, match_type in to_delete:
                print(f"To delete: {file} (Match: {percentage:.2f}%, Type: {match_type})")
        elif action == 'move' and move_dir:
            move_duplicates(to_delete, best_file, move_dir, base_dir)
        elif action == 'delete':
            delete_duplicates(to_delete)

def move_duplicates(to_delete, original_file, move_dir, base_dir):
    """Moves duplicate files to a new directory while keeping the folder structure intact."""
    for file_path, match_percentage, match_type in to_delete:
        # Create the relative path based on the base directory (i.e., the root of the music folder being processed)
        relative_path = os.path.relpath(file_path, start=base_dir)
        
        # Construct the full target path in the move directory
        target_path = os.path.join(move_dir, relative_path)
        target_dir_path = os.path.dirname(target_path)
        
        # Debugging output to check paths
        print(f"Moving {file_path} to {target_path} (Match: {match_percentage:.2f}%, Type: {match_type})")
        print(f"Creating directory: {target_dir_path}")
        
        # Ensure the target directory exists
        if not os.path.exists(target_dir_path):
            os.makedirs(target_dir_path)
        
        # Move the file to the target directory
        shutil.move(file_path, target_path)

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path, match_percentage, match_type in to_delete:
        print(f"Deleting {file_path} (Match: {match_percentage:.2f}%, Type: {match_type})")
        os.remove(file_path)

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

    # Run the regular duplicate finding and processing logic
    duplicates = find_duplicates(args.path, verbose=args.verbose)

    if duplicates:
        print(f"Found {len(duplicates)} sets of duplicates.")
        resolve_duplicates(duplicates, args.action, args.move_dir, base_dir=args.path, verbose=args.verbose)
    else:
        print("No duplicates found.")

    save_cache()

    total_time = time.time() - start_time
    print(f"\nCompleted in {total_time:.2f} seconds.")
    
    display_summary()

if __name__ == "__main__":
    main()
