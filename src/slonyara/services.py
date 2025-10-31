"""Core service utilities for parsing configuration and checking user roles."""

from __future__ import annotations

from typing import Iterable, Iterator, Sequence


def parse_roles(
    raw_roles: str,
    *,
    separator: str = ",",
    normalizer: callable | None = str.lower,
    unique: bool = True,
    sort: bool = False,
) -> list[str]:
    """Parse a delimited string of roles into a cleaned list.

    Parameters
    ----------
    raw_roles:
        The raw string containing delimited role names.
    separator:
        The character or substring that separates items. Defaults to a comma.
    normalizer:
        A callable that normalises each role. By default, roles are lower-cased to make
        comparisons case insensitive. Pass ``None`` to keep the original casing.
    unique:
        If ``True`` duplicate entries are removed while preserving order. When ``False``
        duplicates are kept.
    sort:
        If ``True`` the resulting roles are sorted alphabetically after parsing.

    Returns
    -------
    list[str]
        A list of role names filtered from empty values and normalised according to the
        parameters above.

    Raises
    ------
    ValueError
        If ``raw_roles`` is ``None`` or an empty string after trimming separators.
    TypeError
        If ``normalizer`` is provided but is not callable.
    """

    if raw_roles is None:
        raise ValueError("raw_roles cannot be None")

    if normalizer is not None and not callable(normalizer):
        raise TypeError("normalizer must be callable or None")

    # Split using the provided separator and trim whitespace from each entry.
    parts = [part.strip() for part in raw_roles.split(separator)]
    roles: list[str] = []
    seen: set[str] = set()

    for part in parts:
        if not part:
            continue

        role = normalizer(part) if normalizer is not None else part

        if unique:
            if role in seen:
                continue
            seen.add(role)

        roles.append(role)

    if not roles:
        raise ValueError("raw_roles must contain at least one role")

    if sort:
        roles.sort()

    return roles


def _normalise_roles(
    roles: Iterable[str] | None, *, case_sensitive: bool, normalizer: callable | None
) -> Iterator[str]:
    if roles is None:
        return iter(())

    if normalizer is not None and not callable(normalizer):
        raise TypeError("normalizer must be callable or None")

    for role in roles:
        if role is None:
            continue

        if not isinstance(role, str):
            raise TypeError("roles must be strings")

        value = role if case_sensitive else role.lower()
        if normalizer is not None:
            value = normalizer(value)
        yield value


def check_roles(
    user_roles: Iterable[str],
    required_roles: Sequence[str] | Iterable[str],
    *,
    mode: str = "any",
    case_sensitive: bool = False,
    normalizer: callable | None = None,
) -> bool:
    """Validate that ``user_roles`` satisfies ``required_roles`` according to ``mode``.

    Parameters
    ----------
    user_roles:
        Roles associated with the user (any iterable of strings).
    required_roles:
        Roles that must be present. Empty iterables always return ``True``.
    mode:
        Either ``"any"`` (default) requiring at least one match, or ``"all"`` requiring
        every required role to be present.
    case_sensitive:
        Whether comparisons should respect casing. Defaults to ``False``.
    normalizer:
        Optional additional normaliser applied after the case handling.

    Returns
    -------
    bool
        ``True`` when the check passes, otherwise ``False``.

    Raises
    ------
    ValueError
        If ``mode`` is not ``"any"`` or ``"all"``.
    TypeError
        If ``user_roles`` or ``required_roles`` contain non-string values.
    """

    if mode not in {"any", "all"}:
        raise ValueError("mode must be either 'any' or 'all'")

    normalised_user = list(
        _normalise_roles(
            user_roles,
            case_sensitive=case_sensitive,
            normalizer=normalizer,
        )
    )
    normalised_required = list(
        _normalise_roles(
            required_roles,
            case_sensitive=case_sensitive,
            normalizer=normalizer,
        )
    )

    if not normalised_required:
        return True

    if not normalised_user:
        return False

    user_set = set(normalised_user)

    if mode == "any":
        return any(role in user_set for role in normalised_required)

    # mode == "all"
    return all(role in user_set for role in normalised_required)
