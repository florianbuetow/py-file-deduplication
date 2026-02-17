"""Type stub for simple_term_menu."""

from collections.abc import Sequence

class TerminalMenu:
    def __init__(
        self,
        menu_entries: Sequence[str],
        *,
        title: str | None = ...,
        multi_select: bool = ...,
        show_multi_select_hint: bool = ...,
    ) -> None: ...
    def show(self) -> int | tuple[int, ...] | None: ...
