from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy

import pytest

from cryodaq.channels.config import (
    ChannelConfigError,
    parse_channel_catalog,
    parse_channel_descriptor,
)
from cryodaq.channels.descriptors import ChannelQuantity


def _payload(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "Т1",
        "instrument_id": "lakeshore-main",
        "source_key": "input.1.temperature",
        "quantity": "temperature",
        "unit": "K",
        "role": "primary_measurement",
        "safety_class": "observational",
        "display_group": "Криостат",
        "display_name": "Азотная плита",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 1,
    }
    value.update(changes)
    return value


def test_parser_freezes_a_mutable_fixture_without_retaining_aliases() -> None:
    payload = [_payload()]
    original = deepcopy(payload)
    catalog = parse_channel_catalog(payload)
    payload[0]["display_name"] = "mutated"
    payload.append(_payload(channel_id="P1"))
    assert catalog.descriptors[0].display_name == original[0]["display_name"]
    assert len(catalog.descriptors) == 1
    assert catalog.descriptors[0].quantity is ChannelQuantity.TEMPERATURE


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        "descriptor",
        {_payload()["channel_id"]},
        [None],
        [{**_payload(), "private": "forbidden"}],
        [{key: value for key, value in _payload().items() if key != "unit"}],
        [{**_payload(), "quantity": "Temperature"}],
        [{**_payload(), "role": 1}],
        [{**_payload(), "safety_class": "source"}],
    ],
)
def test_parser_rejects_nonclosed_or_malformed_fixtures(payload: object) -> None:
    with pytest.raises(ChannelConfigError):
        parse_channel_catalog(payload)


def test_parser_paths_identify_the_exact_bad_entry_without_values() -> None:
    with pytest.raises(ChannelConfigError, match=r"channel_descriptors\[1\]"):
        parse_channel_catalog([_payload(), _payload(channel_id="P1", source_key="bad/source")])


def test_parse_one_requires_exact_closed_shape() -> None:
    descriptor = parse_channel_descriptor(_payload(), path="fixture.channel")
    assert descriptor.channel_id == "Т1"
    with pytest.raises(ChannelConfigError, match="missing"):
        parse_channel_descriptor({"schema_version": 1})


def test_catalog_fixture_rejects_duplicate_source_or_channel() -> None:
    with pytest.raises(ChannelConfigError, match="duplicate current channel_id"):
        parse_channel_catalog([_payload(), _payload(descriptor_revision=2, display_name="new")])
    with pytest.raises(ChannelConfigError, match="instrument/source identity anchor fork"):
        parse_channel_catalog([_payload(), _payload(channel_id="Т2")])


def test_parser_rejects_string_subclass_keys_and_values() -> None:
    class Text(str):
        pass

    payload = _payload()
    payload["display_name"] = Text("mutable")
    with pytest.raises(ChannelConfigError, match="display_name"):
        parse_channel_descriptor(payload)
    hostile_key = {
        Text("schema_version"): 1,
        **{key: value for key, value in _payload().items() if key != "schema_version"},
    }
    with pytest.raises(ChannelConfigError, match="keys must be strings"):
        parse_channel_descriptor(hostile_key)


def test_parser_normalizes_hostile_mapping_read_failures() -> None:
    class HostileMapping(Mapping[str, object]):
        def __getitem__(self, key: str) -> object:
            raise KeyError(key)

        def __iter__(self) -> Iterator[str]:
            return iter(_payload())

        def __len__(self) -> int:
            return len(_payload())

        def items(self):
            raise KeyError("mutated")

    with pytest.raises(ChannelConfigError, match="could not be read atomically"):
        parse_channel_descriptor(HostileMapping())
