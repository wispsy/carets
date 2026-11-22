from pathlib import Path
import unittest
from carets.unicode import graphemes,cell_width,visual_width,clip_text

class UnicodeTests(unittest.TestCase):
    def test_official_unicode_18_grapheme_conformance(self):
        cases=0
        path=Path(__file__).parent/'fixtures/GraphemeBreakTest-18.0.0.txt'
        for line in path.read_text(encoding='utf-8').splitlines():
            raw=line.split('#',1)[0].strip()
            if not raw:continue
            expected=[];current=''
            for token in raw.split():
                if token=='÷':
                    if current:expected.append(current);current=''
                elif token!='×':current+=chr(int(token,16))
            text=''.join(expected);self.assertEqual(list(graphemes(text)),expected,line);cases+=1
        self.assertGreater(cases,700)

    def test_width_clipping_emoji_combining_and_styles(self):
        for text,width in [('e\u0301',1),('👩🏽\u200d💻',2),('🇺🇸',2),('界',2),('❤️',2),('क्\u200dष',1)]:
            self.assertEqual(visual_width(text),width,text)
            self.assertEqual(clip_text(text+'x',width),text)
        self.assertEqual(clip_text('abcdef',4,ellipsis='…'),'abc…')
        clipped=clip_text('\x1b[31m界界界\x1b[0m',3,ellipsis='…')
        self.assertEqual(visual_width(clipped),3);self.assertTrue(clipped.endswith('\x1b[0m'))
        self.assertEqual(cell_width('\u0301'),0)
