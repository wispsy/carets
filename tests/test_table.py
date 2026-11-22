from dataclasses import replace
from unittest.mock import patch
import unittest

from carets import KeyMsg
from carets.components import TableModel
from carets.unicode import visual_width

try:
    from headless_spreadsheets import Cell, SourceColumn, SourceRow, TableSnapshot
except (ImportError, SyntaxError):
    TableSnapshot = None


@unittest.skipUnless(TableSnapshot, 'tables extra requires Python 3.14+')
class TableTests(unittest.TestCase):
    def snapshot(self):
        columns = tuple(SourceColumn('c'+str(i), 'Column '+str(i)) for i in range(12))
        rows = tuple(SourceRow('r'+str(i), str(i+1), tuple(Cell('界'+str(i)) for _ in columns), tuple('A'+str(i+1) for _ in columns)) for i in range(1000))
        return TableSnapshot('jobs', '1', columns, rows, generation=1)

    def test_identity_selection_resize_reorder_and_stale_generation(self):
        snapshot = self.snapshot()
        model = TableModel(snapshot, width=34, height=5).update(KeyMsg('end')).update(KeyMsg('right'))
        self.assertEqual((model.selection.row_key, model.selection.column_id, model.selection.revision), ('r999', 'c1', '1000'))
        model = model.with_snapshot(replace(snapshot, rows=tuple(reversed(snapshot.rows)), generation=2))
        self.assertEqual(model.selection.row_key, 'r999')
        self.assertEqual(model.row_offset, 0)
        reversed_columns = replace(model.snapshot, columns=tuple(reversed(snapshot.columns)),
            rows=tuple(replace(row, cells=tuple(reversed(row.cells)), source_addresses=tuple(reversed(row.source_addresses))) for row in model.snapshot.rows), generation=3)
        model = model.with_snapshot(reversed_columns)
        self.assertEqual(model.selection.column_id, 'c1')
        for width, height in ((0, 0), (1, 1), (12, 4), (90, 10)):
            changed = replace(model, width=width, height=height)
            self.assertLessEqual(len(changed.view().splitlines()), height)
            self.assertTrue(all(visual_width(line) <= width for line in changed.view().splitlines()))
        with self.assertRaises(ValueError):
            model.with_snapshot(snapshot)
        self.assertFalse(hasattr(model, 'set_cell'))
        self.assertEqual(snapshot.rows[-1].cells[0].value, '界999')

    def test_only_visible_cells_are_formatted_and_read_only_navigation_works(self):
        from headless_spreadsheets.serialization import scalar_text
        model = TableModel(self.snapshot(), width=35, height=5)
        with patch('headless_spreadsheets.serialization.scalar_text', wraps=scalar_text) as formatter:
            text = model.view()
        self.assertLessEqual(formatter.call_count, 6)
        self.assertIn('read only', text)
        self.assertEqual(model.update(KeyMsg('down')).selection.row_key, 'r1')
        self.assertEqual(model.update(KeyMsg('down', action='release')), model)
        self.assertEqual(replace(model, state=replace(model.state, disabled=True)).update(KeyMsg('down')).selected_key, 'r0')
