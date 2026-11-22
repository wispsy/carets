import asyncio
from dataclasses import dataclass,replace
import io
import unittest
from carets import Command,KeyMsg,Msg,Program
from carets.testing import TestProgram
from carets.renderer import CellDiffRenderer,Cursor

class FrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_coalesce_keeps_updates_responsive_and_flushes_final(self):
        class Model:
            def __init__(self):self.values=[]
            def update(self,msg):
                if isinstance(msg,KeyMsg):self.values.append(msg.key)
            def view(self):return ','.join(self.values)
        model=Model()
        async with TestProgram(model,frame_interval=1) as test:
            initial=len(test.renderer.frames)
            await test.send(*(KeyMsg(str(i)) for i in range(100)),KeyMsg('cancel'))
            self.assertEqual(len(model.values),101)
            self.assertEqual(len(test.renderer.frames),initial)
            await test.advance(1)
            self.assertEqual(len(test.renderer.frames),initial+1)
            self.assertTrue(test.renderer.latest.endswith('cancel'))
            await test.send(KeyMsg('final'))
        self.assertTrue(test.renderer.latest.endswith('final'))
        self.assertEqual(len(test.renderer.frames),initial+2)

    async def test_stream_pressure_orders_every_message_and_final_frame(self):
        class Model:
            def __init__(self):self.values=[];self.program=None
            def update(self,msg):
                self.values.append(msg.key)
                if msg.key=='done':self.program.stop()
            def view(self):return str(len(self.values))
        async def source():
            for n in range(300):yield KeyMsg(str(n))
            yield KeyMsg('done')
        model=Model();out=io.StringIO()
        renderer=CellDiffRenderer(10,1);model.program=Program(model,renderer=renderer,output_stream=out,frame_interval=60,stream_buffer=4)
        await model.program.run([],stop_on_eof=False,commands=[Command.stream(source)])
        self.assertEqual(model.values,[str(n) for n in range(300)]+['done'])
        self.assertEqual(renderer.previous.to_text(),'301')
        self.assertFalse(model.program._frame_tasks)

    async def test_immutable_root_models_and_cursor_cleanup(self):
        @dataclass(frozen=True)
        class Counter:
            count:int=0
            def update(self,msg):return replace(self,count=self.count+1)
            def view(self):return str(self.count)
        original=Counter();renderer=CellDiffRenderer(3,1);renderer.render('x',cursor=Cursor(0,0,True))
        output=io.StringIO();program=Program(original,renderer=renderer,output_stream=output)
        result=await program.run([KeyMsg('a'),KeyMsg('b')])
        self.assertEqual((original.count,result.count),(0,2))
        self.assertTrue(output.getvalue().endswith('\x1b[0 q\x1b[?25h'))
