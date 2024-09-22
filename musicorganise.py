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

def find_duplicates(directory, verbose=False):
    """Recursively scans directory for music files and identifies duplicates based on metadata."""
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

            key = (metadata['artist'], metadata['title'], metadata['album'])
            if key not in files_by_song:
                files_by_song[key] = []
            files_by_song[key].append(file_path)

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

        for file_path in duplicate_set:
            metadata = get_file_metadata(file_path)

            if best_file is None or (metadata['format'] == 'lossless' and (best_metadata is None or metadata['bitrate'] > best_metadata['bitrate'])):
                if best_file:
                    to_delete.append(best_file)
                best_file = file_path
                best_metadata = metadata
            else:
                to_delete.append(file_path)

        # Update summary statistics
        summary_stats['total_files_to_remove'] += len(to_delete)
        summary_stats['total_storage_to_save'] += sum(os.path.getsize(f) for f in to_delete)

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
        # Create the relative path based on the base directory (i.e., the root of the music folder being processed)
        relative_path = os.path.relpath(file_path, start=base_dir)
        
        # Construct the full target path in the move directory
        target_path = os.path.join(move_dir, relative_path)
        target_dir_path = os.path.dirname(target_path)
        
        # Debugging output to check paths
        print(f"Moving {file_path} to {target_path}")
        print(f"Creating directory: {target_dir_path}")
        
        # Ensure the target directory exists
        if not os.path.exists(target_dir_path):
            os.makedirs(target_dir_path)
        
        # Move the file to the target directory
        shutil.move(file_path, target_path)

def delete_duplicates(to_delete):
    """Deletes duplicate files."""
    for file_path in to_delete:
        print(f"Deleting {file_path}")
        os.remove(file_path)

def move_or_delete_folder(folder_path, move_dir=None, action='move', verbose=False):
    """Move or delete folders, depending on the action selected."""
    if action == 'move' and move_dir:
        relative_path = os.path.relpath(folder_path)
        target_path = os.path.join(move_dir, relative_path)

        print(f"Moving folder {folder_path} to {target_path}")
        shutil.move(folder_path, target_path)
        summary_stats['folders_moved'] += 1
    elif action == 'delete':
        print(f"Deleting folder {folder_path}")
        shutil.rmtree(folder_path)
        summary_stats['folders_deleted'] += 1

def is_folder_empty_of_media(path, media_extensions=('.mp3', '.flac', '.ogg', '.wav', '.m4a', '.aac')):
    """Checks if a folder contains any media files. Returns True if no media files are found and no subfolders exist."""
    for root, dirs, files in os.walk(path):
        # Check if there are any media files
        for file in files:
            if file.lower().endswith(media_extensions):
                return False  # Media files exist

        # If there are subfolders, we don't consider the folder empty
        if dirs:
            return False  # Subfolders exist

    return True

def clean_empty_folders(path, action='move', move_dir=None, verbose=False):
    """Cleans up and removes or moves folders that do not contain any media files and have no non-empty subfolders."""
    for root, dirs, _ in os.walk(path, topdown=False):
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            if is_folder_empty_of_media(dir_path):
                move_or_delete_folder(dir_path, move_dir=move_dir, action=action, verbose=verbose)

def display_summary():
    """Displays the summary statistics after processing."""
    print("\nSummary:")
    print(f"Total files processed: {summary_stats['total_files_processed']}")
    print(f"Total duplicates found: {summary_stats['total_duplicates_found']}")
    print(f"Total files to remove: {summary_stats['total_files_to_remove']}")
    print(f"Estimated storage saved: {summary_stats['total_storage_to_save'] / (1024 * 1024):.2f} MB")
    print(f"Folders moved: {summary_stats['folders_moved']}")
    print(f"Folders deleted: {summary_stats['folders_deleted']}")
    print("\nFiles processed by format:")
    for format, count in summary_stats['files_by_format'].items():
        print(f"  {format.upper()}: {count} files")

def main():
    parser = argparse.ArgumentParser(description="Music collection deduplication script.")
    
    parser.add_argument('-p', '--path', required=True, help="Path to the music directory to scan.")
    parser.add_argument('-a', '--action', required=True, choices=['list', 'move', 'delete'], help="Action to take: list, move, or delete duplicates.")
    parser.add_argument('-m', '--move-dir', help="Directory to move duplicates to (required if action is 'move').")
    parser.add_argument('-r', '--remove-empty-folders', action='store_true', help="Remove or move empty folders after files are processed.")
    parser.add_argument('-c', '--clean-folders', action='store_true', help="Clean up and remove or move folders that do not contain any media files.")
    parser.add_argument('-v', '--verbose', action='store_true', help="Enable verbose output with processing speed.")

    args = parser.parse_args()

    # Ensure move_dir is provided if action is 'move'
    if args.action == 'move' and not args.move_dir:
        parser.error("--move-dir is required when action is 'move'")

    start_time = time.time()

    # If clean-folders option is selected, clean folders based on the action
    if args.clean_folders:
        print(f"Cleaning up empty folders by {args.action}...")
        clean_empty_folders(args.path, action=args.action, move_dir=args.move_dir, verbose=args.verbose)

    else:
        # Run the regular duplicate finding and processing logic
        duplicates = find_duplicates(args.path, verbose=args.verbose)

        if duplicates:
            print(f"Found {len(duplicates)} sets of duplicates.")
            resolve_duplicates(duplicates, args.action, args.move_dir, base_dir=args.path, verbose=args.verbose)
        else:
            print("No duplicates found.")

        save_cache()

        # Process folders (move or delete) if the option is selected
        if args.remove_empty_folders:
            print("\nChecking for empty folders...")
            clean_empty_folders(args.path, action=args.action, move_dir=args.move_dir, verbose=args.verbose)

    total_time = time.time() - start_time
    print(f"\nCompleted in {total_time:.2f} seconds.")
    
    display_summary()

if __name__ == "__main__":
    main()
