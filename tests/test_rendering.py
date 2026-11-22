import unittest
from carets.renderer import CellDiffRenderer,Cursor,ScreenBuffer
from carets.layout import Rect
from carets.style import Style,visual_width

class RenderingTests(unittest.TestCase):
    def test_wide_cells_clipping_overwrite_and_mutable_buffer_snapshot(self):
        frame=ScreenBuffer(5,1);frame.write(0,0,'界e\u0301👩🏽\u200d💻')
        self.assertEqual([c.width for c in frame.cells[0]],[2,0,1,2,0])
        renderer=CellDiffRenderer(5,1);first=renderer.render(frame)
        self.assertIn('界e\u0301👩🏽\u200d💻',first)
        frame.write(1,0,'x');second=renderer.render(frame)
        self.assertIn(' x',second);self.assertEqual(renderer.previous.cells[0][0].char,' ')
        frame.write(4,0,'界');self.assertNotEqual(frame.cells[0][4].char,'界')

    def test_layers_resize_cursor_and_full_redraw(self):
        base=ScreenBuffer(6,2);base.write(0,0,'abcdef')
        layer=ScreenBuffer(3,1);layer.write(0,0,'界x');base.blit(layer,2,0,clip=Rect(0,0,4,2))
        self.assertEqual(base.to_text().splitlines()[0],'ab界ef')
        renderer=CellDiffRenderer(6,2,synchronized=False)
        self.assertIn('\x1b[?25h',renderer.render(base,cursor=Cursor(1,0,True,'bar')))
        renderer.invalidate();self.assertIn('\x1b[2J',renderer.render(base))
        renderer.resize(2,1);self.assertIn('\x1b[2J',renderer.render('xy'))
        self.assertIn('\x1b[?25l',renderer.render('xy',cursor=Cursor()))
        renderer.render('ab',cursor=Cursor(1,0,True))
        self.assertIn('\x1b[1;2H',renderer.render('cd'))
        self.assertIn('\x1b[0 q',renderer.close());self.assertEqual(renderer.close(),'')

    def test_color_fallback_and_balanced_style_boxes(self):
        text=Style(foreground='#ff0000',background=(0,0,255),bold=True,width=3,height=1,padding=(1,1,1,1)).render('界界')
        self.assertEqual(len(text.splitlines()),3)
        self.assertTrue(all(visual_width(line)==5 for line in text.splitlines()))
        buffer=ScreenBuffer(3,1);buffer.from_lines([text.splitlines()[1]])
        for depth,code in ((24,'38;2;255;0;0'),(8,'38;5;9'),(4,'91')):
            output=CellDiffRenderer(3,1,color_depth=depth).render(buffer)
            self.assertIn(code,output);self.assertIn('\x1b[0m',output)
        plain=CellDiffRenderer(3,1,ansi=False).render(buffer)
        self.assertNotIn('\x1b',plain)
