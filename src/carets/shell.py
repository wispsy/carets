"""Theme roles and clipped application regions over the existing renderer."""
from dataclasses import dataclass

from .layout import Column, Row, Stack, Leaf, Insets, Size, fixed
from .renderer import ScreenBuffer
from .style import Style


@dataclass(frozen=True)
class Theme:
    text: Style = Style()
    muted: Style = Style(dim=True)
    accent: Style = Style(foreground="cyan", bold=True)
    focus: Style = Style(foreground="yellow", bold=True)
    disabled: Style = Style(dim=True)
    success: Style = Style(foreground="green")
    warning: Style = Style(foreground="yellow")
    error: Style = Style(foreground="red", bold=True)
    spacing: int = 1

    def __post_init__(self):
        if type(self.spacing) is not int or not 0 <= self.spacing <= 8:
            raise ValueError("Theme spacing must be between zero and eight cells")
        if any(type(getattr(self, role)) is not Style for role in ("text", "muted", "accent", "focus", "disabled", "success", "warning", "error")):
            raise TypeError("Theme roles require Style values")


@dataclass(frozen=True)
class ShellCommand:
    id: str
    key: str
    label: str
    enabled: bool = True

    def __post_init__(self):
        if any(type(s) is not str or not s or len(s) > 128 for s in (self.id, self.key, self.label)) or type(self.enabled) is not bool:
            raise ValueError("Commands require bounded identity, key, label and enabled state")


@dataclass(frozen=True)
class ShellFrame:
    buffer: ScreenBuffer
    layout: object


@dataclass(frozen=True)
class AppShell:
    title: str
    theme: Theme = Theme()
    sidebar_width: int = 20
    narrow_width: int = 60

    def __post_init__(self):
        if any(type(v) is not int or not 1 <= v <= 1024 for v in (self.sidebar_width, self.narrow_width)):
            raise ValueError("Shell breakpoints require positive bounded cell sizes")

    def frame(self, width, height, *, body="", navigation=(), selected=0,
              status="ready", severity="muted", commands=(), modal=None):
        """Render caller-owned content. Focus and actions stay in the application.

        Narrow layouts hide the sidebar but name the current section in the
        title. All regions clip by grapheme cells, including modal overlays.
        """
        Size(width, height)
        if width > 4096 or height > 1024:
            raise ValueError("Shell viewport exceeds the bounded terminal size")
        if severity not in ("muted", "success", "warning", "error"):
            raise ValueError("Unknown status role")
        if len(navigation) > 64 or len(commands) > 32:
            raise ValueError("Shell navigation and commands must be bounded")
        section = navigation[selected] if 0 <= selected < len(navigation) else ""
        show_nav = bool(navigation) and width >= self.narrow_width
        children = [Leaf("body")]
        if show_nav:
            children.insert(0, Leaf("navigation", width=fixed(min(self.sidebar_width, width // 3))))
        base = Column("base", Leaf("header", height=fixed(min(1, height))),
                      Row("main", *children, gap=self.theme.spacing if show_nav else 0),
                      Leaf("footer", height=fixed(1 if height > 1 else 0)))
        tree = base
        if modal is not None and width and height:
            mw, mh = min(width, 64), min(height, max(3, len(modal.splitlines()) + 2))
            tree = Stack("shell", base, Leaf("modal", width=fixed(mw), height=fixed(mh),
                         margin=Insets(top=(height-mh)//2, left=(width-mw)//2)))
        layout = tree.arrange(width, height)
        buffer = ScreenBuffer(width, height)

        def paint(id, text, role):
            region = layout.get(id).clip
            for y, line in enumerate(text.splitlines()):
                if y >= region.height:
                    break
                buffer.write(region.x, region.y+y, line, getattr(self.theme, role).sgr(), clip=region)

        paint("header", self.title + (" | " + section if section else ""), "accent")
        paint("body", body, "text")
        if show_nav:
            paint("navigation", "\n".join(("> " if i == selected else "  ")+name for i, name in enumerate(navigation)), "focus")
        help_text = " | ".join(c.key+" "+c.label+(" [disabled]" if not c.enabled else "") for c in commands)
        paint("footer", status + (" | " + help_text if help_text else ""), severity)
        if modal is not None and width and height:
            region = layout.get("modal").clip
            # Opaque overlay removes underlying wide glyphs through ScreenBuffer.
            for y in range(region.y, region.y+region.height):
                buffer.write(region.x, y, " "*region.width, clip=region)
            paint("modal", "[dialog]\n"+modal, "focus")
        return ShellFrame(buffer, layout)
