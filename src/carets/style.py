# ANSI styling, terminal width helpers, and box alignment combinators.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


from .unicode import clip_text, visual_width


def truncate_ansi(text: str, width: int, ellipsis: str = "…") -> str:
    return clip_text(text, width, ellipsis=ellipsis)


@dataclass(frozen=True)
class Border:
    top: str = "─"
    bottom: str = "─"
    left: str = "│"
    right: str = "│"
    top_left: str = "┌"
    top_right: str = "┐"
    bottom_left: str = "└"
    bottom_right: str = "┘"

    @classmethod
    def rounded(cls) -> "Border":
        return cls("─", "─", "│", "│", "╭", "╮", "╰", "╯")


@dataclass(frozen=True)
class Style:
    foreground: str | int | tuple[int, int, int] | None = None
    background: str | int | tuple[int, int, int] | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    border: Border | None = None
    width: int | None = None
    height: int | None = None

    def copy(self, **changes: object) -> "Style":
        return replace(self, **changes)

    def __post_init__(self):
        for value in (self.foreground, self.background):
            if value is not None: color_rgb(value)
        if len(self.padding)!=4 or any(type(v) is not int or v<0 for v in self.padding):
            raise ValueError("Padding uses four nonnegative cell counts")
        for value in (self.width,self.height):
            if value is not None and (type(value) is not int or value<0): raise ValueError("Style sizes must be nonnegative")

    def sgr(self, color_depth=24):
        if color_depth not in (0,4,8,24): raise ValueError("Color depth must be 0, 4, 8 or 24")
        if color_depth==0: return ""
        codes=[str(code) for enabled,code in ((self.bold,1),(self.dim,2),(self.italic,3)) if enabled]
        for value, background in ((self.foreground,False),(self.background,True)):
            if value is not None: codes.extend(map(str,color_codes(value,color_depth,background)))
        return "\x1b["+";".join(codes)+"m" if codes else ""

    def render(self, text: str) -> str:
        lines=text.splitlines() or [""]
        width=max(map(visual_width,lines),default=0) if self.width is None else self.width
        height=len(lines) if self.height is None else self.height
        top,right,bottom,left=self.padding
        padded=[]
        for line in (lines+[""]*height)[:height]:
            line=clip_text(line,width)
            padded.append(" "*left+line+" "*max(0,width-visual_width(line))+" "*right)
        total=width+left+right
        padded=[" "*total]*top+padded+[" "*total]*bottom
        if self.border:
            b=self.border
            padded=[b.top_left+b.top*total+b.top_right]+[b.left+line+b.right for line in padded]+[b.bottom_left+b.bottom*total+b.bottom_right]
        prefix=self.sgr()
        return "\n".join(prefix+line+("\x1b[0m" if prefix else "") for line in padded)

    def join_horizontal(self, *parts: str, gap: int = 0) -> str:
        return (" " * gap).join(parts)

    def join_vertical(self, *parts: str, gap: int = 0) -> str:
        return ("\n" * (gap + 1)).join(parts)

    def align(self, text: str, width: int, *, horizontal: str = "left") -> str:
        missing = max(0, width - visual_width(text))
        if horizontal == "right":
            return " " * missing + text
        if horizontal == "center":
            left = missing // 2
            return " " * left + text + " " * (missing - left)
        return text + " " * missing


_PALETTE=((0,0,0),(128,0,0),(0,128,0),(128,128,0),(0,0,128),(128,0,128),(0,128,128),(192,192,192),
          (128,128,128),(255,0,0),(0,255,0),(255,255,0),(0,0,255),(255,0,255),(0,255,255),(255,255,255))
_NAMES=dict(zip(("black","red","green","yellow","blue","magenta","cyan","white"),range(8)))
_NAMES.update({"bright_"+name:value+8 for name,value in tuple(_NAMES.items())})


def color_rgb(value):
    if type(value) is str:
        if value in _NAMES:return _PALETTE[_NAMES[value]]
        if re.fullmatch(r"#[0-9a-fA-F]{6}",value):return tuple(int(value[i:i+2],16) for i in (1,3,5))
    elif type(value) is int and 0<=value<=255:
        if value<16:return _PALETTE[value]
        if value>=232:return (8+10*(value-232),)*3
        n=value-16;steps=(0,95,135,175,215,255);return steps[n//36],steps[n//6%6],steps[n%6]
    elif type(value) is tuple and len(value)==3 and all(type(v) is int and 0<=v<=255 for v in value):return value
    raise ValueError("Colors use a named ANSI color, #RRGGBB, 0..255 index or RGB tuple")


def color_codes(value, depth, background=False):
    rgb=color_rgb(value);base=48 if background else 38
    if depth==24:return base,2,*rgb
    if depth==8:
        index=value if type(value) is int else min(range(256),key=lambda i:sum((a-b)**2 for a,b in zip(rgb,color_rgb(i))))
        return base,5,index
    if depth==4:
        index=min(range(16),key=lambda i:sum((a-b)**2 for a,b in zip(rgb,_PALETTE[i])))
        return ((40 if background else 30)+index,) if index<8 else ((100 if background else 90)+index-8,)
    return ()


def adapt_sgr(style, depth):
    if depth==0:return ""
    if depth==24:return style
    def convert(match):
        values=list(map(int,match.group(1).split(';')));out=[];i=0
        while i<len(values):
            n=values[i];i+=1
            if n in (38,48) and i<len(values) and values[i] in (2,5):
                mode=values[i];amount=4 if mode==2 else 2;part=values[i:i+amount];i+=amount
                if len(part)==amount:out.extend(color_codes(tuple(part[1:]) if mode==2 else part[1],depth,n==48))
            else:out.append(n)
        return "\x1b["+";".join(map(str,out))+"m"
    return re.sub(r"\x1b\[([0-9;]+)m",convert,style)
