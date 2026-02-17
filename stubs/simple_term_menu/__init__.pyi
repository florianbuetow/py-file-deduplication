"""Type stub for simple_term_menu."""

from collections.abc import Callable, Iterable, Sequence

class _TerminalMenuView:
    active_menu_index: int

class TerminalMenu:
    chosen_accept_key: str
    chosen_menu_index: int | None
    _view: _TerminalMenuView

    def __init__(
        self,
        menu_entries: Sequence[str],
        *,
        title: str | None = ...,
        multi_select: bool = ...,
        multi_select_keys: Iterable[str] = ...,
        multi_select_empty_ok: bool = ...,
        show_multi_select_hint: bool = ...,
        show_multi_select_hint_text: str | None = ...,
        accept_keys: Iterable[str] = ...,
        multi_select_select_on_accept: bool = ...,
        preselected_entries: Iterable[int | str] | None = ...,
        cursor_index: int | None = ...,
        status_bar: str | Callable[[str], str] | None = ...,
        status_bar_below_preview: bool = ...,
        status_bar_style: tuple[str, ...] | None = ...,
    ) -> None: ...
    def show(self) -> int | tuple[int, ...] | None: ...
