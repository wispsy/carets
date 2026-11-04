# Declarative forms, field schemas, and validation helpers.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

Validator = Callable[[Any], str | None]


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
    fields: tuple[InputField | SelectField | ConfirmField, ...]
    title: str = ""

    def __init__(self, fields: Iterable[InputField | SelectField | ConfirmField], title: str = "") -> None:
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "title", title)


@dataclass
class Form:
    groups: tuple[Group, ...]
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)

    def __init__(self, groups: Iterable[Group]) -> None:
        self.groups = tuple(groups)
        self.values = {field.name: field.value for group in self.groups for field in group.fields}
        self.errors = {}

    def validate(self, values: dict[str, Any] | None = None) -> bool:
        if values:
            self.values.update(values)
        self.errors = {}
        for group in self.groups:
            for field in group.fields:
                current = field
                value = self.values.get(field.name)
                if value != field.value:
                    current = type(field)(field.name, field.label, value, field.validators)  # type: ignore[call-arg]
                errors = current.validate()
                if errors:
                    self.errors[field.name] = errors
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)
