# Example Python script showing how to use the transcription functions
# This demonstrates how to integrate the transcription tool into other Python projects

import sys
from pathlib import Path
from transcribe_batch import load_whisper, transcribe_with_feedback, write_artifacts, summarize_text, ensure_dirs


def transcribe_single_file(
    video_path: str,
    output_dir: str,
    model_size: str = "large-v3",
    language: str = "auto",
    compute_type: str = "int8",
    beam_size: int = 5,
    do_summary: bool = True,
):
    """
    Transcribe a single video file using the transcription functions.

    Args:
        video_path: Path to the input video file
        output_dir: Directory to save outputs
        model_size: Whisper model size
        language: Language code or 'auto'
        compute_type: Computation type for optimization
        beam_size: Beam size for decoding
        do_summary: Whether to generate AI summary

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Setup paths
        video_path = Path(video_path)
        output_path = Path(output_dir) / video_path.stem
        ensure_dirs(output_path)

        # Load model
        print(f"Loading Whisper model: {model_size}")
        model = load_whisper(model_size, compute_type)

        # Transcribe
        print(f"Transcribing: {video_path.name}")
        segments, full_text, info = transcribe_with_feedback(
            model=model,
            media_path=video_path,
            language=None if language == "auto" else language,
            beam_size=beam_size,
            progress_timeout=180,
        )

        print(f"Detected language: {info.language}")
        print(f"Duration: {info.duration:.1f} seconds")

        # Write outputs
        write_artifacts(
            out_dir=output_path,
            segments=segments,
            full_text=full_text,
            stem=video_path.stem,
            do_summary=do_summary,
            summary_max=8,
        )

        print(f"✅ Successfully processed: {video_path.name}")
        print(f"📁 Outputs saved to: {output_path}")

        return True

    except Exception as e:
        print(f"❌ Error processing {video_path}: {e}")
        return False


def batch_transcribe_directory(input_dir: str, output_dir: str, **kwargs):
    """
    Transcribe all MP4 files in a directory.

    Args:
        input_dir: Directory containing MP4 files
        output_dir: Directory to save outputs
        **kwargs: Additional arguments for transcribe_single_file
    """
    input_path = Path(input_dir)
    mp4_files = list(input_path.glob("*.mp4"))

    if not mp4_files:
        print(f"No MP4 files found in {input_path}")
        return

    print(f"Found {len(mp4_files)} MP4 files")

    successful = 0
    failed = 0

    for video_file in mp4_files:
        if transcribe_single_file(str(video_file), output_dir, **kwargs):
            successful += 1
        else:
            failed += 1

    print(f"\n📊 Results: {successful} successful, {failed} failed")


# Example usage
if __name__ == "__main__":
    # Example 1: Transcribe a single file
    if len(sys.argv) >= 3:
        video_file = sys.argv[1]
        output_directory = sys.argv[2]

        success = transcribe_single_file(
            video_path=video_file,
            output_dir=output_directory,
            model_size="medium",  # Use medium model for balance
            language="auto",
            do_summary=True,
        )

        if success:
            print("🎉 Transcription completed successfully!")
        else:
            print("💥 Transcription failed!")
            sys.exit(1)

    else:
        print("Usage examples:")
        print("1. Single file: python examples/python_integration.py input.mp4 outputs/")
        print("2. Batch directory: modify the script to call batch_transcribe_directory()")
        print("")
        print("Example for batch processing:")
    print('batch_transcribe_directory("input_mp4", "outputs", model_size="small", language="en")')
