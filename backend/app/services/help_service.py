from pathlib import Path

from app.core.config import settings
from app.services.interfaces import IHelpService


class HelpService(IHelpService):
    """HelpService implementation reading system assistance guidance from a markdown resource file on disk."""

    def __init__(self, help_file_path: Path | None = None):
        """Initializes the HelpService with an optional custom path to help.md.

        Args:
            help_file_path: Optional custom path to help.md.
        """
        if help_file_path is None:
            # Resolve default path relative to current module location
            help_file_path = Path(__file__).parent.parent / "resources" / "help.md"
        self._help_file_path = help_file_path
        self._cached_help = None

    def get_help_markdown(self) -> str:
        """Returns the system guidance markdown text.

        Bypasses the in-memory cache if settings.DEBUG is True to allow developers
        to modify resources/help.md and immediately see changes reload in dev.
        """
        if settings.DEBUG:
            return self._read_file()

        if self._cached_help is None:
            self._cached_help = self._read_file()
        return self._cached_help

    def _read_file(self) -> str:
        """Reads help.md contents from disk with resilient fallback if disk I/O fails."""
        try:
            return self._help_file_path.read_text(encoding="utf-8").strip()
        except Exception:
            # Resilient fallback if disk file is missing or unreadable
            return (
                "### How to use the ASM AI Reporting Agent\n\n"
                "Ask analytical questions about your database."
            )
