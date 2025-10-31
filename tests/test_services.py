import pytest

from slonyara.services import check_roles, parse_roles


def test_parse_roles_strips_and_lowercases_by_default():
    assert parse_roles("Admin, User , editor") == ["admin", "user", "editor"]


def test_parse_roles_handles_duplicates_when_unique_false():
    assert parse_roles("admin,admin,User", unique=False) == ["admin", "admin", "user"]


def test_parse_roles_raises_for_empty_values():
    with pytest.raises(ValueError):
        parse_roles(" ,   ,   ")


def test_parse_roles_custom_separator_and_sort():
    assert parse_roles("admin|manager|viewer", separator="|", sort=True) == [
        "admin",
        "manager",
        "viewer",
    ]


def test_parse_roles_custom_normalizer():
    assert parse_roles("Admin,User", normalizer=lambda v: v.upper()) == ["ADMIN", "USER"]


def test_check_roles_any_mode_default_case_insensitive():
    user_roles = parse_roles("Admin,Editor")
    assert check_roles(user_roles, ["editor"]) is True
    assert check_roles(user_roles, ["viewer"]) is False


def test_check_roles_all_mode_requires_every_role():
    user_roles = parse_roles("Admin,Editor,Auditor")
    assert check_roles(user_roles, ["editor", "admin"], mode="all") is True
    assert check_roles(user_roles, ["editor", "viewer"], mode="all") is False


def test_check_roles_case_sensitive():
    user_roles = parse_roles("Admin,Editor", normalizer=None)
    assert check_roles(user_roles, ["Admin"], case_sensitive=True, normalizer=None) is True
    assert check_roles(user_roles, ["admin"], case_sensitive=True, normalizer=None) is False


def test_check_roles_empty_required_returns_true():
    assert check_roles(["admin"], []) is True


def test_check_roles_invalid_mode():
    with pytest.raises(ValueError):
        check_roles(["admin"], ["admin"], mode="invalid")


def test_check_roles_non_string_values_raise_type_error():
    with pytest.raises(TypeError):
        check_roles(["admin", 123], ["admin"])  # type: ignore[list-item]

    with pytest.raises(TypeError):
        check_roles(["admin"], ["admin", 42])  # type: ignore[list-item]


def test_check_roles_respects_custom_normalizer():
    user_roles = ["TEAM:DEVOPS", "TEAM:QA"]
    def normalizer(value: str) -> str:
        return value.split(":")[-1]

    assert check_roles(user_roles, ["devops"], normalizer=normalizer) is True

