Music Deduplication Tool
Overview

The Music Deduplication Tool is a Python script designed to help you manage your music library by identifying and handling duplicate audio files. It scans your music directories, detects duplicates using audio fingerprinting and metadata analysis, and allows you to either list, move, or delete the duplicates based on your preference.
Features

    Audio Fingerprinting with AcoustID: Utilizes AcoustID and the Chromaprint acoustic fingerprinting library to identify audio duplicates, even if file metadata differs.
    Metadata Analysis: Extracts and compares metadata (artist, title, album) using fuzzy matching to detect duplicates when fingerprints are unavailable.
    Batch Processing: Processes files in batches to optimize resource usage and prevent system overloads.
    Caching Mechanism: Caches file metadata and AcoustID fingerprints to improve performance on subsequent runs.
    Customizable Actions: Supports listing, moving, or deleting duplicates based on user selection.
    Verbose Output: Provides detailed progress information when enabled.

Installation
Prerequisites

    Python 3.6 or higher
    pip (Python package installer)

Required Python Libraries

Install the required Python libraries using pip:

bash

pip install acoustid mutagen fuzzywuzzy[speedup] python-magic

    acoustid: For audio fingerprinting and AcoustID API interaction.
    mutagen: For reading and writing audio metadata.
    fuzzywuzzy: For fuzzy string matching in metadata comparison.
    python-magic: For file type detection.

System Dependencies

Install the following system dependencies:
On Debian/Ubuntu-based systems:

bash

sudo apt-get update
sudo apt-get install ffmpeg libchromaprint-tools

    ffmpeg: Provides audio decoding capabilities required by some audio processing libraries.
    libchromaprint-tools: Provides fpcalc, required by AcoustID for fingerprinting.

On macOS using Homebrew:

bash

brew install ffmpeg chromaprint

Configuration
Obtain an AcoustID API Key

To use the audio fingerprinting feature, you need an AcoustID API key:

    Register for a free API key at AcoustID API Key Registration.
    The script will prompt you for the API key on the first run and store it in config.json.

Configure Fuzzy Match Threshold (Optional)

The script uses a fuzzy matching threshold for metadata comparison (default is 90). You can set a custom threshold during the initial run or by editing config.json.
Usage
Running the Script

Basic command structure:

bash

python3 music_deduplicate.py --path "/path/to/music" --action ACTION [options]

Command-Line Options

    -p, --path: (Required) Path to the music directory to scan.
    -a, --action: (Required) Action to take on duplicates. Choices are:
        list: List duplicates without making any changes.
        move: Move duplicates to a specified directory.
        delete: Delete duplicate files permanently.
    -m, --move-dir: (Required if action is 'move') Directory to move duplicates to.
    -v, --verbose: Enable verbose output with processing speed and progress updates.

Examples
List Duplicates

bash

python3 music_deduplicate.py --path "/media/music/Organised" --action list --verbose

Move Duplicates to a Directory

bash

python3 music_deduplicate.py --path "/media/music/Organised" --action move --move-dir "/media/music/Duplicates" --verbose

Delete Duplicates

bash

python3 music_deduplicate.py --path "/media/music/Organised" --action delete --verbose

Adjusting Batch Size (Optional)

The script processes files in batches to optimize resource usage. You can adjust the batch size by modifying the batch_size variable in the script:

python

batch_size = 100  # Adjust batch size as needed

Increasing Open File Limits (If Necessary)

If you encounter [Errno 24] Too many open files error, you may need to increase your system's open file limit.
Temporarily Increase Limit

bash

ulimit -n 8192

Permanently Increase Limit

    Edit /etc/security/limits.conf (Linux):

    yaml

    your_username soft nofile 8192
    your_username hard nofile 16384

    Replace your_username with your actual username.

    Log out and log back in for changes to take effect.

How It Works

    File Scanning: The script recursively scans the specified music directory for supported audio file formats (.mp3, .flac, .ogg, .wav, .m4a, .aac).

    Metadata Extraction: For each file, it extracts metadata such as artist, title, album, and track number using mutagen.

    Audio Fingerprinting: It generates an audio fingerprint using fpcalc and retrieves an AcoustID recording ID.

    Duplicate Detection:
        AcoustID Matching: If an AcoustID is available, it uses the recording ID for exact duplicate matching.
        Metadata Fuzzy Matching: If AcoustID is unavailable, it performs fuzzy matching on metadata fields to identify potential duplicates.

    Action Execution: Based on the specified action (list, move, delete), the script processes the identified duplicates accordingly.

    Caching: The script caches metadata and AcoustID results to file_cache.json to improve performance on subsequent runs.

Limitations

    AcoustID API Rate Limits: Be mindful of AcoustID API usage limits when processing large music libraries.
    Metadata Dependence: Accurate metadata is crucial for effective duplicate detection when AcoustID is unavailable.
    File Permissions: Ensure the script has the necessary read/write permissions for all files and directories involved.

Troubleshooting

    Too Many Open Files Error:
        Increase the open file limit as described in the installation section.
        Reduce the batch_size to a smaller number to decrease resource usage.
    Missing Dependencies:
        Verify that all Python libraries and system dependencies are correctly installed.
    AcoustID Lookup Failures:
        Ensure you have a valid AcoustID API key.
        Check your internet connection.
        Some files may be corrupt or unsupported; consider replacing them.

Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.
License

This project is licensed under the MIT License.
Acknowledgments

    AcoustID: For providing an open-source audio identification service.
    Mutagen: For the powerful audio metadata handling library.
    FuzzyWuzzy: For the fuzzy string matching library.

Contact

For any questions or support, please open an issue on the GitHub repository.
