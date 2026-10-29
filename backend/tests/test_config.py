"""配置校验：类型、范围、枚举（F7 的核心逻辑）。"""

from __future__ import annotations

import pytest

from kbqa.config.service import ConfigError, _coerce
from kbqa.infra.db import models as m


def _row(**kw) -> m.AppConfig:
    base = dict(config_key="x.y", config_value=None, default_value=None,
                value_type="int", group_name="retrieval", description="d",
                min_value=None, max_value=None, enum_values=None,
                hot_reloadable=True)
    base.update(kw)
    return m.AppConfig(**base)


def test_int_ok_and_bounds():
    r = _row(value_type="int", min_value=1, max_value=10)
    assert _coerce(r, 5) == 5
    with pytest.raises(ConfigError, match="不得大于"):
        _coerce(r, 11)
    with pytest.raises(ConfigError, match="不得小于"):
        _coerce(r, 0)


def test_int_rejects_float_and_bool():
    r = _row(value_type="int")
    with pytest.raises(ConfigError, match="整数"):
        _coerce(r, 5.5)
    with pytest.raises(ConfigError, match="整数"):
        _coerce(r, True)          # bool 是 int 子类，必须单独拦


def test_float_coerces_int():
    r = _row(value_type="float", min_value=0, max_value=1)
    assert _coerce(r, 1) == 1.0
    assert _coerce(r, 0.35) == 0.35
    with pytest.raises(ConfigError):
        _coerce(r, "0.5")


def test_bool_strict():
    r = _row(value_type="bool")
    assert _coerce(r, True) is True
    with pytest.raises(ConfigError, match="布尔"):
        _coerce(r, 1)


def test_enum_membership():
    r = _row(value_type="enum", enum_values=["structure", "fixed"])
    assert _coerce(r, "fixed") == "fixed"
    with pytest.raises(ConfigError, match="只能是"):
        _coerce(r, "semantic")


def test_str_and_json():
    assert _coerce(_row(value_type="str"), "deepseek-chat") == "deepseek-chat"
    with pytest.raises(ConfigError):
        _coerce(_row(value_type="str"), 123)

    j = _row(value_type="json")
    assert _coerce(j, ["md", "pdf"]) == ["md", "pdf"]
    with pytest.raises(ConfigError, match="JSON"):
        _coerce(j, "md,pdf")


def test_unknown_type_rejected():
    with pytest.raises(ConfigError, match="未知类型"):
        _coerce(_row(value_type="datetime"), "2026-01-01")
