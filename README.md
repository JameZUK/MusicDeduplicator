# Music Deduplication Tool

## Overview

The **Music Deduplication Tool** is a Python script designed to help you manage and clean up your music library by identifying and handling duplicate audio files. It scans your music directories, detects duplicates using metadata analysis and audio fingerprinting with AcoustID, and allows you to either list, move, or delete the duplicates based on your preference.

## Features

- **Metadata Analysis with Fuzzy Matching**: Quickly identifies potential duplicates by comparing metadata (artist, title, album) using fuzzy string matching.
- **Audio Fingerprinting with AcoustID**: Utilizes AcoustID and the Chromaprint library to accurately identify audio duplicates, even if file metadata differs or is missing.
- **Batch Processing**: Processes directories in configurable batches (default 1000) to optimize resource usage and prevent system overload.
- **Multiprocessing Support**: Uses a process pool (capped at 2 workers to respect API rate limits) to speed up directory scanning. Can be disabled with `--no-multiprocessing`.
- **Progress Bar**: Displays real-time progress bars using `tqdm` when `--verbose` is enabled.
- **Caching Mechanism**: Caches file metadata and AcoustID fingerprints in a local SQLite database (`file_cache.db`) to improve performance on subsequent runs.
- **Customizable Actions**: Supports listing, moving, or deleting duplicates based on user selection.
- **Logging Functionality**: Detailed logging with configurable log levels, stored in `music_deduplicate.log`.
- **Configurable Parameters**: Batch size, fuzzy match threshold, and other settings are configurable via `config.json`.
- **Dry Run Mode**: Test what would happen without modifying any files using `--dry-run`.
- **Safety Confirmation**: Destructive `delete` action requires confirmation (bypass with `--yes`).

## Installation

### Prerequisites

- **Python 3.6 or higher**
- **pip** (Python package installer)

### Required Python Libraries

Install the required Python libraries using pip:

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install acoustid mutagen fuzzywuzzy[speedup] tqdm pyacoustid ratelimit
```

- **acoustid**: For audio fingerprinting and AcoustID API interaction.
- **mutagen**: For reading and writing audio metadata.
- **fuzzywuzzy**: For fuzzy string matching in metadata comparison.
- **python-Levenshtein**: Installed with `[speedup]` option for faster fuzzy matching.
- **tqdm**: For displaying progress bars.
- **ratelimit**: For rate limiting AcoustID API calls.

### System Dependencies

Install the following system dependencies:

On Debian/Ubuntu-based systems:

```bash
sudo apt-get update
sudo apt-get install ffmpeg libchromaprint-tools
```

- **ffmpeg**: Provides audio decoding capabilities required by some audio processing libraries.
- **libchromaprint-tools**: Provides `fpcalc`, required by AcoustID for fingerprinting.

On macOS using Homebrew:

```bash
brew install ffmpeg chromaprint
```

## Configuration

### Obtain an AcoustID API Key

To use the audio fingerprinting feature, you need an AcoustID API key:

1. Register for a free API key at AcoustID API Key Registration.
2. The script will prompt you for the API key on the first run and store it in `config.json`.

### Configure Settings

The script uses a configuration file `config.json` to store settings:

- **Fuzzy Match Threshold**: Determines how closely metadata must match to be considered duplicates (default is 90).
- **Batch Size**: Number of directories processed in each batch (default is 1000).
- **Supported Extensions**: Audio file formats to scan (default: `.mp3`, `.flac`, `.ogg`, `.wav`, `.m4a`, `.aac`).

These settings can be modified directly in `config.json` or will be prompted during the first run if not present.

Example `config.json`:

```json
{
    "acoustid_api_key": "YOUR_API_KEY_HERE",
    "fuzzy_threshold": 90,
    "batch_size": 1000,
    "supported_extensions": [".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac"]
}
```

## Usage

### Running the Script

Basic command structure:

```bash
python3 musicorganise.py --path "/path/to/music" --action ACTION [options]
```

### Command-Line Options

- `-p, --path`: (Required) Path to the music directory to scan.
- `-a, --action`: (Required) Action to take on duplicates. Choices are:
  - `list`: List duplicates without making any changes.
  - `move`: Move duplicates to a specified directory.
  - `delete`: Delete duplicate files permanently.
- `-m, --move-dir`: (Required if action is `move`) Directory to move duplicates to.
- `-v, --verbose`: Enable verbose output with progress bars.
- `-y, --yes`: Skip confirmation prompt for destructive actions.
- `--log-level`: Set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Default is `INFO`.
- `--no-multiprocessing`: Disable multiprocessing for debugging purposes.
- `--dry-run`: Perform a test run without modifying any files.
- `--clear-cache`: Clear the cache database before running.

### Examples

List duplicates with progress bar:

```bash
python3 musicorganise.py --path "/media/music/Organised" --action list --verbose
```

Move duplicates to a directory:

```bash
python3 musicorganise.py --path "/media/music/Organised" --action move --move-dir "/media/music/Duplicates" --verbose
```

Delete duplicates with detailed logging:

```bash
python3 musicorganise.py --path "/media/music/Organised" --action delete --verbose --log-level DEBUG
```

Dry run (preview what would happen):

```bash
python3 musicorganise.py --path "/media/music/Organised" --action delete --dry-run --verbose
```

Disabling multiprocessing:

```bash
python3 musicorganise.py --path "/media/music/Organised" --action list --no-multiprocessing --verbose
```

Adjusting batch size via `config.json`:

```json
{
    "batch_size": 500
}
```

## How It Works

1. **File Scanning**: The script recursively scans the specified music directory for supported audio file formats (`.mp3`, `.flac`, `.ogg`, `.wav`, `.m4a`, `.aac`).

2. **Metadata Extraction**: For each file, it extracts metadata such as artist, title, album, and track number using `mutagen`.

3. **Audio Fingerprinting**: It generates an audio fingerprint using `fpcalc` and retrieves an AcoustID recording ID via the AcoustID API.

4. **Directory Hashing**: Each directory's contents are hashed using AcoustID recording IDs (with metadata as a fallback). Directories with identical hashes are flagged as duplicates.

5. **Duplicate Resolution**:
   - **Inter-directory**: The best directory is kept (prioritizing FLAC files, then largest total size). Other directories are listed, moved, or deleted.
   - **Intra-directory**: Within the kept directory, files with the same AcoustID are identified and resolved (keeping the highest quality format).

6. **Caching**: The script caches metadata and AcoustID results in a local SQLite database (`file_cache.db`) to improve performance on subsequent runs. Cache entries are validated against file modification times.

7. **Logging and Progress**: Detailed logs are recorded in `music_deduplicate.log`, and progress bars are displayed when `--verbose` is enabled.

## Logging

- **Log File**: Logs are saved to `music_deduplicate.log` in the script's directory.
- **Log Levels**: Configurable via `--log-level`. Levels include `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`.

Example command to set log level to DEBUG:

```bash
python3 musicorganise.py --path "/media/music/Organised" --action list --log-level DEBUG
```

## Limitations and Considerations

- **AcoustID API Rate Limits**: API calls are rate-limited to 3 per second per process. Be mindful of usage when processing large music libraries.
- **System Resources**: Multiprocessing can consume significant CPU and memory resources. Adjust `batch_size` and consider disabling multiprocessing if needed.
- **Metadata Dependence**: Accurate metadata enhances duplicate detection efficiency.
- **File Permissions**: Ensure the script has the necessary read/write permissions for all files and directories involved.
- **Backups**: Always back up your music library before performing operations that modify or delete files.

## Troubleshooting

- **Too Many Open Files Error**:
  - Increase the open file limit.
  - Reduce the `batch_size`.
- **Missing Dependencies**:
  - Verify that all Python libraries and system dependencies are correctly installed.
  - Run `pip install -r requirements.txt` to install all Python dependencies.
- **AcoustID Lookup Failures**:
  - Ensure you have a valid AcoustID API key.
  - Check your internet connection.
  - Some files may be corrupt or unsupported; consider replacing them.
- **Multiprocessing Issues**:
  - Use `--no-multiprocessing` to disable multiprocessing for debugging.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

## License

This project is licensed under the MIT License.

## Acknowledgments

- **AcoustID**: For providing an open-source audio identification service.
- **Mutagen**: For the powerful audio metadata handling library.
- **FuzzyWuzzy**: For the fuzzy string matching library.
- **tqdm**: For providing a simple and flexible progress bar utility.

## Contact

For any questions or support, please open an issue on the GitHub repository.

**Note**: Always ensure you have backups of your music library before performing operations that modify or delete files.
