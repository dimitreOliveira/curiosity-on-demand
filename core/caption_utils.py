"""Synchronized subtitle (.srt) generation utilities for Curiosity On Demand."""

import logging
import re
from pathlib import Path

from core.models import AnimationStoryboard, NarrationStoryboard, Script

logger = logging.getLogger(__name__)


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SubRip (SRT) timestamp format HH:MM:SS,mmm.

    Args:
        seconds: Time offset in seconds.

    Returns:
        Formatted timestamp string (e.g. '00:01:23,450').
    """
    clamped = max(0.0, float(seconds))
    total_ms = round(clamped * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, millis = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def strip_audio_tags(text: str) -> str:
    """Remove inline directorial audio tags (e.g. <short pause>, <gasp>, [whispers]) from narration text."""
    if not text:
        return ""
    cleaned = re.sub(r"\[[^\]]+\]|<[^<>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r" +([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def split_text_into_caption_cues(
    text: str,
    max_words_per_cue: int = 12,
    max_chars_per_line: int = 42,
) -> list[str]:
    """Break a scene's spoken narration into readable, television-grade caption cues.

    Each cue has at most `max_words_per_cue` words and is wrapped up to 2 lines
    bounded by `max_chars_per_line` characters per line.
    """
    clean_text = strip_audio_tags(text)
    if not clean_text:
        return []

    # First split on sentence boundaries (. ! ? ;)
    raw_sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if s and s.strip()
    ]
    if not raw_sentences:
        raw_sentences = [clean_text]

    raw_cues: list[str] = []
    for sentence in raw_sentences:
        words = sentence.split()
        if len(words) <= max_words_per_cue:
            raw_cues.append(sentence)
            continue

        # Split longer sentences at clause punctuation (, — : ;) if possible, else by word budget
        clauses = [
            c.strip() for c in re.split(r"(?<=[,;—–:])\s+", sentence) if c and c.strip()
        ]
        current_words: list[str] = []
        for clause in clauses:
            clause_words = clause.split()
            if len(current_words) + len(clause_words) <= max_words_per_cue:
                current_words.extend(clause_words)
            else:
                if current_words:
                    raw_cues.append(" ".join(current_words))
                    current_words = []
                if len(clause_words) <= max_words_per_cue:
                    current_words.extend(clause_words)
                else:
                    for i in range(0, len(clause_words), max_words_per_cue):
                        chunk = clause_words[i : i + max_words_per_cue]
                        if i + max_words_per_cue < len(clause_words):
                            raw_cues.append(" ".join(chunk))
                        else:
                            current_words.extend(chunk)
        if current_words:
            raw_cues.append(" ".join(current_words))

    # Format each cue to wrap cleanly onto at most two balanced lines if exceeding max_chars_per_line
    formatted_cues: list[str] = []
    for cue in raw_cues:
        if len(cue) <= max_chars_per_line:
            formatted_cues.append(cue)
            continue

        words = cue.split()
        if len(words) < 2:
            formatted_cues.append(cue)
            continue

        # Find split point closest to middle by character count
        mid_char = len(cue) / 2.0
        best_idx = 1
        best_diff = float("inf")
        running_len = 0
        for idx in range(1, len(words)):
            running_len += len(words[idx - 1]) + (1 if idx > 1 else 0)
            diff = abs(running_len - mid_char)
            if diff < best_diff:
                best_diff = diff
                best_idx = idx

        line_1 = " ".join(words[:best_idx])
        line_2 = " ".join(words[best_idx:])
        formatted_cues.append(f"{line_1}\n{line_2}")

    return formatted_cues


def generate_srt_content(
    script: Script,
    narration_storyboard: NarrationStoryboard | None = None,
    animation_storyboard: AnimationStoryboard | None = None,
    max_words_per_cue: int = 12,
) -> str:
    """Generate a complete SubRip (.srt) subtitle document synchronized to scene durations.

    Scene durations are resolved in priority order:
    1. Exact synthesized `SceneAudio.duration_seconds` from `narration_storyboard`
    2. Rendered `SceneAnimation.duration_seconds` from `animation_storyboard`
    3. Estimated `ScriptScene.duration_seconds` from `script`

    Within each scene, cue timings are allocated proportionally to word count.
    """
    if not script or not script.scenes:
        return ""

    audio_durations: dict[int, float] = {}
    if narration_storyboard and narration_storyboard.scenes_audio:
        for sa in narration_storyboard.scenes_audio:
            if sa.duration_seconds and sa.duration_seconds > 0:
                audio_durations[sa.scene_number] = float(sa.duration_seconds)

    anim_durations: dict[int, float] = {}
    if animation_storyboard and animation_storyboard.scenes:
        for anim in animation_storyboard.scenes:
            if anim.duration_seconds and anim.duration_seconds > 0:
                anim_durations[anim.scene_number] = float(anim.duration_seconds)

    srt_blocks: list[str] = []
    cue_index = 1
    elapsed_seconds = 0.0

    for scene in script.scenes:
        scene_num = scene.scene_number
        scene_duration = (
            audio_durations.get(scene_num)
            or anim_durations.get(scene_num)
            or float(max(1, scene.duration_seconds))
        )

        cues = split_text_into_caption_cues(
            scene.narration,
            max_words_per_cue=max_words_per_cue,
        )
        if not cues:
            elapsed_seconds += scene_duration
            continue

        word_counts = [max(1, len(c.split())) for c in cues]
        total_words = sum(word_counts)

        scene_cursor = elapsed_seconds
        for idx, (cue_text, wc) in enumerate(zip(cues, word_counts, strict=True)):
            start_time = scene_cursor
            if idx == len(cues) - 1:
                end_time = elapsed_seconds + scene_duration
            else:
                cue_dur = scene_duration * (wc / float(total_words))
                end_time = start_time + cue_dur
            scene_cursor = end_time

            start_ts = format_srt_timestamp(start_time)
            end_ts = format_srt_timestamp(max(start_time + 0.1, end_time))

            srt_blocks.append(f"{cue_index}\n{start_ts} --> {end_ts}\n{cue_text}")
            cue_index += 1

        elapsed_seconds += scene_duration

    if not srt_blocks:
        return ""

    return "\n\n".join(srt_blocks) + "\n"


def save_srt_subtitles(
    output_path: Path | str,
    script: Script,
    narration_storyboard: NarrationStoryboard | None = None,
    animation_storyboard: AnimationStoryboard | None = None,
) -> Path:
    """Generate and write a synchronized .srt subtitle file to disk."""
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    srt_content = generate_srt_content(
        script=script,
        narration_storyboard=narration_storyboard,
        animation_storyboard=animation_storyboard,
    )
    out_p.write_text(srt_content, encoding="utf-8")
    logger.info(
        "Generated synchronized SRT subtitles at %s (%d bytes)",
        out_p,
        len(srt_content.encode("utf-8")),
    )
    return out_p
