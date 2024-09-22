import os
import shutil
import argparse
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

    # Extract metadata
    file_metadata['artist'] = audio.get('artist', ['Unknown Artist'])[0]
    file_metadata['title'] = audio.get('title', ['Unknown Title'])[0]
    file_metadata['album'] = audio.get('album', ['Unknown Album'])[0]
    file_metadata['tracknumber'] = audio.get('tracknumber', [0])[0]
    
    file_extension = os.path.splitext(file_path)[1].lower()

    if file_extension == '.flac':
        file_metadata['bitrate'] = FLAC(file_path).info.bitrate
        file_metadata['format'] = 'lossless'
    elif file_extension == '.mp3':
        file_metadata['bitrate'] = MP3(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
    elif file_extension == '.ogg':
        file_metadata['bitrate'] = OggVorbis(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
    elif file_extension == '.wav':
        file_metadata['bitrate'] = WAVE(file_path).info.bitrate
        file_metadata['format'] = 'uncompressed'
    elif file_extension in ['.m4a', '.aac']:
        file_metadata['bitrate'] = MP4(file_path).info.bitrate
        file_metadata['format'] = 'lossy'
    else:
        return None

    file_cache[file_path] = file_metadata
    return file_metadata

def find_duplicates(directory, verbose=False):
    """Recursively scans directory for music files and identifies duplicates based on metadata."""
    files_by_song = {}
    duplicates = []
    file_count = 0
    start_time = time.time()

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if not file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
                continue

            metadata = get_file_metadata(file_path)
            if not metadata:
                continue

            key = (metadata['artist'], metadata['title'], metadata['album'])
            if key not in files_by_song:
                files_by_song[key] = []
            files_by_song[key].append(file_path)

            file_count += 1

            # Verbose output
            if verbose and file_count % 100 == 0:
                elapsed_time = time.time() - start_time
                files_per_sec = file_count / elapsed_time
                print(f"Processed {file_count} files. Speed: {files_per_sec:.2f} files/sec")

    # Identify duplicates
    for file_list in files_by_song.values():
        if len(file_list) > 1:
            duplicates.append(file_list)

    # Final verbose output
    if verbose:
        total_time = time.time() - start_time
        print(f"Finished processing {file_count} files in {total_time:.2f} seconds. Average speed: {file_count/total_time:.2f} files/sec.")

    return duplicates

def resolve_duplicates(duplicates, action='list', move_dir=None, verbose=False):
    """Resolves duplicates by either listing, moving, or deleting them."""
    for duplicate_set in duplicates:
        best_file = None
        best_metadata = None
        to_delete = []

        for file_path in duplicate_set:
            metadata = get_file_metadata(file_path)

            if best_file is None or (metadata['format'] == 'lossless' and (best_metadata is None or metadata['bitrate'] > best_metadata['bitrate'])):
                if best_file:
                    to_delete.append(best_file)
                best_file = file_path
                best_metadata = metadata
            else:
                to_delete.append(file_path)

        if action == 'list':
            print(f"Best file: {best_file}")
            for file in to_delete:
                print(f"To delete: {file}")
        elif action == 'move' and move_dir:
            move_duplicates(to_delete, best_file, move_dir)
        elif action == 'delete':
            delete_duplicates(to_delete)

def move_duplicates(to_delete, original_file, move_dir):
    """Moves duplicate files to a new directory while keeping the folder structure intact."""
    for file_path in to_delete:
        relative_path = os.path.relpath(file_path, start=os.path.dirname(original_file))
        target_path = os.path.join(move_dir, relative_path)
        target_dir_path = os.path.dirname(target_path)
        if not os.path.exists(target_dir_path):
            os.makedirs(target_dir_path)
        print(f"Moving {file_path} to {target_path}")
        shutil.move(file_path, target_path)

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path in to_delete:
        print(f"Deleting {file_path}")
        os.remove(file_path)

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

    duplicates = find_duplicates(args.path, verbose=args.verbose)

    if duplicates:
        print(f"Found {len(duplicates)} sets of duplicates.")
        resolve_duplicates(duplicates, args.action, args.move_dir, verbose=args.verbose)
    else:
        print("No duplicates found.")

    save_cache()

    total_time = time.time() - start_time
    print(f"Completed in {total_time:.2f} seconds.")

if __name__ == "__main__":
    main()
