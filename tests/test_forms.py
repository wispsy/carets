import asyncio
import io
import logging
from pathlib import Path
import tempfile
import unittest

from carets import ApplicationContext, Form, Group, SelectField, TypedField, load_config


class FormTests(unittest.TestCase):
    def test_typed_defaults_optional_conditional_password_and_states(self):
        form = Form([Group([TypedField("count", "Count", int), TypedField("note", "Note", optional=True),
            TypedField("password", "Password", default="private", password=True),
            TypedField("extra", "Extra", int, when=lambda values: values.get("count") == "2")])])
        self.assertEqual(form.submit().status, "incomplete")
        self.assertEqual(form.submit({"count": "bad"}).status, "invalid")
        self.assertEqual(form.submit({"count": "2"}).status, "incomplete")
        result = form.submit({"extra": "4"})
        self.assertEqual((result.status, result.values["count"], result.values["extra"], result.values["note"]), ("valid", 2, 4, None))
        self.assertEqual(form.display("password"), "*******")
        self.assertEqual(form.cancel().status, "cancelled")
        result.values.clear()
        self.assertEqual(form.as_dict()["count"], 2)

    def test_cross_field_errors_timing_and_existing_select_update(self):
        form = Form([Group([TypedField("a", "A", int, default=1), TypedField("b", "B", int, default=2)])],
            validators=[lambda values: {"b": "Must exceed a"} if values.get("b", 0) <= values.get("a", 0) else None], validate_on="blur")
        self.assertIsNone(form.update("b", "0"))
        self.assertFalse(form.update("b", "0", event="blur"))
        self.assertEqual(form.errors, {"b": ["Must exceed a"]})
        selection = Form([Group([SelectField("choice", "Choice", ["a", "b"], "a")])])
        self.assertTrue(selection.validate({"choice": "b"}))
        self.assertEqual(selection.as_dict(), {"choice": "b"})

    def test_services_load_config_redact_logs_and_keep_crash_output_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"name":"example"}')
            self.assertEqual(load_config(path), {"name": "example"})
            for value in ('{"a":1,"a":2}', '{"a":1e999}', '[1]'):
                path.write_text(value)
                with self.assertRaises(ValueError): load_config(path)
        records = []
        class Handler(logging.Handler):
            def emit(self, record): records.append(record)
        logger = logging.Logger("form-test")
        logger.addHandler(Handler())
        context = ApplicationContext(services={"chosen": object()}, logger=logger)
        context.log("configured", token="private", nested={"password": "private", "count": 2})
        self.assertEqual(records[0].fields["token"], "[redacted]")
        self.assertEqual(records[0].fields["nested"], {"password": "[redacted]", "count": 2})
        stream = io.StringIO()
        context.report_crash(RuntimeError("private"), stream)
        self.assertNotIn("private", stream.getvalue())


class AsyncFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_field_and_cross_validation_without_terminal(self):
        async def available(value):
            await asyncio.sleep(0)
            return "Already selected" if value == "taken" else None
        async def together(values):
            return {"name": "Name required"} if values.get("name") == "" else None
        form = Form([Group([TypedField("name", "Name", async_validators=(available,))])], async_validators=(together,))
        with self.assertRaises(RuntimeError): form.validate({"name": "taken"})
        result = await form.asubmit({"name": "taken"})
        self.assertEqual((result.status, result.errors), ("invalid", {"name": ["Already selected"]}))
        self.assertEqual((await form.asubmit({"name": "free"})).status, "valid")
