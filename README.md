Summary of Key Features:

    Case-Insensitive Duplicate Detection: The script normalizes the artist, title, and album fields by converting them to lowercase before comparing, ensuring that differences in capitalization don't lead to missed duplicates.
    Folder Removal Logic: Folders will only be removed if they contain no media files. Non-media files (like .txt, .jpg, etc.) in a folder will prevent it from being deleted.
    Relative Path Handling: The move_duplicates function now correctly constructs the relative path from the base directory, ensuring files are moved to the correct target directory without permission issues or unexpected traversal problems.
    Detailed Summary: At the end of the script's execution, a summary will show the total number of files processed, duplicates found, files to be removed, storage space saved, and empty folders removed.

Example Commands:

    List duplicates with case-insensitive matching:

    bash

python script.py --path "/path/to/music" --action list

Move duplicates and remove empty folders:

bash

python script.py --path "/path/to/music" --action move --move-dir "/path/to/.Duplicates" --remove-empty-folders --verbose
