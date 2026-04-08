"""
Unit tests for roles.py — ROLE_HIERARCHY, ALL_ROLES, expand_roles()
"""

import pytest
from roles import expand_roles, ROLE_HIERARCHY, ALL_ROLES


# ── ROLE_HIERARCHY structure ──────────────────────────────────────────────────

class TestRoleHierarchyStructure:
    def test_all_expected_roles_present(self):
        expected = {"admin", "hr", "finance", "engineer", "intern"}
        assert set(ROLE_HIERARCHY.keys()) == expected

    def test_admin_includes_all_roles(self):
        assert set(ROLE_HIERARCHY["admin"]) == {"admin", "hr", "finance", "engineer", "intern"}

    def test_hr_includes_intern(self):
        assert "intern" in ROLE_HIERARCHY["hr"]

    def test_finance_includes_intern(self):
        assert "intern" in ROLE_HIERARCHY["finance"]

    def test_engineer_includes_intern(self):
        assert "intern" in ROLE_HIERARCHY["engineer"]

    def test_intern_only_sees_intern(self):
        assert ROLE_HIERARCHY["intern"] == ["intern"]

    def test_hr_does_not_include_finance(self):
        assert "finance" not in ROLE_HIERARCHY["hr"]

    def test_finance_does_not_include_hr(self):
        assert "hr" not in ROLE_HIERARCHY["finance"]

    def test_engineer_does_not_include_hr(self):
        assert "hr" not in ROLE_HIERARCHY["engineer"]

    def test_all_roles_list_matches_hierarchy_keys(self):
        assert set(ALL_ROLES) == set(ROLE_HIERARCHY.keys())

    def test_all_roles_has_correct_length(self):
        assert len(ALL_ROLES) == 5


# ── expand_roles() ────────────────────────────────────────────────────────────

class TestExpandRoles:
    def test_admin_expands_to_all(self):
        result = set(expand_roles(["admin"]))
        assert result == {"admin", "hr", "finance", "engineer", "intern"}

    def test_hr_expands_to_hr_and_intern(self):
        result = set(expand_roles(["hr"]))
        assert result == {"hr", "intern"}

    def test_finance_expands_to_finance_and_intern(self):
        result = set(expand_roles(["finance"]))
        assert result == {"finance", "intern"}

    def test_engineer_expands_to_engineer_and_intern(self):
        result = set(expand_roles(["engineer"]))
        assert result == {"engineer", "intern"}

    def test_intern_expands_to_only_intern(self):
        result = set(expand_roles(["intern"]))
        assert result == {"intern"}

    def test_empty_roles_returns_empty(self):
        result = expand_roles([])
        assert result == []

    def test_unknown_role_passes_through(self):
        result = set(expand_roles(["superuser"]))
        assert result == {"superuser"}

    def test_multiple_roles_merged(self):
        result = set(expand_roles(["hr", "finance"]))
        assert result == {"hr", "finance", "intern"}

    def test_duplicate_roles_deduplicated(self):
        result = expand_roles(["intern", "intern"])
        assert result.count("intern") == 1

    def test_returns_list(self):
        result = expand_roles(["hr"])
        assert isinstance(result, list)

    def test_admin_plus_finance_still_all_roles(self):
        result = set(expand_roles(["admin", "finance"]))
        assert result == {"admin", "hr", "finance", "engineer", "intern"}

    def test_hr_plus_engineer_no_finance(self):
        result = set(expand_roles(["hr", "engineer"]))
        assert "finance" not in result
        assert "hr" in result
        assert "engineer" in result
        assert "intern" in result

    def test_unknown_plus_known_role(self):
        result = set(expand_roles(["intern", "alien"]))
        assert "intern" in result
        assert "alien" in result

    def test_all_individual_roles_expand_correctly(self):
        for role in ["admin", "hr", "finance", "engineer", "intern"]:
            result = expand_roles([role])
            assert role in result  # every role includes itself
