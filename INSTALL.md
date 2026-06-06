# Installation Guide for Video Transcription Tool

## Quick Install

```bash
# Clone the repository
git clone <repository-url>
cd meeting-companion

# Install the package globally
pip install -e .

# Now you can use the global command:
meeting-companion --help
```

## Development Install

```bash
# Install with development dependencies
pip install -e .[dev]

# Or install from PyPI (when available)
pip install meeting-companion
```

## System Requirements

### Prerequisites

- Python 3.8 or higher
- FFmpeg (for audio processing)

### Install FFmpeg

**macOS (using Homebrew):**

```bash
brew install ffmpeg
```

**Ubuntu/Debian:**

```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html or use chocolatey:

```bash
choco install ffmpeg
```

## Usage After Installation

Once installed, you can use the global `meeting-companion` command:

### Interactive Setup

```bash
meeting-companion --interactive
```

### Quick Processing

```bash
meeting-companion run --quick --input input_mp4 --output outputs
```

### Single File Processing

```bash
meeting-companion file --input myvideo.mp4 --output results/
```

### Browse for Files

```bash
meeting-companion file --browse
```

### Configuration Management

```bash
# Show current settings
meeting-companion --show-config

# Reset to defaults
meeting-companion --reset-config

# Check dependencies
meeting-companion --check-deps
```

## Available Commands

| Command                           | Description                       |
| --------------------------------- | --------------------------------- |
| `meeting-companion --help`        | Show full help                    |
| `meeting-companion --interactive` | Interactive setup wizard          |
| `meeting-companion run`           | Batch process directory of videos |
| `meeting-companion file`          | Process single video file         |
| `meeting-companion --check-deps`  | Validate system dependencies      |
| `meeting-companion --show-config` | Display current configuration     |

## Troubleshooting

### Command not found

If `meeting-companion` command is not found after installation:

```bash
# Reinstall with pip
pip uninstall meeting-companion
pip install -e .

# Check if pip scripts directory is in PATH
python -m site --user-base
```

### Permission errors

On some systems you might need:

```bash
pip install --user -e .
```

### Virtual environment install

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
```
