"""
Role hierarchy and expansion logic.

admin is a superset — it expands to include all roles so it passes
every ChromaDB metadata filter automatically.
"""

ROLE_HIERARCHY: dict[str, list[str]] = {
    "admin":    ["admin", "hr", "finance", "engineer", "intern"],
    "hr":       ["hr", "intern"],
    "finance":  ["finance", "intern"],
    "engineer": ["engineer", "intern"],
    "intern":   ["intern"],
}

ALL_ROLES = list(ROLE_HIERARCHY.keys())


def expand_roles(roles: list[str]) -> list[str]:
    """Return the full set of role labels a user is allowed to access."""
    expanded: set[str] = set()
    for role in roles:
        expanded.update(ROLE_HIERARCHY.get(role, [role]))
    return list(expanded)
