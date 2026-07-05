"""
Gemini API Key Manager Module
Manages two API keys with automatic rotation on rate limit errors.
KEY_1 is always primary; KEY_2 is a fallback. Keys reset to KEY_1
at the start of each new file upload/conversion session.
"""

import os
import logging

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages Gemini API key rotation with silent failover."""

    def __init__(self):
        self._keys: list[str] = []
        self._current_index: int = 0
        self._rotation_count: int = 0  # tracks how many rotations in current cycle
        self._load_keys()

    def _load_keys(self):
        """Load API keys from environment variables on startup."""
        key1 = os.getenv("GEMINI_API_KEY_1", "").strip()
        key2 = os.getenv("GEMINI_API_KEY_2", "").strip()

        if key1:
            self._keys.append(key1)
        if key2:
            self._keys.append(key2)

        if not self._keys:
            logger.error("No Gemini API keys configured. Set GEMINI_API_KEY_1 and/or GEMINI_API_KEY_2 in .env")
        else:
            logger.info(f"Loaded {len(self._keys)} Gemini API key(s)")

    def get_current_key(self) -> str:
        """Return the currently active API key."""
        if not self._keys:
            raise RuntimeError("No Gemini API keys configured")
        return self._keys[self._current_index]

    def rotate_key(self) -> bool:
        """
        Switch to the next available key.

        Returns:
            True if successfully rotated to a different key.
            False if all keys have been exhausted in this cycle.
        """
        self._rotation_count += 1

        if self._rotation_count >= len(self._keys):
            # All keys have been tried in this cycle
            logger.warning("All Gemini API keys have been rate limited")
            return False

        old_index = self._current_index
        self._current_index = (self._current_index + 1) % len(self._keys)
        logger.info(
            f"Key {old_index + 1} rate limited, switching to Key {self._current_index + 1}"
        )
        return True

    def reset_keys(self):
        """
        Reset to KEY_1 (primary). Called at the start of each new
        file upload / conversion session.
        """
        self._current_index = 0
        self._rotation_count = 0
        logger.debug("Key manager reset — using Key 1 (primary)")

    def all_keys_exhausted(self) -> bool:
        """Check if all keys have been tried in the current rotation cycle."""
        return self._rotation_count >= len(self._keys)

    def has_keys(self) -> bool:
        """Check if at least one key is configured."""
        return len(self._keys) > 0


# Module-level singleton — used by all other modules
key_manager = KeyManager()
