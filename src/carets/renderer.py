"""Grapheme cells, clipped layers, cursor state and deterministic frame diffs."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .unicode import cell_width,styled_graphemes
from .style import adapt_sgr
from .layout import Rect


@dataclass(frozen=True)
class Cell:
    char: str = " "
    style: str = ""
    width: int = 1


@dataclass(frozen=True)
class Cursor:
    x: int = 0
    y: int = 0
    visible: bool = False
    shape: str = "block"

    def __post_init__(self):
        if type(self.x) is not int or type(self.y) is not int or min(self.x,self.y)<0:
            raise ValueError("Cursor positions are nonnegative integers")
        if type(self.visible) is not bool or self.shape not in ('block','underline','bar'):
            raise ValueError("Invalid cursor state")


class ScreenBuffer:
    def __init__(self, width: int, height: int, fill: Cell | None = None):
        if type(width) is not int or type(height) is not int:raise TypeError('Screen sizes use integers')
        self.width,self.height=max(0,width),max(0,height);self._fill=fill or Cell()
        if self._fill.width!=1 or cell_width(self._fill.char)!=1:raise ValueError('Fill must occupy one cell')
        self.cells=[[self._fill for _ in range(self.width)] for _ in range(self.height)]

    def clear(self):
        for row in self.cells:row[:]=[self._fill]*self.width

    def copy(self):
        result=ScreenBuffer(self.width,self.height,self._fill)
        result.cells=[row[:] for row in self.cells];return result

    def _erase(self,x,y):
        if not 0<=x<self.width:return
        row=self.cells[y]
        if row[x].width==0 and x>0:row[x-1]=self._fill
        elif row[x].width==2 and x+1<self.width:row[x+1]=self._fill
        row[x]=self._fill

    def write(self,x,y,text,style='',*,clip=None):
        if not 0<=y<self.height:return
        clip=Rect(0,0,self.width,self.height) if clip is None else clip.intersect(Rect(0,0,self.width,self.height))
        column=x
        for cluster,attributes in styled_graphemes(text,style):
            width=cell_width(cluster)
            if not width:continue
            if column>=clip.x+clip.width:break
            if column>=clip.x and column+width<=clip.x+clip.width and clip.y<=y<clip.y+clip.height:
                for cx in range(column,column+width):self._erase(cx,y)
                self.cells[y][column]=Cell(cluster,attributes,width)
                if width==2:self.cells[y][column+1]=Cell('',attributes,0)
            column+=width

    def from_lines(self,lines: Iterable[str]):
        self.clear()
        for y,line in enumerate(lines):
            if y>=self.height:break
            self.write(0,y,line)

    def blit(self,source,x=0,y=0,*,clip=None,transparent=False):
        for row,values in enumerate(source.cells):
            for column,cell in enumerate(values):
                if cell.width==0 or (transparent and cell.char==' ' and not cell.style):continue
                self.write(x+column,y+row,cell.char,cell.style,clip=clip)

    def to_text(self):
        return '\n'.join(''.join(c.char for c in row if c.width).rstrip() for row in self.cells)


class CellDiffRenderer:
    SYNC_START='\x1b[?2026h';SYNC_END='\x1b[?2026l'

    def __init__(self,width=80,height=24,*,color_depth=24,synchronized=True,ansi=True):
        if color_depth not in (0,4,8,24):raise ValueError('Unknown color depth')
        self.width,self.height=width,height;self.color_depth=color_depth
        self.synchronized,self.ansi=synchronized,ansi
        self.previous=ScreenBuffer(width,height);self._force=False;self._cursor=None

    def invalidate(self):self._force=True

    def resize(self,width,height):
        if (width,height)!=(self.width,self.height):
            self.width,self.height=width,height;self._force=True

    def render(self,content,*,cursor=None,full=False):
        if isinstance(content,ScreenBuffer):
            current=content
            self.resize(current.width,current.height)
        else:
            current=ScreenBuffer(self.width,self.height);current.from_lines(content.splitlines() or [''])
        force=full or self._force or (self.previous.width,self.previous.height)!=(current.width,current.height)
        if not self.ansi:
            self.previous=current.copy();self._force=False
            return current.to_text()+'\n'
        output=[self.SYNC_START] if self.synchronized else []
        if force:output.append('\x1b[2J')
        for y,row in enumerate(current.cells):
            previous=self.previous.cells[y] if y<self.previous.height else []
            x=0
            while x<current.width:
                cell=row[x]
                changed=force or x>=len(previous) or cell!=previous[x] or (cell.width==2 and (x+1>=len(previous) or row[x+1]!=previous[x+1]))
                if cell.width==0 or not changed:x+=1;continue
                start=x;style=cell.style;chars=[]
                while x<current.width:
                    cell=row[x]
                    changed=force or x>=len(previous) or cell!=previous[x] or (cell.width==2 and (x+1>=len(previous) or row[x+1]!=previous[x+1]))
                    if cell.width==0:x+=1;continue
                    if not changed or cell.style!=style:break
                    chars.append(cell.char);x+=cell.width
                output.append(f'\x1b[{y+1};{start+1}H{adapt_sgr(style,self.color_depth)}'+''.join(chars)+'\x1b[0m')
        desired=cursor if cursor is not None else self._cursor
        if desired is not None:
            if desired.visible and desired.x<current.width and desired.y<current.height:
                shape={'block':2,'underline':4,'bar':6}[desired.shape]
                output.append(f'\x1b[{shape} q\x1b[{desired.y+1};{desired.x+1}H\x1b[?25h')
            else:output.append('\x1b[?25l')
            self._cursor=desired
        if self.synchronized:output.append(self.SYNC_END)
        self.previous=current.copy();self._force=False
        return ''.join(output)

    def close(self):
        """Release an explicitly managed cursor to terminal defaults once."""
        if self._cursor is None or not self.ansi:return ''
        self._cursor=None
        return '\x1b[0 q\x1b[?25h'
