import os
import shutil
import argparse
from fuzzywuzzy import fuzz
from mutagen import File
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.mp4 import MP4
import time
import json

# Dictionary to store cached metadata of files to improve performance
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

# Fuzzy match threshold (90% similarity considered a match)
FUZZY_THRESHOLD = 90

# Load cached data if it exists
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'r') as f:
        file_cache = json.load(f)

# Save cache to file for persistence
def save_cache():
    with open(CACHE_FILE, 'w') as f:
        json.dump(file_cache, f)

def get_file_metadata(file_path):
    """Fetches metadata of the music file using Mutagen and caches it for performance."""
    if file_path in file_cache:
        return file_cache[file_path]
    
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

    file_cache[file_path] = file_metadata
    return file_metadata

def fuzzy_match(metadata1, metadata2):
    """Performs fuzzy matching between two metadata sets (title, artist, album) and returns the similarity percentage."""
    title_match = fuzz.ratio(metadata1['title'], metadata2['title'])
    artist_match = fuzz.ratio(metadata1['artist'], metadata2['artist'])
    album_match = fuzz.ratio(metadata1['album'], metadata2['album'])
    
    # Average percentage match across title, artist, and album
    avg_match = (title_match + artist_match + album_match) / 3
    
    return avg_match

def find_duplicates(directory, verbose=False):
    """Recursively scans directory for music files and identifies duplicates based on fuzzy metadata matching."""
    files_by_song = {}
    duplicates = []
    start_time = time.time()

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if not file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
                continue

            metadata = get_file_metadata(file_path)
            if not metadata:
                continue

            # Find potential duplicates by fuzzy matching
            duplicate_found = False
            for key, file_list in files_by_song.items():
                match_percentage = fuzzy_match(metadata, key)
                if match_percentage >= FUZZY_THRESHOLD:
                    file_list.append((file_path, match_percentage))
                    duplicate_found = True
                    break

            if not duplicate_found:
                files_by_song[(metadata['artist'], metadata['title'], metadata['album'])] = [(file_path, 100)]  # Add the first file with 100% match

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

        for file_path, match_percentage in duplicate_set:
            metadata = get_file_metadata(file_path)

            if best_file is None or (metadata['format'] == 'lossless' and (best_metadata is None or metadata['bitrate'] > best_metadata['bitrate'])):
                if best_file:
                    to_delete.append((best_file, match_percentage))
                best_file = file_path
                best_metadata = metadata
            else:
                to_delete.append((file_path, match_percentage))

        # Update summary statistics
        summary_stats['total_files_to_remove'] += len(to_delete)
        summary_stats['total_storage_to_save'] += sum(os.path.getsize(f[0]) for f in to_delete)

        if action == 'list':
            print(f"Best file: {best_file}")
            for file, percentage in to_delete:
                print(f"To delete: {file} (Match: {percentage:.2f}%)")
        elif action == 'move' and move_dir:
            move_duplicates(to_delete, best_file, move_dir, base_dir)
        elif action == 'delete':
            delete_duplicates(to_delete)

def move_duplicates(to_delete, original_file, move_dir, base_dir):
    """Moves duplicate files to a new directory while keeping the folder structure intact."""
    for file_path, match_percentage in to_delete:
        # Create the relative path based on the base directory (i.e., the root of the music folder being processed)
        relative_path = os.path.relpath(file_path, start=base_dir)
        
        # Construct the full target path in the move directory
        target_path = os.path.join(move_dir, relative_path)
        target_dir_path = os.path.dirname(target_path)
        
        # Debugging output to check paths
        print(f"Moving {file_path} to {target_path} (Match: {match_percentage:.2f}%)")
        print(f"Creating directory: {target_dir_path}")
        
        # Ensure the target directory exists
        if not os.path.exists(target_dir_path):
            os.makedirs(target_dir_path)
        
        # Move the file to the target directory
        shutil.move(file_path, target_path)

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path, match_percentage in to_delete:
        print(f"Deleting {file_path} (Match: {match_percentage:.2f}%)")
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
