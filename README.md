# OpenRocket Monte Carlo

**[English Version](README.md)**

A small Python tool to run Monte Carlo-style experiments for OpenRocket projects.

## What is in this repo
- `openrocket_montecarlo.py`: main script
- `base_rocket.ork`: sample OpenRocket design
- `OpenRocket-15.03.jar`: OpenRocket runtime (used by the script)
- `settings.json`: example settings
- `test_jpype.py`: quick JPype check

## Requirements
- Python 3.8+
- JPype
- Java (required by OpenRocket)

## Quick start
1. Ensure Java is installed and on your PATH.
2. Install Python deps:
   - `pip install jpype1`
3. Run:
   - `python openrocket_montecarlo.py`

## Notes
- Update `settings.json` to match your simulation inputs.
- The script expects the OpenRocket JAR to be present in the repo.
