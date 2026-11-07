import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.name == "posix", "Native POSIX terminal input")
class NativeInputTests(unittest.TestCase):
    def test_one_key_on_buffered_stdin_does_not_block_the_event_loop(self):
        import pty
        import select

        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("native_input_worker.py"))],
                                   stdin=slave, stderr=slave, stdout=subprocess.PIPE)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], "Worker did not start")
            self.assertEqual(process.stdout.readline().strip(), b"READY")
            os.write(master, b"a")
            output, _ = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, output)
            self.assertIn(b"GOT:a", output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            os.close(master)
            os.close(slave)
