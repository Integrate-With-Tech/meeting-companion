#!/usr/bin/env python3
"""
Setup script for Video Transcription Tool
Enables pip installation and global command availability
"""

from setuptools import setup
import sys
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements = [
    "faster-whisper>=0.10.0",
    "transformers>=4.21.0",
    "sentencepiece>=0.1.99",
    "torch>=1.13.0",
]

dev_requirements = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "flake8>=5.0.0",
    "black>=22.0.0",
    "mypy>=0.991",
]

# Check Python version
if sys.version_info < (3, 8):
    print("Error: Python 3.8 or higher is required")
    sys.exit(1)

setup(
    name="video-transcription-tool",
    version="1.0.0",
    description="Batch video transcription with AI-powered summarization using Whisper and BART",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Sejal Sheth",
    author_email="integratewithtech@gmail.com",
    url="https://github.com/sejalsheth/integrate-with-tech",
    # Package configuration
    py_modules=["transcribe_batch"],
    python_requires=">=3.8",
    # Dependencies
    install_requires=requirements,
    extras_require={
        "dev": dev_requirements,
        "test": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
    },
    # Console scripts
    entry_points={
        "console_scripts": [
            "video-transcribe=transcribe_batch:main",
        ],
    },
    # Classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Video",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Text Processing :: Linguistic",
    ],
    # Keywords
    keywords=[
        "video",
        "transcription",
        "whisper",
        "ai",
        "speech-to-text",
        "summarization",
        "bart",
        "machine-learning",
        "nlp",
        "console",
    ],
    # Project URLs
    project_urls={
        "Homepage": "https://github.com/sejalsheth/integrate-with-tech",
        "Repository": "https://github.com/sejalsheth/integrate-with-tech.git",
        "Issues": "https://github.com/sejalsheth/integrate-with-tech/issues",
        "Documentation": "https://github.com/sejalsheth/integrate-with-tech/blob/main/video-transcribe/README.md",
    },
    # Package data
    include_package_data=True,
    zip_safe=False,
)
