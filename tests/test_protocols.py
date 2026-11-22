import asyncio
import unittest
from carets.input import AnsiInputParser
from carets.runtime import FocusMsg,KeyMsg,MouseMsg,ProtocolMsg

class ProtocolTests(unittest.TestCase):
    def test_arbitrary_byte_fragments_match_complete_input(self):
        raw='é\x1bOP\x1b[1;5A\x1b[15~\x1b[97:65;2:2;65u\x1b[57350;5:3u\x1b[I\x1b[O\x1b[<32;2;3M\x1b[<35;4;5M\x1b[<66;1;1M\x1b[200~👩🏽\u200d💻\n\x1b[A\x1b[201~q'.encode()
        p=AnsiInputParser();expected=p.feed(raw)+p.finish()
        for split in range(len(raw)+1):
            p=AnsiInputParser();actual=p.feed(raw[:split])+p.feed(raw[split:])+p.finish()
            self.assertEqual(actual,expected,split)
        self.assertIn(KeyMsg('f1'),expected)
        self.assertIn(KeyMsg('up',modifiers=frozenset({'ctrl'})),expected)
        self.assertIn(KeyMsg('a','A',frozenset({'shift'}),'repeat'),expected)
        self.assertIn(KeyMsg('left',modifiers=frozenset({'ctrl'}),action='release'),expected)
        self.assertIn(FocusMsg(True),expected);self.assertIn(MouseMsg(1,2,'left','drag'),expected)
        self.assertIn(MouseMsg(3,4,'none','move'),expected)

    def test_bounded_paste_unknown_recovery_and_unterminated_data(self):
        p=AnsiInputParser(max_sequence=16,max_paste_bytes=5)
        events=p.feed('\x1b['+'9'*100)+p.feed('~x\x1b[200~ééé\x1b[201~z')+p.finish()
        self.assertEqual(events,[ProtocolMsg('malformed'),KeyMsg('x','x'),KeyMsg('paste','éé',truncated=True),KeyMsg('z','z')])
        p=AnsiInputParser();self.assertEqual(p.feed('\x1b[200~hi')+p.finish(),[KeyMsg('paste','hi',truncated=True)])
        p=AnsiInputParser();self.assertEqual(p.feed('\x1b]52;bad\x07q'),[ProtocolMsg('unknown'),KeyMsg('q','q')])
        p=AnsiInputParser();self.assertEqual(p.feed('\x1b[12\x1b[Aq'),[ProtocolMsg('malformed'),KeyMsg('up'),KeyMsg('q','q')])

    def test_malformed_numeric_keys_do_not_raise_or_lose_following_input(self):
        for sequence in ('\x1b[u','\x1b[97;0u','\x1b[97;1;55296u','\x1b[<0;0;2M'):
            p=AnsiInputParser();events=p.feed(sequence+'q')+p.finish()
            self.assertEqual(events,[ProtocolMsg('malformed'),KeyMsg('q','q')])

class EscapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_escape_timeout_and_close(self):
        p=AnsiInputParser(escape_timeout=0)
        self.assertEqual(p.feed(b'\x1b'),[])
        self.assertEqual(await asyncio.wait_for(anext(p),1),KeyMsg('escape'))
        p.close()
        with self.assertRaises(StopAsyncIteration):await anext(p)

class ProtocolOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_negotiation_and_paired_cleanup(self):
        from carets import Program,TerminalOptions,TerminalSession
        from carets.testing import FakeTerminal
        terminal=FakeTerminal()
        options=TerminalOptions(keyboard_protocol='auto',focus_events=True,mouse=True,mouse_motion=True)
        session=TerminalSession(terminal.input,terminal.output,backend=terminal,options=options)
        class Model:
            def update(self,message):pass
            def view(self):return ''
        await Program(Model(),terminal=session).run([ProtocolMsg('kitty',0),ProtocolMsg('kitty',0)])
        text=terminal.output.getvalue()
        self.assertIn('\x1b[?u',text);self.assertEqual(text.count('\x1b[>3u'),1)
        self.assertEqual(text.count('\x1b[<u'),1)
        for mode in (1003,1004):self.assertIn(f'\x1b[?{mode}h',text);self.assertIn(f'\x1b[?{mode}l',text)
        self.assertEqual(terminal.restore_count,1)
