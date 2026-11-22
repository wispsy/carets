"""Incremental UTF-8, legacy/Kitty keys and bounded terminal protocol recovery."""
from __future__ import annotations
import asyncio
import codecs
import os
import re
from collections.abc import AsyncIterator
from typing import Any
from .runtime import FocusMsg,KeyMsg,MouseMsg,ProtocolMsg

_MODIFIERS=((1,'shift'),(2,'alt'),(4,'ctrl'),(8,'super'),(16,'hyper'),(32,'meta'),(64,'capslock'),(128,'numlock'))
_ARROWS={'A':'up','B':'down','C':'right','D':'left','H':'home','F':'end','Z':'backtab'}
_TILDE={1:'home',2:'insert',3:'delete',4:'end',5:'pageup',6:'pagedown',7:'home',8:'end',
        11:'f1',12:'f2',13:'f3',14:'f4',15:'f5',17:'f6',18:'f7',19:'f8',20:'f9',21:'f10',23:'f11',24:'f12'}
_KITTY={27:'escape',13:'enter',9:'tab',127:'backspace',57348:'insert',57349:'delete',57350:'left',57351:'right',
        57352:'up',57353:'down',57354:'pageup',57355:'pagedown',57356:'home',57357:'end',57358:'capslock',
        57359:'scrolllock',57360:'numlock',57361:'printscreen',57362:'pause',57363:'menu'}
_KITTY.update({57364+i:'f'+str(i+1) for i in range(35)})


def _modifiers(value):return frozenset(name for bit,name in _MODIFIERS if (value-1)&bit)


def _codepoint(cp,modifiers=frozenset(),action='press',text=None):
    if not 0<=cp<=0x10ffff or 0xd800<=cp<=0xdfff:raise ValueError('Invalid scalar')
    key=_KITTY.get(cp,chr(cp)); blocked=bool(modifiers&{'ctrl','alt','super','hyper','meta'})
    if text is None and cp not in _KITTY and cp>=32 and not blocked:text=chr(cp)
    if key=='tab' and 'shift' in modifiers:key='backtab'
    return KeyMsg(key,text,modifiers,action)


class AnsiInputParser(AsyncIterator):
    def __init__(self,stream: Any=None,*,loop=None,max_sequence=1024,max_paste_bytes=65536,escape_timeout=0.035):
        if type(max_sequence) is not int or not 16<=max_sequence<=65536:raise ValueError('Invalid sequence limit')
        if type(max_paste_bytes) is not int or not 0<=max_paste_bytes<=1024*1024:raise ValueError('Invalid paste limit')
        if escape_timeout is not None and not 0<=escape_timeout<=1:raise ValueError('Invalid escape delay')
        self.stream,self.loop=stream,loop;self.max_sequence=max_sequence;self.max_paste_bytes=max_paste_bytes
        self.escape_timeout=escape_timeout;self._decoder=codecs.getincrementaldecoder('utf-8')('replace')
        self._buffer='';self._events=asyncio.Queue();self._reader_registered=False;self._closed=False
        self._paste=None;self._paste_bytes=0;self._paste_truncated=False;self._escape_handle=None
        self._discard=None

    def start(self):
        if self._closed:raise RuntimeError('Parser is closed')
        if self.stream is None or self._reader_registered:return
        (self.loop or asyncio.get_running_loop()).add_reader(self.stream.fileno(),self._on_readable)
        self._reader_registered=True

    def _remove_reader(self):
        if self._reader_registered:
            (self.loop or asyncio.get_event_loop()).remove_reader(self.stream.fileno());self._reader_registered=False
        if self._escape_handle is not None:self._escape_handle.cancel();self._escape_handle=None

    def close(self):
        if self._closed:return
        self._remove_reader();self._closed=True;self._events.put_nowait(None)

    async def __anext__(self):
        if self._closed and self._events.empty():raise StopAsyncIteration
        if self.stream is not None and not self._reader_registered and not self._closed:self.start()
        event=await self._events.get()
        if event is None:raise StopAsyncIteration
        return event

    def _on_readable(self):
        try:data=os.read(self.stream.fileno(),4096)
        except (BlockingIOError,InterruptedError):return
        if data:self.feed(data)
        else:self.finish()

    def feed(self,data):
        if self._closed:raise RuntimeError('Parser is closed')
        if self._escape_handle is not None:self._escape_handle.cancel();self._escape_handle=None
        self._buffer+=data if isinstance(data,str) else self._decoder.decode(data,final=False)
        events=self._parse()
        for event in events:self._events.put_nowait(event)
        if self._buffer=='\x1b' and self.escape_timeout is not None:
            try:loop=self.loop or asyncio.get_running_loop()
            except RuntimeError:pass
            else:self._escape_handle=loop.call_later(self.escape_timeout,self.flush_escape)
        return events

    def flush_escape(self):
        self._escape_handle=None
        if self._buffer=='\x1b':
            self._buffer='';event=KeyMsg('escape');self._events.put_nowait(event);return [event]
        return []

    def finish(self):
        if self._closed:return []
        self._remove_reader();self._buffer+=self._decoder.decode(b'',final=True)
        events=self._parse(final=True)
        for event in events:self._events.put_nowait(event)
        self._closed=True;self._events.put_nowait(None);return events

    def _append_paste(self,value):
        raw=value.encode('utf-8');remaining=self.max_paste_bytes-self._paste_bytes
        if len(raw)>remaining:
            raw=raw[:remaining];value=raw.decode('utf-8','ignore');self._paste_truncated=True
        self._paste.append(value);self._paste_bytes+=len(value.encode('utf-8'))

    def _parse(self,final=False):
        events=[]
        while self._buffer or (final and self._paste is not None):
            if self._paste is not None:
                end=self._buffer.find('\x1b[201~')
                if end>=0 or final:
                    self._append_paste(self._buffer if end<0 else self._buffer[:end])
                    events.append(KeyMsg('paste',''.join(self._paste),truncated=self._paste_truncated or end<0))
                    self._buffer='' if end<0 else self._buffer[end+6:];self._paste=None;continue
                keep=min(5,len(self._buffer));self._append_paste(self._buffer[:-keep] if keep else self._buffer)
                self._buffer=self._buffer[-keep:] if keep else '';break
            if self._discard=='csi':
                i=0
                while i<len(self._buffer) and self._buffer[i]!='\x1b' and not '@'<=self._buffer[i]<='~':i+=1
                if i==len(self._buffer):self._buffer='';break
                consume=i if self._buffer[i]=='\x1b' else i+1
                self._buffer=self._buffer[consume:];self._discard=None;continue
            if self._discard=='string':
                match=re.search('\x07|\x1b\\\\',self._buffer)
                if match:self._buffer=self._buffer[match.end():];self._discard=None;continue
                self._buffer='\x1b' if self._buffer.endswith('\x1b') else '';break
            if self._buffer.startswith(('\x1b]','\x1bP','\x1b^','\x1b_')):
                self._buffer=self._buffer[2:];self._discard='string';events.append(ProtocolMsg('unknown'));continue
            if self._buffer.startswith(('\x1b[','\x1bO')):
                prefix=self._buffer[:2];i=2
                while i<len(self._buffer) and ' '<=self._buffer[i]<='?':i+=1
                if i==len(self._buffer):
                    if i>self.max_sequence:
                        self._buffer='';self._discard='csi';events.append(ProtocolMsg('malformed'))
                    elif final:self._buffer='';events.append(ProtocolMsg('malformed'))
                    break
                if not '@'<=self._buffer[i]<='~':
                    self._buffer=self._buffer[i:];events.append(ProtocolMsg('malformed'));continue
                raw=self._buffer[2:i];last=self._buffer[i];self._buffer=self._buffer[i+1:]
                if i>self.max_sequence:events.append(ProtocolMsg('malformed'));continue
                if prefix=='\x1b[' and raw=='200' and last=='~':
                    self._paste=[];self._paste_bytes=0;self._paste_truncated=False;continue
                try:events.append(self._sequence(prefix,raw,last))
                except (ValueError,OverflowError):events.append(ProtocolMsg('malformed'))
                continue
            char=self._buffer[0]
            if char=='\x1b':
                if len(self._buffer)==1:
                    if final:events.append(KeyMsg('escape'));self._buffer=''
                    break
                other=self._buffer[1];self._buffer=self._buffer[2:]
                events.append(KeyMsg(other,modifiers=frozenset({'alt'})));continue
            self._buffer=self._buffer[1:]
            keys={'\r':'enter','\n':'enter','\t':'tab','\x7f':'backspace','\x08':'backspace','\x03':'ctrl-c'}
            if char in keys:events.append(KeyMsg(keys[char]))
            elif 0<ord(char)<27:events.append(KeyMsg('ctrl-'+chr(ord(char)+96),modifiers=frozenset({'ctrl'})))
            elif ord(char)<32 or 127<=ord(char)<160:events.append(ProtocolMsg('control'))
            else:events.append(KeyMsg(char,char))
        return events

    def _sequence(self,prefix,raw,last):
        if raw.startswith('<') and last in ('m','M'):
            parts=raw[1:].split(';')
            if len(parts)!=3:raise ValueError('Invalid mouse report')
            code,x,y=map(int,parts)
            if not 0<=code<=255 or not 1<=x<=1000000 or not 1<=y<=1000000:raise ValueError('Mouse bounds')
            mods=frozenset(name for bit,name in ((4,'shift'),(8,'alt'),(16,'ctrl')) if code&bit)
            low=code&3;button=('left','middle','right','none')[low]
            if code&64:button=('up','down','left','right')[low];action='scroll'
            elif code&32:action='move' if low==3 else 'drag'
            else:action='release' if last=='m' or low==3 else 'press'
            if code&128:button=('back','forward','button10','button11')[low]
            return MouseMsg(x-1,y-1,button,action,mods)
        if raw.startswith('?') and last=='u':
            value=int(raw[1:])
            if not 0<=value<=65535:raise ValueError('Invalid protocol flags')
            return ProtocolMsg('kitty',value)
        if last in ('I','O') and not raw:return FocusMsg(last=='I')
        parts=raw.split(';') if raw else []
        if last=='u':
            if not parts or not parts[0]:raise ValueError('Missing key code')
            cp=int(parts[0].split(':')[0]);mod=parts[1].split(':') if len(parts)>1 else ['1']
            encoded=int(mod[0] or 1)
            if not 1<=encoded<=256:raise ValueError('Invalid modifiers')
            modifiers=_modifiers(encoded);event=int(mod[1]) if len(mod)>1 else 1
            if event not in (1,2,3):raise ValueError('Unknown key event')
            text=None
            if len(parts)>2 and parts[2]:
                values=[int(c) for c in parts[2].split(':')]
                if any(not 0<=v<=0x10ffff or 0xd800<=v<=0xdfff for v in values):raise ValueError('Invalid text scalar')
                text=''.join(map(chr,values))
            return _codepoint(cp,modifiers,('press','repeat','release')[event-1],text)
        modifier=int(parts[1]) if len(parts)>1 else 1
        if not 1<=modifier<=256:raise ValueError('Invalid modifiers')
        mods=_modifiers(modifier)
        if last in _ARROWS:
            if last=='Z':mods=mods|{'shift'}
            return KeyMsg(_ARROWS[last],modifiers=frozenset(mods))
        if last in 'PQRS':return KeyMsg('f'+str('PQRS'.index(last)+1),modifiers=mods)
        if last=='~' and parts:
            if parts[0]=='27' and len(parts)==3:return _codepoint(int(parts[2]),mods)
            return KeyMsg(_TILDE.get(int(parts[0]),'unknown'),modifiers=mods)
        return ProtocolMsg('unknown')
