"""Look and feel for the ENC inverter parameter editor.

Every colour, font and ttk style lives here so the editor module only has to
deal with inverter logic.  Two palettes are provided; the editor swaps between
them at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk

FONT = ("Segoe UI", 10)
SMALL_FONT = ("Segoe UI", 9)
BOLD_FONT = ("Segoe UI", 10, "bold")
TITLE_FONT = ("Segoe UI Semibold", 15)
SECTION_FONT = ("Segoe UI", 8, "bold")
TABLE_FONT = ("Segoe UI", 10, "normal")
TABLE_HEADER_FONT = ("Segoe UI", 9, "bold")
TABLE_INDEX_FONT = ("Segoe UI", 9, "normal")
MONO_FONT = ("Consolas", 9)


@dataclass(frozen=True)
class Palette:
    """Colours used by both the ttk widgets and the parameter sheet."""

    name: str
    sheet_theme: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    brand: str
    brand_text: str
    brand_muted: str
    accent: str
    accent_active: str
    accent_text: str
    success: str
    warning: str
    danger: str
    field: str
    selection: str
    selection_text: str
    readonly_bg: str
    readonly_fg: str
    modified_bg: str
    modified_fg: str
    # Marks a setting that no longer matches the manual's factory value; kept
    # away from the amber of an unwritten edit and the red of a failed read.
    nondefault_bg: str
    nondefault_fg: str
    error_bg: str
    error_fg: str


LIGHT = Palette(
    name="light",
    sheet_theme="light blue",
    bg="#EDF1F7",
    surface="#FFFFFF",
    surface_alt="#F4F7FB",
    border="#D3DBE6",
    text="#17202B",
    muted="#66748A",
    brand="#12314F",
    brand_text="#FFFFFF",
    brand_muted="#9FB6CE",
    accent="#2563EB",
    accent_active="#1D4ED8",
    accent_text="#FFFFFF",
    success="#15803D",
    warning="#B45309",
    danger="#DC2626",
    field="#FFFFFF",
    selection="#DBE7FF",
    selection_text="#12314F",
    readonly_bg="#F1F4F8",
    readonly_fg="#7A8798",
    modified_bg="#FDF0D5",
    modified_fg="#8A5200",
    nondefault_bg="#EAE2FB",
    nondefault_fg="#5433B5",
    error_bg="#FBE3E3",
    error_fg="#A81E1E",
)

DARK = Palette(
    name="dark",
    sheet_theme="dark",
    bg="#12161D",
    surface="#1A2029",
    surface_alt="#212936",
    border="#2F3948",
    text="#E4E9F2",
    muted="#94A2B8",
    brand="#0B1119",
    brand_text="#F2F5FA",
    brand_muted="#7B8DA6",
    accent="#3B82F6",
    accent_active="#2563EB",
    accent_text="#FFFFFF",
    success="#4ADE80",
    warning="#FBBF24",
    danger="#F87171",
    field="#141A22",
    selection="#1E3A64",
    selection_text="#EAF1FF",
    readonly_bg="#1E242E",
    readonly_fg="#7D8B9E",
    modified_bg="#3A2E12",
    modified_fg="#F3C466",
    nondefault_bg="#2A2145",
    nondefault_fg="#BFAAF7",
    error_bg="#3B1B1E",
    error_fg="#F79A9A",
)

THEMES = {palette.name: palette for palette in (LIGHT, DARK)}


def apply_theme(root, style: ttk.Style, palette: Palette) -> None:
    """Restyle every ttk widget class the editor uses."""
    style.theme_use("clam")
    root.configure(background=palette.bg)

    # Drop-down list of the comboboxes is a classic Tk listbox.
    root.option_add("*TCombobox*Listbox.background", palette.surface)
    root.option_add("*TCombobox*Listbox.foreground", palette.text)
    root.option_add("*TCombobox*Listbox.selectBackground", palette.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", palette.accent_text)
    root.option_add("*TCombobox*Listbox.font", FONT)

    style.configure(".", font=FONT, background=palette.bg, foreground=palette.text)

    style.configure("App.TFrame", background=palette.bg)
    style.configure("Card.TFrame", background=palette.surface)
    style.configure("Brand.TFrame", background=palette.brand)
    style.configure("Status.TFrame", background=palette.surface)
    style.configure("Toolbar.TFrame", background=palette.bg)

    style.configure("TLabel", background=palette.bg, foreground=palette.text)
    style.configure("Card.TLabel", background=palette.surface, foreground=palette.text)
    style.configure("Muted.TLabel", background=palette.surface, foreground=palette.muted, font=SMALL_FONT)
    style.configure("Field.TLabel", background=palette.surface, foreground=palette.muted, font=SMALL_FONT)
    style.configure(
        "Section.TLabel",
        background=palette.surface,
        foreground=palette.muted,
        font=SECTION_FONT,
    )
    style.configure("BrandTitle.TLabel", background=palette.brand, foreground=palette.brand_text, font=TITLE_FONT)
    style.configure("BrandSub.TLabel", background=palette.brand, foreground=palette.brand_muted, font=SMALL_FONT)
    style.configure("Status.TLabel", background=palette.surface, foreground=palette.text, font=SMALL_FONT)
    style.configure("StatusMuted.TLabel", background=palette.surface, foreground=palette.muted, font=SMALL_FONT)
    style.configure("Mono.TLabel", background=palette.surface, foreground=palette.muted, font=MONO_FONT)

    for name, colour in (
        ("Success", palette.success),
        ("Warning", palette.warning),
        ("Danger", palette.danger),
        ("Accent", palette.accent),
    ):
        style.configure(f"{name}.Status.TLabel", background=palette.surface, foreground=colour, font=SMALL_FONT)

    _button(style, "TButton", palette, palette.surface_alt, palette.text, palette.border)
    _button(style, "Accent.TButton", palette, palette.accent, palette.accent_text, palette.accent)
    _button(style, "Card.TButton", palette, palette.surface_alt, palette.text, palette.border)
    _button(style, "Brand.TButton", palette, palette.brand, palette.brand_muted, palette.brand)
    _button(style, "Danger.TButton", palette, palette.surface_alt, palette.danger, palette.border)
    style.configure("Icon.TButton", padding=(6, 4))
    _button(style, "Icon.TButton", palette, palette.surface_alt, palette.text, palette.border)

    style.configure(
        "TCombobox",
        fieldbackground=palette.field,
        background=palette.surface_alt,
        foreground=palette.text,
        arrowcolor=palette.muted,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        insertcolor=palette.text,
        padding=(8, 5),
        selectbackground=palette.field,
        selectforeground=palette.text,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.field), ("disabled", palette.surface_alt)],
        foreground=[("disabled", palette.muted)],
        bordercolor=[("focus", palette.accent), ("hover", palette.accent)],
        arrowcolor=[("hover", palette.accent)],
    )

    style.configure(
        "TSpinbox",
        fieldbackground=palette.field,
        background=palette.surface_alt,
        foreground=palette.text,
        arrowcolor=palette.muted,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        insertcolor=palette.text,
        padding=(8, 4),
    )
    style.map("TSpinbox", bordercolor=[("focus", palette.accent)], arrowcolor=[("hover", palette.accent)])

    style.configure(
        "TEntry",
        fieldbackground=palette.field,
        foreground=palette.text,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        insertcolor=palette.text,
        padding=(8, 5),
    )
    style.map("TEntry", bordercolor=[("focus", palette.accent)])
    style.configure("Search.TEntry", padding=(8, 6))
    style.map("Search.TEntry", bordercolor=[("focus", palette.accent)])

    style.configure(
        "Groups.Treeview",
        background=palette.surface,
        fieldbackground=palette.surface,
        foreground=palette.text,
        bordercolor=palette.surface,
        lightcolor=palette.surface,
        darkcolor=palette.surface,
        borderwidth=0,
        rowheight=26,
        font=FONT,
    )
    style.map(
        "Groups.Treeview",
        background=[("selected", palette.selection)],
        foreground=[("selected", palette.selection_text)],
    )
    style.layout("Groups.Treeview", [("Groups.Treeview.treearea", {"sticky": "nswe"})])

    style.configure(
        "TProgressbar",
        troughcolor=palette.surface_alt,
        background=palette.accent,
        bordercolor=palette.surface_alt,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        thickness=6,
    )

    style.configure("TSeparator", background=palette.border)
    style.configure(
        "Vertical.TScrollbar",
        background=palette.surface_alt,
        troughcolor=palette.surface,
        bordercolor=palette.surface,
        arrowcolor=palette.muted,
        lightcolor=palette.surface_alt,
        darkcolor=palette.surface_alt,
    )
    style.map("Vertical.TScrollbar", background=[("active", palette.border)])


def _button(style: ttk.Style, name: str, palette: Palette, bg: str, fg: str, border: str) -> None:
    style.configure(
        name,
        background=bg,
        foreground=fg,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        focuscolor=border,
        borderwidth=1,
        relief="flat",
        font=FONT if name != "Icon.TButton" else SMALL_FONT,
        padding=(12, 6) if name != "Icon.TButton" else (7, 4),
    )
    hover = palette.accent_active if bg == palette.accent else palette.selection
    style.map(
        name,
        background=[("disabled", palette.surface_alt), ("pressed", hover), ("active", hover)],
        foreground=[("disabled", palette.muted)],
        bordercolor=[("active", palette.accent), ("focus", palette.accent)],
    )


def sheet_options(palette: Palette) -> dict:
    """Colour options for a :class:`tksheet.Sheet` matching ``palette``."""
    return {
        "table_bg": palette.surface,
        "table_fg": palette.text,
        "table_grid_fg": palette.border,
        "table_selected_cells_bg": palette.selection,
        "table_selected_cells_fg": palette.selection_text,
        "table_selected_rows_bg": palette.selection,
        "table_selected_rows_fg": palette.selection_text,
        "table_selected_columns_bg": palette.selection,
        "table_selected_columns_fg": palette.selection_text,
        "table_selected_cells_border_fg": palette.accent,
        "table_selected_rows_border_fg": palette.accent,
        "table_selected_columns_border_fg": palette.accent,
        "table_selected_box_cells_fg": palette.accent,
        "table_selected_box_rows_fg": palette.accent,
        "table_selected_box_columns_fg": palette.accent,
        "table_editor_bg": palette.field,
        "table_editor_fg": palette.text,
        "header_bg": palette.surface_alt,
        "header_fg": palette.muted,
        "header_grid_fg": palette.border,
        "header_border_fg": palette.border,
        "header_selected_cells_bg": palette.accent,
        "header_selected_cells_fg": palette.accent_text,
        "header_selected_columns_bg": palette.accent,
        "header_selected_columns_fg": palette.accent_text,
        "index_bg": palette.surface_alt,
        "index_fg": palette.muted,
        "index_grid_fg": palette.border,
        "index_border_fg": palette.border,
        "index_selected_cells_bg": palette.accent,
        "index_selected_cells_fg": palette.accent_text,
        "index_selected_rows_bg": palette.accent,
        "index_selected_rows_fg": palette.accent_text,
        "top_left_bg": palette.surface_alt,
        "top_left_fg": palette.border,
        "frame_bg": palette.surface,
        "outline_color": palette.border,
        "popup_menu_bg": palette.surface,
        "popup_menu_fg": palette.text,
        "popup_menu_highlight_bg": palette.accent,
        "popup_menu_highlight_fg": palette.accent_text,
        "table_font": TABLE_FONT,
        "header_font": TABLE_HEADER_FONT,
        "index_font": TABLE_INDEX_FONT,
    }
