"""Pinned extended grapheme boundaries and an explicit terminal-cell width policy."""
from bisect import bisect_right
from functools import lru_cache
import re
from . import _unicode_data as data

ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*?(?:\x07|\x1b\\))")
_GCB_STARTS = tuple(row[0] for row in data.GCB)
_INCB_STARTS = tuple(row[0] for row in data.INCB)
_RANGE_STARTS = {name:tuple(row[0] for row in getattr(data,name)) for name in ('WIDE','EXTENDED_PICTOGRAPHIC','EMOJI_PRESENTATION')}


def _property(cp, rows, starts, default='Other'):
    index=bisect_right(starts,cp)-1
    return rows[index][2] if index>=0 and cp<=rows[index][1] else default


@lru_cache(maxsize=8192)
def _gcb(cp):
    if 0xAC00<=cp<=0xD7A3: return 'LV' if (cp-0xAC00)%28==0 else 'LVT'
    return _property(cp,data.GCB,_GCB_STARTS)


def _incb(cp): return _property(cp,data.INCB,_INCB_STARTS,'None')


def _in(cp,name):
    rows=getattr(data,name);index=bisect_right(_RANGE_STARTS[name],cp)-1
    return index>=0 and cp<=rows[index][1]


def graphemes(text):
    """Yield Unicode 18 extended clusters (UAX #29 revision 49, including GB9c)."""
    if not text: return
    codes=list(map(ord,text)); props=list(map(_gcb,codes)); start=0; ri=1 if props[0]=='Regional_Indicator' else 0
    for i in range(1,len(text)):
        left,right=props[i-1],props[i]; join=False
        if left=='CR' and right=='LF': join=True
        elif left in ('Control','CR','LF') or right in ('Control','CR','LF'): pass
        elif left=='L' and right in ('L','V','LV','LVT'): join=True
        elif left in ('LV','V') and right in ('V','T'): join=True
        elif left in ('LVT','T') and right=='T': join=True
        elif right in ('Extend','ZWJ','SpacingMark') or left=='Prepend': join=True
        elif _incb(codes[i])=='Consonant':
            j=i-1
            while j>=start and _incb(codes[j])=='Extend': j-=1
            join=j>=start and _incb(codes[j])=='Linker'
        if not join and _in(codes[i],'EXTENDED_PICTOGRAPHIC') and left=='ZWJ':
            j=i-2
            while j>=start and props[j]=='Extend': j-=1
            join=j>=start and _in(codes[j],'EXTENDED_PICTOGRAPHIC')
        if left=='Regional_Indicator' and right=='Regional_Indicator': join=bool(ri%2)
        if not join:
            yield text[start:i];start=i
        ri=ri+1 if right=='Regional_Indicator' and left=='Regional_Indicator' else 1 if right=='Regional_Indicator' else 0
    yield text[start:]


def cell_width(cluster):
    """Controls/orphan marks occupy zero; common emoji/wide clusters occupy two.

    Ambiguous width is one. Fonts, shaping and emulator policy can differ; this
    is a deterministic cell policy, not a promise about every terminal font.
    """
    bases=[ord(c) for c in cluster if _gcb(ord(c)) not in ('Extend','ZWJ','SpacingMark','Prepend','Control','CR','LF')]
    if not bases: return 0
    if '\ufe0f' in cluster or '\u20e3' in cluster or ('\u200d' in cluster and any(_in(c,'EXTENDED_PICTOGRAPHIC') for c in bases)):
        return 2
    if '\ufe0e' not in cluster and any(_in(c,'EMOJI_PRESENTATION') for c in bases): return 2
    return max(2 if _in(c,'WIDE') else 1 for c in bases)


def visual_width(text):
    return sum(cell_width(cluster) for cluster in graphemes(ANSI_RE.sub('',text)))


def styled_graphemes(text, initial=''):
    """Yield clusters with bounded SGR state; non-SGR control sequences are data-free."""
    plain=[]; changes={0:initial}; position=0; state=initial; offset=0
    for match in ANSI_RE.finditer(text):
        segment=text[position:match.start()];plain.append(segment)
        offset+=len(segment)
        sequence=match.group()
        if sequence.startswith('\x1b[') and sequence.endswith('m'):
            state=merge_sgr(state,sequence);changes[offset]=state
        position=match.end()
    plain.append(text[position:]);offset=0;state=initial
    changes=iter(sorted(changes.items()));pending=next(changes,None)
    for cluster in graphemes(''.join(plain)):
        while pending is not None and pending[0]<=offset:
            state=pending[1];pending=next(changes,None)
        yield cluster,state
        offset+=len(cluster)


def merge_sgr(previous, sequence):
    attributes={}; fg=None; bg=None
    for match in re.finditer(r'\x1b\[([0-9;]*)m',previous+sequence):
        values=[int(x or 0) for x in match.group(1).split(';')]; i=0
        while i<len(values):
            n=values[i];i+=1
            if n==0: attributes.clear();fg=bg=None
            elif n in (1,2,3,4,5,7,8,9): attributes[n]=True
            elif n in (22,23,24,25,27,28,29):
                for key in ((1,2) if n==22 else (n-20,)): attributes.pop(key,None)
            elif n==39: fg=None
            elif n==49: bg=None
            elif 30<=n<=37 or 90<=n<=97: fg=(n,)
            elif 40<=n<=47 or 100<=n<=107: bg=(n,)
            elif n in (38,48) and i<len(values) and values[i] in (2,5):
                amount=4 if values[i]==2 else 2
                chunk=values[i:i+amount];i+=amount
                if len(chunk)==amount and all(0<=v<=255 for v in chunk[1:]):
                    if n==38: fg=(n,*chunk)
                    else: bg=(n,*chunk)
    codes=sorted(attributes)+list(fg or ())+list(bg or ())
    return '\x1b['+';'.join(map(str,codes))+'m' if codes else ''


def clip_text(text, width, *, ellipsis=''):
    if width<=0: return ''
    if visual_width(text)<=width: return text
    suffix=''.join(c for c in graphemes(ellipsis) if cell_width(c)<=width)
    if visual_width(suffix)>width: suffix=''
    target=width-visual_width(suffix);used=0;parts=[];active=''
    for cluster,style in styled_graphemes(text):
        size=cell_width(cluster)
        if used+size>target: break
        if style!=active:
            parts.append('\x1b[0m' if active else '');parts.append(style);active=style
        parts.append(cluster);used+=size
    parts.append(suffix)
    if active:parts.append('\x1b[0m')
    return ''.join(parts)
