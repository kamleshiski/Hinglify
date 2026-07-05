"""
SRT Parser & Writer Module
Handles parsing .srt subtitle files into structured data and
reassembling them back into valid .srt format.
"""

import re
from dataclasses import dataclass, field


@dataclass
class SubtitleBlock:
    """Represents a single subtitle entry in an SRT file."""
    index: int
    start_time: str
    end_time: str
    text: str
    # After conversion, this holds the Hinglish text
    converted_text: str = ""
    # Flag if this block had a conversion warning
    warning: str = ""


# Regex for SRT timestamp line: 00:01:23,456 --> 00:01:25,789
TIMESTAMP_PATTERN = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})$"
)


def parse_srt(content: str) -> list[SubtitleBlock]:
    """
    Parse raw SRT file content into a list of SubtitleBlock objects.

    Handles:
    - BOM (byte order mark) stripping
    - \\r\\n and \\r normalization to \\n
    - Flexible whitespace between blocks

    Raises ValueError with a descriptive message if the file is malformed.
    """
    # Strip BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]

    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    blocks: list[SubtitleBlock] = []
    # Split into blocks separated by one or more blank lines
    raw_blocks = re.split(r"\n\n+", content.strip())

    if not raw_blocks or (len(raw_blocks) == 1 and not raw_blocks[0].strip()):
        raise ValueError("The uploaded file appears to be empty or contains no subtitle blocks.")

    for i, raw_block in enumerate(raw_blocks):
        lines = raw_block.strip().split("\n")

        if len(lines) < 2:
            raise ValueError(
                f"Malformed subtitle block near position {i + 1}: "
                f"expected at least an index, timestamp, and text line. "
                f"Got: {repr(raw_block[:100])}"
            )

        # Line 1: Index (should be a number)
        index_line = lines[0].strip()
        if not index_line.isdigit():
            raise ValueError(
                f"Expected a numeric index at block {i + 1}, "
                f"got: {repr(index_line)}"
            )
        index = int(index_line)

        # Line 2: Timestamp
        timestamp_line = lines[1].strip()
        match = TIMESTAMP_PATTERN.match(timestamp_line)
        if not match:
            raise ValueError(
                f"Invalid timestamp format at block {index}: "
                f"expected 'HH:MM:SS,mmm --> HH:MM:SS,mmm', "
                f"got: {repr(timestamp_line)}"
            )
        start_time = match.group(1)
        end_time = match.group(2)

        # Lines 3+: Subtitle text (may be multi-line)
        text_lines = lines[2:]
        text = "\n".join(text_lines).strip()

        # Text can be empty (some SRTs have blank subtitle entries)
        blocks.append(SubtitleBlock(
            index=index,
            start_time=start_time,
            end_time=end_time,
            text=text,
        ))

    if not blocks:
        raise ValueError("No valid subtitle blocks found in the file.")

    return blocks


def write_srt(blocks: list[SubtitleBlock]) -> str:
    """
    Reassemble SubtitleBlock objects into a valid .srt string.

    Uses the ORIGINAL timestamps and the converted_text (falling back
    to original text if converted_text is empty).
    """
    output_parts: list[str] = []

    for block in blocks:
        # Use converted text if available, otherwise fall back to original
        text = block.converted_text if block.converted_text else block.text

        entry = (
            f"{block.index}\n"
            f"{block.start_time} --> {block.end_time}\n"
            f"{text}\n"
        )
        output_parts.append(entry)

    # Join blocks with a blank line separator, add trailing newline
    return "\n".join(output_parts) + "\n"
