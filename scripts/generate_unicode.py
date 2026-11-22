"""Regenerate pinned Unicode tables from the explicitly downloaded UCD files."""
from pathlib import Path
import json
import sys


def generate(directory, destination):
    root = Path(directory); tables = {}
    def rows(name):
        for line in (root/name).read_text(encoding='utf-8').splitlines():
            line=line.split('#',1)[0].strip()
            if not line: continue
            fields=[f.strip() for f in line.split(';')]
            parts=fields[0].split('..'); yield int(parts[0],16),int(parts[-1],16),fields[1:]
    gcb=[(a,b,p[0]) for a,b,p in rows('grapheme.txt') if p[0] not in ('LV','LVT')]
    incb=[(a,b,p[1]) for a,b,p in rows('derived.txt') if p[0]=='InCB']
    tables['GCB']=sorted(gcb);tables['INCB']=sorted(incb)
    for prop in ('Extended_Pictographic','Emoji_Presentation'):
        tables[prop.upper()]=[(a,b) for a,b,p in rows('emoji.txt') if p[0]==prop]
    tables['WIDE']=[(a,b) for a,b,p in rows('width.txt') if p[0] in ('W','F')]
    text='"""Generated Unicode 18.0.0 properties; see UNICODE_LICENSE.txt and docs/unicode.md."""\nVERSION = "18.0.0"\n'
    for key,values in tables.items():
        text+=key+' = (\n'+''.join('    '+repr(value)+',\n' for value in sorted(values))+')\n'
    Path(destination).write_text(text,encoding='utf-8')


if __name__=='__main__': generate(*sys.argv[1:])
