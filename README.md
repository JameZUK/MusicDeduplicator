# Music Deduplication Tool

## Overview

The **Music Deduplication Tool** is a Python script designed to help you manage and clean up your music library by identifying and handling duplicate audio files. It scans your music directories, detects duplicates using metadata analysis and audio fingerprinting with AcoustID, and allows you to either list, move, or delete the duplicates based on your preference.

## Features

- **Metadata Analysis with Fuzzy Matching**: Quickly identifies potential duplicates by comparing metadata (artist, title, album) using fuzzy string matching.
- **Audio Fingerprinting with AcoustID**: Utilizes AcoustID and the Chromaprint library to accurately identify audio duplicates, even if file metadata differs or is missing.
- **Batch Processing**: Processes files in batches to optimize resource usage and prevent system overload.
- **Multiprocessing Support**: Leverages multiple CPU cores to speed up processing tasks.
- **Progress Bar**: Provides a real-time progress bar for AcoustID lookups using `tqdm`.
- **Caching Mechanism**: Caches file metadata and AcoustID fingerprints to improve performance on subsequent runs.
- **Customizable Actions**: Supports listing, moving, or deleting duplicates based on user selection.
- **Logging Functionality**: Detailed logging with configurable log levels, stored in `music_deduplicate.log`.
- **Configurable Parameters**: Batch size, fuzzy match threshold, and other settings are configurable via `config.json`.
- **Verbose Output**: Provides detailed progress information when enabled.

## Installation

### Prerequisites

- **Python 3.6 or higher**
- **pip** (Python package installer)

### Required Python Libraries

Install the required Python libraries using pip:

```bash
pip install acoustid mutagen fuzzywuzzy[speedup] tqdm
```
# Music Deduplication Tool

## Overview

The **Music Deduplication Tool** is a Python script designed to help you manage and clean up your music library by identifying and handling duplicate audio files. It scans your music directories, detects duplicates using metadata analysis and audio fingerprinting with AcoustID, and allows you to either list, move, or delete the duplicates based on your preference.

## Features

- **Metadata Analysis with Fuzzy Matching**: Quickly identifies potential duplicates by comparing metadata (artist, title, album) using fuzzy string matching.
- **Audio Fingerprinting with AcoustID**: Utilizes AcoustID and the Chromaprint library to accurately identify audio duplicates, even if file metadata differs or is missing.
- **Batch Processing**: Processes files in batches to optimize resource usage and prevent system overload.
- **Multiprocessing Support**: Leverages multiple CPU cores to speed up processing tasks.
- **Progress Bar**: Provides a real-time progress bar for AcoustID lookups using `tqdm`.
- **Caching Mechanism**: Caches file metadata and AcoustID fingerprints to improve performance on subsequent runs.
- **Customizable Actions**: Supports listing, moving, or deleting duplicates based on user selection.
- **Logging Functionality**: Detailed logging with configurable log levels, stored in `music_deduplicate.log`.
- **Configurable Parameters**: Batch size, fuzzy match threshold, and other settings are configurable via `config.json`.
- **Verbose Output**: Provides detailed progress information when enabled.

## Installation

### Prerequisites

- **Python 3.6 or higher**
- **pip** (Python package installer)

### Required Python Libraries

Install the required Python libraries using pip:

```bash
pip install acoustid mutagen fuzzywuzzy[speedup] tqdm
```
    acoustid: For audio fingerprinting and AcoustID API interaction.
    mutagen: For reading and writing audio metadata.
    fuzzywuzzy: For fuzzy string matching in metadata comparison.
    python-Levenshtein: Installed with [speedup] option for faster fuzzy matching.
    tqdm: For displaying progress bars.

System Dependencies

Install the following system dependencies:
On Debian/Ubuntu-based systems:

```bash

sudo apt-get update
sudo apt-get install ffmpeg libchromaprint-tools
```
    ffmpeg: Provides audio decoding capabilities required by some audio processing libraries.
    libchromaprint-tools: Provides fpcalc, required by AcoustID for fingerprinting.

On macOS using Homebrew:

```bash

brew install ffmpeg chromaprint
```
Configuration
Obtain an AcoustID API Key

To use the audio fingerprinting feature, you need an AcoustID API key:

    Register for a free API key at AcoustID API Key Registration.
    The script will prompt you for the API key on the first run and store it in config.json.

Configure Settings

The script uses a configuration file config.json to store settings:

    Fuzzy Match Threshold: Determines how closely metadata must match to be considered duplicates (default is 90).
    Batch Size: Number of files processed in each batch (default is 1000).

These settings can be modified directly in config.json or will be prompted during the first run if not present.

Example config.json:

```json

{
    "acoustid_api_key": "YOUR_API_KEY_HERE",
    "fuzzy_threshold": 90,
    "batch_size": 1000
}
```
Usage
Running the Script

Basic command structure:

```bash

python3 music_deduplicate.py --path "/path/to/music" --action ACTION [options]
```
Command-Line Options

    -p, --path: (Required) Path to the music directory to scan.
    -a, --action: (Required) Action to take on duplicates. Choices are:
        list: List duplicates without making any changes.
        move: Move duplicates to a specified directory.
        delete: Delete duplicate files permanently.
    -m, --move-dir: (Required if action is 'move') Directory to move duplicates to.
    -v, --verbose: Enable verbose output with processing speed and progress bars.
    --log-level: Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default is INFO.
    --no-multiprocessing: Disable multiprocessing for debugging purposes.

Examples
List Duplicates with Progress Bar

```bash

python3 music_deduplicate.py --path "/media/music/Organised" --action list --verbose
```
Move Duplicates to a Directory

```bash

python3 music_deduplicate.py --path "/media/music/Organised" --action move --move-dir "/media/music/Duplicates" --verbose
```
Delete Duplicates with Detailed Logging

```bash

python3 music_deduplicate.py --path "/media/music/Organised" --action delete --verbose --log-level DEBUG
```
Adjusting Batch Size

You can adjust the batch size by modifying the batch_size parameter in the config.json file.

```json

{
    "batch_size": 500
}
```
Disabling Multiprocessing

If you encounter issues with multiprocessing or are debugging, you can disable it:

```bash

python3 music_deduplicate.py --path "/media/music/Organised" --action list --no-multiprocessing --verbose
```
How It Works

    File Scanning: The script recursively scans the specified music directory for supported audio file formats (.mp3, .flac, .ogg, .wav, .m4a, .aac).

    Metadata Extraction: For each file, it extracts metadata such as artist, title, album, and track number using mutagen.

    Metadata Grouping: Files are grouped based on normalized metadata to identify potential duplicates quickly.

    Audio Fingerprinting: It generates an audio fingerprint using fpcalc and retrieves an AcoustID recording ID for potential duplicates.

    Duplicate Detection:
        AcoustID Matching: If an AcoustID is available, it uses the recording ID for exact duplicate matching.
        Metadata Fuzzy Matching: Uses fuzzy matching on metadata fields to identify potential duplicates.

    Action Execution: Based on the specified action (list, move, delete), the script processes the identified duplicates accordingly.

    Caching: The script caches metadata and AcoustID results to file_cache.json to improve performance on subsequent runs.

    Logging and Progress Reporting: Detailed logs are recorded in music_deduplicate.log, and progress bars are displayed when --verbose is enabled.

Logging

    Log File: Logs are saved to music_deduplicate.log in the script's directory.
    Log Levels: Configurable via --log-level. Levels include DEBUG, INFO, WARNING, ERROR, and CRITICAL.

Example command to set log level to DEBUG:

```bash

python3 music_deduplicate.py --path "/media/music/Organised" --action list --log-level DEBUG
```
Limitations and Considerations

    AcoustID API Rate Limits: Be mindful of AcoustID API usage limits when processing large music libraries.
    System Resources: Multiprocessing can consume significant CPU and memory resources. Adjust batch_size and consider disabling multiprocessing if needed.
    Metadata Dependence: Accurate metadata enhances duplicate detection efficiency.
    File Permissions: Ensure the script has the necessary read/write permissions for all files and directories involved.
    Backups: Always back up your music library before performing operations that modify or delete files.

Troubleshooting

    Too Many Open Files Error:
        Increase the open file limit.
        Reduce the batch_size.
    Missing Dependencies:
        Verify that all Python libraries and system dependencies are correctly installed.
    AcoustID Lookup Failures:
        Ensure you have a valid AcoustID API key.
        Check your internet connection.
        Some files may be corrupt or unsupported; consider replacing them.
    Multiprocessing Issues:
        Use --no-multiprocessing to disable multiprocessing for debugging.

Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.
License

This project is licensed under the MIT License.
Acknowledgments

    AcoustID: For providing an open-source audio identification service.
    Mutagen: For the powerful audio metadata handling library.
    FuzzyWuzzy: For the fuzzy string matching library.
    tqdm: For providing a simple and flexible progress bar utility.

Contact

For any questions or support, please open an issue on the GitHub repository.

Note: Always ensure you have backups of your music library before performing operations that modify or delete files.
