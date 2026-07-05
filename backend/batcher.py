"""
Batcher Module
Groups subtitle blocks into batches for efficient LLM processing.
Batch size is calculated automatically based on total line count.
"""

import logging

from srt_parser import SubtitleBlock

logger = logging.getLogger(__name__)


def calculate_batch_size(line_count: int) -> int:
    """
    Calculate optimal batch size based on total number of subtitle lines.

    Tiered strategy:
        1–100     → batch size 20
        101–300   → batch size 25
        301–600   → batch size 35
        601–1000  → batch size 45
        1000+     → batch size 50

    Args:
        line_count: Total number of subtitle lines to process.

    Returns:
        Calculated batch size.
    """
    if line_count <= 100:
        return 20
    elif line_count <= 300:
        return 25
    elif line_count <= 600:
        return 35
    elif line_count <= 1000:
        return 45
    else:
        return 50


def create_batches(blocks: list[SubtitleBlock]) -> list[list[SubtitleBlock]]:
    """
    Split subtitle blocks into batches using auto-calculated batch size.

    Args:
        blocks: List of SubtitleBlock objects to batch.

    Returns:
        List of batches, where each batch is a list of SubtitleBlock objects.
        Order is preserved — batch 0 contains the first N blocks, etc.
    """
    line_count = len(blocks)
    batch_size = calculate_batch_size(line_count)

    logger.info(f"Auto-batch: {line_count} lines → batch size {batch_size}")

    batches: list[list[SubtitleBlock]] = []
    for i in range(0, len(blocks), batch_size):
        batches.append(blocks[i : i + batch_size])

    return batches
