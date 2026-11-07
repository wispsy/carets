# Declarative forms, field schemas, and validation helpers.

from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
import inspect
from typing import Any, Callable, Iterable

Validator = Callable[[Any], str | None]
_MISSING = object()


@dataclass(frozen=True)
class TypedField:
    name: str
    label: str
    convert: Callable = str
    default: Any = _MISSING
    optional: bool = False
    password: bool = False
    validators: tuple = ()
    async_validators: tuple = ()
    when: Callable | None = None

    def __post_init__(self):
        if not callable(self.convert) or (self.when is not None and not callable(self.when)):
            raise TypeError("Converters and conditions must be callable")
        if type(self.optional) is not bool or type(self.password) is not bool:
            raise TypeError("Field flags must be booleans")


@dataclass(frozen=True)
class FormResult:
    status: str
    values: dict
    errors: dict


@dataclass(frozen=True)
class InputField:
    name: str
    label: str
    value: str = ""
    validators: tuple[Validator, ...] = ()

    def validate(self) -> list[str]:
        return [error for validator in self.validators if (error := validator(self.value))]


@dataclass(frozen=True)
class SelectField:
    name: str
    label: str
    options: tuple[Any, ...] = ()
    value: Any = None
    validators: tuple[Validator, ...] = ()

    def __init__(self, name: str, label: str, options: Iterable[Any] = (), value: Any = None, validators: Iterable[Validator] = ()) -> None:
        option_values = tuple(options)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "options", option_values)
        object.__setattr__(self, "value", value if value is not None else (option_values[0] if option_values else None))
        object.__setattr__(self, "validators", tuple(validators))

    def validate(self) -> list[str]:
        errors = [error for validator in self.validators if (error := validator(self.value))]
        if self.value not in self.options:
            errors.append(f"{self.label} must be one of the available options")
        return errors


@dataclass(frozen=True)
class ConfirmField:
    name: str
    label: str
    value: bool = False
    validators: tuple[Validator, ...] = ()

    def validate(self) -> list[str]:
        return [error for validator in self.validators if (error := validator(self.value))]


@dataclass(frozen=True)
class Group:
    fields: tuple[InputField | SelectField | ConfirmField | TypedField, ...]
    title: str = ""

    def __init__(self, fields: Iterable[InputField | SelectField | ConfirmField | TypedField], title: str = "") -> None:
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "title", title)


@dataclass
class Form:
    groups: tuple[Group, ...]
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)

    def __init__(self, groups: Iterable[Group], *, validators=(), async_validators=(), validate_on="submit") -> None:
        self.groups = tuple(groups)
        self._fields = {field.name: field for group in self.groups for field in group.fields}
        if len(self._fields) != sum(len(group.fields) for group in self.groups):
            raise ValueError("Field names must be unique")
        if validate_on not in ("submit", "change", "blur"):
            raise ValueError("Validation timing must be submit, change or blur")
        self.validate_on = validate_on
        self.validators, self.async_validators = tuple(validators), tuple(async_validators)
        self._raw = {}
        for field in self._fields.values():
            value = field.default if isinstance(field, TypedField) else field.value
            if value is not _MISSING:
                self._raw[field.name] = deepcopy(value)
        self.values = deepcopy(self._raw)
        self.errors = {}
        self.status = "incomplete"

    def update(self, name, value, *, event="change"):
        if name not in self._fields:
            raise KeyError(name)
        self._raw[name] = deepcopy(value)
        self.status = "incomplete"
        return self.validate() if event == self.validate_on else None

    def display(self, name):
        value = str(self._raw.get(name, ""))
        return "*" * len(value) if getattr(self._fields[name], "password", False) else value

    def _merge(self, errors):
        if errors is None:
            return
        if not isinstance(errors, dict) or any(name not in self._fields and name != "__all__" for name in errors):
            raise ValueError("Cross-field errors must identify declared fields or __all__")
        for name, values in errors.items():
            values = [values] if isinstance(values, str) else list(values)
            if any(not isinstance(value, str) for value in values):
                raise TypeError("Validation messages must be strings")
            self.errors.setdefault(name, []).extend(values)

    def _sync(self, result):
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise RuntimeError("Async validation requires avalidate/asubmit and async_validators")
        return result

    def _prepare(self, values):
        if values is not None:
            if set(values) - self._fields.keys():
                raise ValueError("Unknown form fields")
            self._raw.update(deepcopy(values))
        self.errors, self.values, self._active = {}, {}, []
        self._missing = False
        for field in self._fields.values():
            if isinstance(field, TypedField) and field.when is not None and not field.when(deepcopy(self._raw)):
                continue
            self._active.append(field)
            if field.name not in self._raw:
                if isinstance(field, TypedField) and field.optional:
                    self.values[field.name] = None
                else:
                    self.errors[field.name] = ["Required value is missing"]
                    self._missing = True
                continue
            value = deepcopy(self._raw[field.name])
            if isinstance(field, TypedField):
                try:
                    if field.optional and value in (None, ""):
                        value = None
                    elif field.convert is bool:
                        if type(value) is not bool and value not in ("true", "false"):
                            raise ValueError
                        value = value if type(value) is bool else value == "true"
                    else:
                        value = field.convert(value)
                except (ValueError, TypeError, OverflowError):
                    self.errors[field.name] = ["Invalid value"]
                    continue
                errors = [self._sync(validator(value)) for validator in field.validators]
            else:
                errors = replace(field, value=value).validate()
            self.values[field.name] = value
            errors = [self._sync(error) for error in errors if error]
            if errors:
                self.errors[field.name] = errors
        for validator in self.validators:
            self._merge(self._sync(validator(deepcopy(self.values))))

    def _finish(self):
        self.status = "incomplete" if self._missing else "invalid" if self.errors else "valid"
        return not self.errors

    def validate(self, values: dict[str, Any] | None = None) -> bool:
        if self.async_validators or any(getattr(field, "async_validators", ()) for field in self._fields.values()):
            raise RuntimeError("Use avalidate/asubmit for async validators")
        self._prepare(values)
        return self._finish()

    async def avalidate(self, values=None):
        self._prepare(values)
        for field in self._active:
            if field.name in self.errors or field.name not in self.values:
                continue
            for validator in getattr(field, "async_validators", ()):
                result = validator(deepcopy(self.values[field.name]))
                if inspect.isawaitable(result):
                    result = await result
                if result:
                    self.errors.setdefault(field.name, []).append(result)
        for validator in self.async_validators:
            result = validator(deepcopy(self.values))
            self._merge(await result if inspect.isawaitable(result) else result)
        return self._finish()

    def result(self):
        return FormResult(self.status, deepcopy(self.values), deepcopy(self.errors))

    def submit(self, values=None):
        self.validate(values)
        return self.result()

    async def asubmit(self, values=None):
        await self.avalidate(values)
        return self.result()

    def cancel(self):
        self.status = "cancelled"
        return self.result()

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self.values)
