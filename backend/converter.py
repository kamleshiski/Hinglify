"""
Converter Orchestrator Module
Ties together SRT parsing, batching, LLM conversion, and reassembly
into a single pipeline function.
"""

import re
import time
import logging
from typing import Callable, Awaitable

from srt_parser import SubtitleBlock, parse_srt, write_srt
from batcher import create_batches
from llm_provider import convert_batch
from key_manager import key_manager

logger = logging.getLogger(__name__)

# Regex to detect Devanagari characters (Hindi script)
DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")


def _contains_devanagari(text: str) -> bool:
    """Check if text contains any Devanagari (Hindi) characters."""
    return bool(DEVANAGARI_PATTERN.search(text))


async def convert_srt(
    content: str,
    progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict:
    """
    Full conversion pipeline: parse → batch → convert → reassemble.

    Args:
        content: Raw SRT file content as string.
        progress_callback: Async callback(batch_index, total_batches) for progress updates.

    Returns:
        Dictionary with:
        - "srt_content": Converted SRT file as string
        - "preview": List of {original, converted} dicts for first 6 lines
        - "warnings": List of warning messages
        - "stats": {total_lines, total_batches, time_seconds, ...}
        - "has_unconverted": Boolean, True if any batches fell back to original
    """
    start_time = time.time()
    warnings: list[str] = []

    # Reset key manager to primary key for this new session
    key_manager.reset_keys()

    # Step 1: Parse the SRT file
    blocks = parse_srt(content)
    total_lines = len(blocks)
    logger.info(f"Parsed {total_lines} subtitle blocks")

    # Step 2: Identify which blocks need conversion (contain Devanagari)
    # Blocks that are already in English/Roman script are passed through unchanged
    blocks_needing_conversion: list[int] = []  # indices into blocks list
    for i, block in enumerate(blocks):
        if _contains_devanagari(block.text):
            blocks_needing_conversion.append(i)
        else:
            # Already Roman script — pass through as-is
            block.converted_text = block.text

    logger.info(
        f"{len(blocks_needing_conversion)} blocks need conversion, "
        f"{total_lines - len(blocks_needing_conversion)} already in Roman script"
    )

    # Step 3: Batch only the blocks that need conversion (auto batch size)
    conversion_blocks = [blocks[i] for i in blocks_needing_conversion]
    batches = create_batches(conversion_blocks)
    total_batches = len(batches)

    logger.info(f"Created {total_batches} batches")

    # Step 4: Process each batch through the LLM
    converted_so_far = 0
    unconverted_count = 0
    first_unconverted_timestamp = None

    for batch_idx, batch in enumerate(batches):
        # Extract text from blocks for this batch
        batch_texts = [block.text for block in batch]

        # Call the LLM (uses Gemini with key rotation internally)
        converted_texts, warning, is_unconverted = await convert_batch(
            lines=batch_texts,
        )

        if is_unconverted:
            unconverted_count += len(batch)
            if not first_unconverted_timestamp and len(batch) > 0:
                first_unconverted_timestamp = batch[0].start_time

        if warning:
            warnings.append(f"Batch {batch_idx + 1}: {warning}")

        # Map converted text back to the blocks
        for block, converted_text in zip(batch, converted_texts):
            # Sanitize to prevent double newlines from breaking SRT block structure
            block.converted_text = converted_text.replace("\n\n", "\n")

        converted_so_far += len(batch)

        # Report progress
        if progress_callback:
            await progress_callback(batch_idx + 1, total_batches)

        logger.info(
            f"Batch {batch_idx + 1}/{total_batches} done "
            f"({converted_so_far}/{len(conversion_blocks)} lines)"
        )

    # Step 5: Add user-friendly notice if any batches were unconverted
    has_unconverted = unconverted_count > 0
    if has_unconverted:
        warnings.append(
            f"A few lines couldn't be converted and kept their original script. "
            f"You can download and check around [{first_unconverted_timestamp or '00:00:00,000'}]."
        )

    # Step 6: Reassemble the SRT
    srt_output = write_srt(blocks)

    # Step 6.5: Post-assembly sanity check
    try:
        output_blocks = parse_srt(srt_output)
        if len(output_blocks) != total_lines:
            # Find approximate timestamp of the first affected block
            first_affected_time = None
            first_affected_block_idx = 0
            for idx in range(min(len(blocks), len(output_blocks))):
                if blocks[idx].start_time != output_blocks[idx].start_time or blocks[idx].text != output_blocks[idx].text:
                    first_affected_time = blocks[idx].start_time
                    first_affected_block_idx = idx
                    break
            
            if not first_affected_time and len(blocks) > 0:
                first_affected_block_idx = min(len(blocks), len(output_blocks)) - 1
                first_affected_time = blocks[first_affected_block_idx].start_time

            # Map block index back to a batch number
            # batches contain blocks_needing_conversion.
            culprit_batch = "unknown"
            for b_idx, batch in enumerate(batches):
                if any(b.index == blocks[first_affected_block_idx].index for b in batch):
                    culprit_batch = str(b_idx + 1)
                    break

            logger.error(
                f"Sanity check failed: output has {len(output_blocks)} subtitle blocks, "
                f"but input had {total_lines}. Mismatch started around block {first_affected_block_idx + 1}. "
                f"Likely caused by batch index {culprit_batch}."
            )
            warn_msg = "Some subtitles may be misaligned."
            if first_affected_time:
                warn_msg = (
                    f"A few lines couldn't be converted and kept their original script. "
                    f"You can download and check around [{first_affected_time}]."
                )
            warnings.append(warn_msg)
    except Exception as e:
        logger.error(f"Failed to run post-assembly sanity check: {e}")

    # Step 7: Generate preview (first 6 converted lines)
    preview = []
    preview_count = 0
    for block in blocks:
        if preview_count >= 6:
            break
        if _contains_devanagari(block.text):
            preview.append({
                "index": block.index,
                "original": block.text,
                "converted": block.converted_text,
            })
            preview_count += 1

    elapsed = round(time.time() - start_time, 2)

    return {
        "srt_content": srt_output,
        "preview": preview,
        "warnings": warnings,
        "has_unconverted": has_unconverted,
        "stats": {
            "total_lines": total_lines,
            "lines_converted": len(blocks_needing_conversion) - unconverted_count,
            "lines_passthrough": total_lines - len(blocks_needing_conversion),
            "unconverted_count": unconverted_count,
            "total_batches": total_batches,
            "time_seconds": elapsed,
        },
    }
