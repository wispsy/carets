# Typed forms and application services

Existing InputField, SelectField and ConfirmField declarations keep their API.
TypedField adds a selected converter, default, optional/password flags, validators,
async_validators and an optional when(raw_values) condition. Missing required fields
produce incomplete results; conversion/validation errors produce invalid results.
submit/asubmit return FormResult(status, typed values, field errors); cancel returns
cancelled. Successful forms are valid. Values/results are copied for the caller.

Form.validate remains the synchronous boolean API; avalidate/asubmit await async
field and cross-field validators. Cross validators return mappings from affected
field names (or __all__) to messages. Unknown field names are configuration errors.
Validation timing is submit by default; change/blur can be selected and update
applies validation at that event. Async hosts call avalidate for their chosen event.
display masks password fields; submit results intentionally include the typed value
for the selected application. Converters/validators are trusted host code, never
loaded from a form document. Conditions see raw values before conversion.

ApplicationContext holds caller-selected config, services and an optional logger.
load_config reads one bounded strict JSON object without activating services. log
adds event/fields metadata and redacts password/secret/token/api_key field names,
including nested records. Avoid placing credentials in arbitrary text fields.
report_crash writes only the error type to an explicitly selected stream outside
the rendered terminal. No global logging configuration or terminal is required.
