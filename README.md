Usage Instructions
Install Required Libraries

Ensure you have all the necessary Python libraries installed:

bash

pip install acoustid mutagen fuzzywuzzy python-Levenshtein

    Note: You may need to install system dependencies for chromaprint (used by acoustid):

    bash

    sudo apt-get install libchromaprint-tools

Obtain an AcoustID API Key

    Get a free API key from AcoustID API Key Registration.
    The script will prompt you for the API key on the first run and store it in config.json.

Running the Script

    List duplicates:

    bash

python3 music_deduplicate.py --path "/path/to/music" --action list --verbose

Move duplicates to a directory:

bash

python3 music_deduplicate.py --path "/path/to/music" --action move --move-dir "/path/to/.Duplicates" --verbose

Delete duplicates:

bash

    python3 music_deduplicate.py --path "/path/to/music" --action delete --verbose

Additional Notes

    Fuzzy Match Threshold: You can set the fuzzy match threshold (default is 90) when prompted. This controls how strictly metadata must match for files to be considered duplicates when AcoustID is not available.
    Cache Files: The script uses config.json for configuration and file_cache.json for caching metadata and AcoustID fingerprints. These files are stored in the same directory as the script.
