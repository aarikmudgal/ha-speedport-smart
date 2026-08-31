"""Telekom ToTR64 SOAP encoding and parsing."""

from __future__ import annotations

from collections.abc import Sequence
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ..models import ParameterValue
from .exceptions import (
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)

SOAP_ACTION = "urn:telekom-de:device:TO_InternetGatewayDevice:2#GetParameterValues"
_INTEGER_TYPES = {
    "byte",
    "int",
    "integer",
    "long",
    "negativeinteger",
    "nonnegativeinteger",
    "nonpositiveinteger",
    "positiveinteger",
    "short",
    "unsignedbyte",
    "unsignedint",
    "unsignedlong",
    "unsignedshort",
}
_FLOAT_TYPES = {"decimal", "double", "float"}


def build_get_parameter_values(names: Sequence[str]) -> str:
    """Build tested ToTR64 GetParameterValues request body."""
    if not names:
        msg = "GetParameterValues requires at least one parameter name"
        raise ValueError(msg)
    parameters = "".join(f"<xsd:string>{escape(name)}</xsd:string>" for name in names)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<soap-env:Envelope "
        'xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:cwmp="urn:telekom-de.totr64-2-n">'
        "<soap-env:Body>"
        '<cwmp:GetParameterValues xmlns:cwmp="urn:dslforum-org:cwmp-1-0">'
        f'<cwmp:ParameterNames length="{len(names)}">'
        f"{parameters}"
        "</cwmp:ParameterNames>"
        "</cwmp:GetParameterValues>"
        "</soap-env:Body>"
        "</soap-env:Envelope>"
    )


def parse_get_parameter_values(payload: str) -> dict[str, ParameterValue]:
    """Parse ToTR64 response or raise typed SOAP fault."""
    try:
        root = ET.fromstring(payload)  # noqa: S314 - bounded local-router response
    except ET.ParseError as exc:
        msg = "Router returned malformed ToTR64 XML"
        raise SpeedportProtocolError(msg) from exc

    fault = next(
        (node for node in root.iter() if _local_name(node.tag) == "Fault"),
        None,
    )
    if fault is not None:
        _raise_fault(fault)

    result: dict[str, ParameterValue] = {}
    for structure in root.iter():
        if _local_name(structure.tag) not in {
            "ParameterValueStruct",
            "ParameterValue",
        }:
            continue
        name_node = next(
            (child for child in structure if _local_name(child.tag) == "Name"),
            None,
        )
        value_node = next(
            (child for child in structure if _local_name(child.tag) == "Value"),
            None,
        )
        if name_node is None or value_node is None or not name_node.text:
            continue
        data_type = next(
            (
                value
                for key, value in value_node.attrib.items()
                if _local_name(key) == "type"
            ),
            None,
        )
        text = value_node.text or ""
        name = name_node.text.strip()
        result[name] = ParameterValue(
            name=name,
            value=_convert_value(text, data_type),
            data_type=data_type,
        )
    if not result:
        msg = "ToTR64 response contained no parameter values"
        raise SpeedportProtocolError(msg)
    return result


def _raise_fault(fault: ET.Element) -> None:
    values: dict[str, str] = {}
    for node in fault.iter():
        if node.text and node.text.strip():
            values[_local_name(node.tag).casefold()] = node.text.strip()
    code = values.get("faultcode", "")
    detail_code = values.get("faultcode", "")
    for key in ("errorcode", "fault_code", "code"):
        detail_code = values.get(key, detail_code)
    combined = " ".join(values.values())
    description = (
        values.get("faultstring")
        or values.get("faultdescription")
        or values.get("description")
        or "Unknown SOAP fault"
    )
    if "9801" in combined:
        raise SpeedportSessionBusyError("ToTR64 session busy (fault 9801)")
    if any(token in combined for token in ("9005", "Invalid Parameter Name")):
        raise SpeedportUnsupportedError(
            f"ToTR64 parameter unsupported ({detail_code or code}): {description}"
        )
    raise SpeedportProtocolError(
        f"ToTR64 SOAP fault ({detail_code or code or 'unknown'}): {description}"
    )


def _convert_value(text: str, data_type: str | None) -> str | int | float | bool:
    value = text.strip()
    normalized_type = (data_type or "").rsplit(":", 1)[-1].casefold()
    if normalized_type in _INTEGER_TYPES:
        try:
            return int(value)
        except ValueError:
            return value
    if normalized_type in _FLOAT_TYPES:
        try:
            return float(value)
        except ValueError:
            return value
    if normalized_type in {"bool", "boolean"}:
        if value.casefold() in {"1", "true", "yes", "on"}:
            return True
        if value.casefold() in {"0", "false", "no", "off"}:
            return False
    return value


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]
