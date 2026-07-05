"""
LLM Provider Module
Handles calling Gemini API with key rotation, response parsing,
and line-count validation with auto-reconciliation.

Other providers (OpenRouter/Claude, OpenAI) are commented out
but preserved for future use.
"""

import os
import re
import json
import asyncio
import logging

# import httpx  # Commented out — used by OpenRouter (future)
from google import genai
# from openai import AsyncOpenAI  # Commented out — used by OpenAI (future)

from key_manager import key_manager

logger = logging.getLogger(__name__)

# ─── System Prompt ───────────────────────────────────────────────────────────
# This is the core prompt that drives Hindi → Hinglish conversion.
# Embedded here as a constant — used by all providers.

SYSTEM_PROMPT = """You are an expert Hinglish transliterator specializing in Indian subtitle
content (movies, web series, YouTube videos, reels). Your job is to convert
Hindi text (Devanagari script) into Hinglish — Hindi written using the
Roman/English alphabet, exactly the way young urban Indians actually type
it casually on WhatsApp, Instagram, and texting. This is NOT formal academic
transliteration (no IAST, no ITRANS, no diacritics like ā/ī/ū/ṃ).

CORE RULES:

1. CASUAL SPELLING, NOT ACADEMIC TRANSLITERATION
   - "क्या" → "kya" (not "kyā")
   - "है" → "hai"
   - "नहीं" → "nahi" or "nahin" (both acceptable, prefer "nahi" — simpler is better)
   - "हूँ" → "hoon" (not "hūṃ")
   - "मैं" → "main" (not "maiṃ")
   - Long vowels in casual texting are usually NOT doubled unless it changes
     meaning or matches common usage (e.g. "theek" not "thik", "accha" not "acha")
   - When in doubt, write it the way it would appear in a casual Instagram
     comment or WhatsApp message, not a textbook.

2. KEEP ENGLISH WORDS IN ENGLISH
   Indian Hindi speech is naturally peppered with English words. If a word
   in the source is already an English loanword being used as-is in casual
   speech (e.g. "टाइम", "फोन", "ऑफिस", "सीरियसली"), render it back in its
   normal English spelling, not phonetic Hindi-ized spelling.
   - "टाइम" → "time" (not "taim")
   - "फोन" → "phone" (not "fon")
   - "सीरियसली" → "seriously"

3. PRESERVE TONE AND REGISTER
   - Keep slang, filler words, and casual speech patterns as they are
     ("yaar", "matlab", "arre", "bas", "thoda", "bilkul") — these are part
     of how the line was actually spoken, don't formalize them.
   - Match the emotional register of the line (don't make an angry line
     sound polite, don't make a casual line sound formal).
   - Preserve exclamation marks, question marks, and emphasis as in source.

4. NUMBERS, NAMES, PROPER NOUNS
   - Keep numerals as numerals (don't spell out).
   - Proper nouns (names of people, places, brands) should be transliterated
     using their common/standard Roman spelling, not phonetic guesswork
     (e.g. "दिल्ली" → "Delhi", not "Dilli", unless context is clearly
     informal/colloquial usage where "Dilli" is intentional).

5. PUNCTUATION AND FORMATTING
   - Preserve all punctuation, line breaks within a single subtitle entry,
     and any formatting tags (like <i>, <b>) exactly as they appear.
   - Do not add or remove punctuation that changes meaning.
   - Do not translate meaning — this is transliteration (script conversion),
     NOT translation. If the line is in Hindi, output the SAME words and
     SAME meaning, just in Roman script. Do not paraphrase or "improve" it.

6. CONSISTENCY
   - Use the SAME spelling for the same Hindi word every time it appears
     in this batch (e.g. don't write "nahi" once and "nahin" later for
     the same word — pick one and stick with it for this entire job).

OUTPUT FORMAT:
Return ONLY a valid JSON object with a single key "lines" containing an array of strings, where each string is the converted Hinglish text.
Do not add explanations, notes, or commentary. Do not merge, split, omit, or reorder lines. If a line is already in English/Roman script, return it unchanged. If a line is empty, return an empty string in the array.

Example response:
{
  "lines": [
    "first converted line",
    "second converted line"
  ]
}"""


# ─── Response Parsing ─────────────────────────────────────────────────────────

def _format_input(lines: list[str]) -> str:
    """Format subtitle lines for the LLM."""
    return json.dumps({"lines": lines}, ensure_ascii=False, indent=2)


def _parse_output(response_text: str, expected_count: int) -> list[str] | None:
    """
    Parse the LLM's JSON response back into a list of strings.
    Returns None if parsing fails or line count doesn't match expected_count.
    """
    try:
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        if "lines" in data and isinstance(data["lines"], list):
            parsed = data["lines"]
        elif isinstance(data, list):
            parsed = data
        else:
            logger.warning("JSON did not contain a 'lines' array or was not an array")
            return None

        if len(parsed) != expected_count:
            logger.warning(
                f"Line count mismatch: expected {expected_count}, got {len(parsed)}"
            )
            return None

        return [str(line) for line in parsed]
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON response: {e}")
        return None


# ─── Gemini API Call ──────────────────────────────────────────────────────────

async def _call_gemini(lines: list[str], strict_count: int | None = None) -> str:
    """Call Google Gemini API using the current key from key manager."""
    api_key = key_manager.get_current_key()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=api_key)
    user_message = _format_input(lines)

    if strict_count is not None:
        user_message += f"\n\nCRITICAL: You must return EXACTLY {strict_count} lines. Count them before responding."

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=user_message,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )

    return response.text


# ─── Public API ───────────────────────────────────────────────────────────────

def _is_rate_limit_error(error_str: str) -> bool:
    """Check if an error string indicates a rate limit or quota issue."""
    indicators = ["429", "rate", "quota", "resource_exhausted", "too many requests"]
    error_lower = error_str.lower()
    return any(indicator in error_lower for indicator in indicators)


async def convert_batch(
    lines: list[str],
) -> tuple[list[str], str, bool]:
    """
    Convert a batch of Hindi subtitle lines to Hinglish using Gemini.

    Handles:
    - Key rotation on rate limit errors (silent failover)
    - Line count validation via strict JSON parsing
    - Attempt 1: Normal batch send
    - Attempt 2: Stricter prompt instruction
    - Attempt 3: Reduce batch size by half and re-split recursively
    - Graceful fallback to original text on persistent failures

    Args:
        lines: List of subtitle text strings to convert.

    Returns:
        Tuple of (converted_lines, warning_message, is_unconverted).
        - warning_message is empty on success
        - is_unconverted is True if original text was kept due to failure
    """
    expected_count = len(lines)
    if expected_count == 0:
        return [], "", False

    # Try Attempt 1 and Attempt 2 (with stricter instructions)
    for attempt in [1, 2]:
        strict_count = expected_count if attempt == 2 else None
        
        # We need a loop to handle rate limits and retryable errors within the attempt
        while True:
            try:
                response_text = await _call_gemini(lines, strict_count)
                parsed = _parse_output(response_text, expected_count)
                if parsed is not None:
                    return parsed, "", False
                
                # If parse failed (line count mismatch or invalid JSON), break to next attempt
                logger.info(
                    f"Attempt {attempt} failed validation (expected {expected_count} lines) "
                    f"for batch size {len(lines)}."
                )
                break

            except Exception as e:
                error_str = str(e)

                if _is_rate_limit_error(error_str):
                    rotated = key_manager.rotate_key()
                    if rotated:
                        logger.info("Retrying batch with rotated key...")
                        continue  # Retry same attempt
                    else:
                        logger.warning(
                            "All API keys rate limited. Waiting 60 seconds before retry..."
                        )
                        await asyncio.sleep(60)
                        key_manager.reset_keys()
                        continue  # Retry same attempt

                is_retryable = any(
                    code in error_str for code in ["500", "502", "503"]
                )

                if is_retryable:
                    wait_time = 2.0
                    logger.info(
                        f"Retryable error inside attempt {attempt}, waiting {wait_time}s: {error_str}"
                    )
                    await asyncio.sleep(wait_time)
                    continue  # Retry same attempt
                else:
                    logger.error(f"LLM API call failed with non-retryable error: {error_str}")
                    # On non-retryable, we stop attempts and fallback
                    return lines, "", True

    # Attempt 3: Reduce batch size by half and re-split
    if expected_count > 1:
        logger.info(
            f"Attempt 3: Reducing batch size by half and re-splitting {expected_count} lines..."
        )
        mid = expected_count // 2
        left_half = lines[:mid]
        right_half = lines[mid:]

        left_parsed, _, left_unconverted = await convert_batch(left_half)
        right_parsed, _, right_unconverted = await convert_batch(right_half)

        combined_parsed = left_parsed + right_parsed
        combined_unconverted = left_unconverted or right_unconverted
        return combined_parsed, "", combined_unconverted

    # If it is a batch of 1 and both attempts failed, we must keep original
    logger.warning(f"All attempts failed for single line batch. Keeping original text.")
    return lines, "", True
