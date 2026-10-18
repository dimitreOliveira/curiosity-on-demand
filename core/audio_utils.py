import logging
import re
import struct
import wave
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# Official point-in-time inline vocal tags supported by Gemini 3.8 TTS (enclosed in <...>)
VALID_INLINE_AUDIO_TAGS: frozenset[str] = frozenset(
    {
        "argh",
        "breath",
        "heavy breath",
        "exhales",
        "cackle",
        "cheer",
        "chuckle",
        "chuckles",
        "cough",
        "cry",
        "gasp",
        "giggle",
        "groan",
        "growl",
        "grunt",
        "grr",
        "hiss",
        "laugh",
        "laughter",
        "moan",
        "pant",
        "pff",
        "phew",
        "scream",
        "shout",
        "shriek",
        "sigh",
        "sighs",
        "sneeze",
        "snicker",
        "snort",
        "sob",
        "throat-clearing",
        "tsk",
        "whimper",
        "whispers",
        "whispering",
        "yawn",
        "short pause",
        "long pause",
    }
)

# Mapping of common LLM-generated or legacy tag variants to canonical Gemini 3.8 TTS inline tags
INLINE_AUDIO_TAG_ALIASES: dict[str, str] = {
    "pause": "short pause",
    "brief pause": "short pause",
    "slight pause": "short pause",
    "quick pause": "short pause",
    "beat": "short pause",
    "short beat": "short pause",
    "hesitation": "short pause",
    "hesitates": "short pause",
    "dramatic pause": "long pause",
    "long beat": "long pause",
    "extended pause": "long pause",
    "pregnant pause": "long pause",
    "deep pause": "long pause",
    "clears throat": "throat-clearing",
    "clear throat": "throat-clearing",
    "throat clearing": "throat-clearing",
    "ahem": "throat-clearing",
    "whisper": "whispers",
    "whispered": "whispers",
    "hushed": "whispers",
    "deep breath": "heavy breath",
    "sharp breath": "heavy breath",
    "big breath": "heavy breath",
    "inhale": "breath",
    "inhales": "breath",
    "breathes in": "breath",
    "takes a breath": "breath",
    "exhale": "exhales",
    "breathes out": "exhales",
    "laughs": "laugh",
    "laughing": "laugh",
    "chuckling": "chuckles",
    "gasps": "gasp",
    "gasping": "gasp",
    "sighing": "sigh",
    "coughs": "cough",
    "coughing": "cough",
    "groans": "groan",
    "groaning": "groan",
    "grunts": "grunt",
    "grunting": "grunt",
    "yawns": "yawn",
    "yawning": "yawn",
    "giggles": "giggle",
    "giggling": "giggle",
    "snickers": "snicker",
    "snickering": "snicker",
    "sobs": "sob",
    "sobbing": "sob",
    "cries": "cry",
    "crying": "cry",
    "screams": "scream",
    "screaming": "scream",
    "shouts": "shout",
    "shouting": "shout",
    "shrieks": "shriek",
    "shrieking": "shriek",
    "pants": "pant",
    "breathless": "pant",
    "out of breath": "pant",
}

_INLINE_TAG_PATTERN = re.compile(r"\[([^\[\]]+)\]|<([a-zA-Z][a-zA-Z\s\-_]*)>")


def normalize_inline_audio_tags(text: str) -> str:
    """Normalize inline TTS tags to Gemini 3.8 TTS angle-bracket format (<...>).

    Converts valid vocal events and pause aliases (whether in `[...]` or `<...>`)
    to canonical `<...>` tags (e.g. `[dramatic pause]` -> `<long pause>`,
    `[pause]` -> `<short pause>`, `[gasp]` -> `<gasp>`), and strips unsupported
    inline stage directions (e.g. `[excitedly]`, `[curious]`) so the TTS model
    does not read them aloud.
    """
    if not text:
        return ""

    def _replace_tag(match: re.Match[str]) -> str:
        raw_tag = (match.group(1) or match.group(2) or "").strip().lower()
        raw_tag = re.sub(r"\s+", " ", raw_tag)
        if raw_tag in VALID_INLINE_AUDIO_TAGS:
            return f"<{raw_tag}>"
        if raw_tag in INLINE_AUDIO_TAG_ALIASES:
            return f"<{INLINE_AUDIO_TAG_ALIASES[raw_tag]}>"
        return ""

    normalized = _INLINE_TAG_PATTERN.sub(_replace_tag, text)
    # Clean up redundant spaces while preserving intentional newlines
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" +([,.;:!?])", r"\1", normalized)
    return normalized.strip()


def parse_audio_mime_type(mime_type: str | None = None) -> dict[str, int]:
    """Parses bits per sample and rate from an audio MIME type string.

    Assumes bits per sample is encoded like "L16" and rate as "rate=xxxxx".

    Args:
        mime_type: The audio MIME type string (e.g., "audio/L16;rate=24000").

    Returns:
        A dictionary with "bits_per_sample" and "rate" keys.
    """
    bits_per_sample = 16
    rate = 24000

    if not mime_type:
        return {"bits_per_sample": bits_per_sample, "rate": rate}

    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass
        elif param.lower().startswith("audio/l"):
            try:
                sub = param[7:]
                num_str = "".join(c for c in sub if c.isdigit())
                if num_str:
                    bits_per_sample = int(num_str)
            except (ValueError, IndexError):
                pass

    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str = "audio/L16;rate=24000") -> bytes:
    """Generates a standard RIFF WAV file header for raw PCM audio data.

    If the audio_data already begins with 'RIFF', it is returned unchanged.

    Args:
        audio_data: The raw PCM audio bytes.
        mime_type: MIME type describing the audio data format and sample rate.

    Returns:
        Bytes with proper RIFF WAV header prepended to audio data.
    """
    if audio_data.startswith(b"RIFF") and len(audio_data) >= 44:
        return audio_data

    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters.get("bits_per_sample") or 16
    sample_rate = parameters.get("rate") or 24000
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + audio_data


def get_wav_duration(file_path: Path | str) -> float:
    """Calculate the exact playback duration in seconds for a WAV audio file.

    Args:
        file_path: Path to the WAV audio file.

    Returns:
        Duration in seconds as a float.
    """
    path = Path(file_path)
    if not path.exists() or path.stat().st_size <= 44:
        return 0.0

    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return round(frames / float(rate), 3)
    except (OSError, wave.Error) as err:
        logger.warning("Could not read WAV duration from %s: %s", path, err)

    return 0.0


def combine_wav_files(
    input_paths: Sequence[Path | str], output_path: Path | str
) -> Path:
    """Concatenate multiple WAV audio files into a single continuous master WAV file.

    Args:
        input_paths: List of file paths to input WAV clips in playback order.
        output_path: Destination path for the concatenated master WAV.

    Returns:
        Resolved Path to the concatenated output file.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    valid_paths = [
        Path(p) for p in input_paths if Path(p).exists() and Path(p).stat().st_size > 44
    ]
    if not valid_paths:
        raise ValueError("No valid input WAV files provided for concatenation")

    if len(valid_paths) == 1:
        out_p.write_bytes(valid_paths[0].read_bytes())
        return out_p

    first = valid_paths[0]
    with wave.open(str(first), "rb") as w_in:
        params = w_in.getparams()

    with wave.open(str(out_p), "wb") as w_out:
        w_out.setparams(params)
        for p in valid_paths:
            with wave.open(str(p), "rb") as w_in:
                w_out.writeframes(w_in.readframes(w_in.getnframes()))

    return out_p


def format_duration(seconds: float) -> str:
    """Format duration in seconds into a human-readable string (e.g. '3m 00s' or '1h 05m 20s').

    Args:
        seconds: Total duration in seconds.

    Returns:
        Formatted string representation.
    """
    total_seconds = max(0, round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"
