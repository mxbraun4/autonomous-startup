"""Tests for PolicyEngine and PolicyResult."""

from src.framework.safety.limits import ToolClassification
from src.framework.safety.policy_engine import PolicyEngine, PolicyResult


class TestPolicyResult:
    def test_default_allowed(self):
        pr = PolicyResult()
        assert pr.allowed is True
        assert pr.denied_reason is None
        assert pr.rule_name is None


class TestPolicyEngineEmpty:
    def test_empty_policy_allows_all(self):
        pe = PolicyEngine()
        assert pe.check("any_tool", "any_cap", {}) is True


class TestDenylist:
    def test_denylist_blocks(self):
        pe = PolicyEngine(denylist={"bad_tool"})
        assert pe.check("bad_tool", "cap", {}) is False

    def test_denylist_allows_unlisted(self):
        pe = PolicyEngine(denylist={"bad_tool"})
        assert pe.check("good_tool", "cap", {}) is True


class TestAllowlist:
    def test_allowlist_allows_listed(self):
        pe = PolicyEngine(allowlist={"ok_tool"})
        assert pe.check("ok_tool", "cap", {}) is True

    def test_allowlist_blocks_unlisted(self):
        pe = PolicyEngine(allowlist={"ok_tool"})
        assert pe.check("other_tool", "cap", {}) is False


class TestDenyOverridesAllow:
    def test_deny_wins_over_allow(self):
        pe = PolicyEngine(allowlist={"tool_a"}, denylist={"tool_a"})
        assert pe.check("tool_a", "cap", {}) is False
        result = pe.check_detailed("tool_a", "cap", {})
        assert result.rule_name == "denylist"


class TestAutonomyLevel:
    def test_level_0_blocks_side_effect_1(self):
        tc = {"writer": ToolClassification(tool_name="writer", side_effect_level=1)}
        pe = PolicyEngine(autonomy_level=0, tool_classifications=tc)
        assert pe.check("writer", "cap", {}) is False

    def test_level_1_allows_side_effect_1(self):
        tc = {"writer": ToolClassification(tool_name="writer", side_effect_level=1)}
        pe = PolicyEngine(autonomy_level=1, tool_classifications=tc)
        assert pe.check("writer", "cap", {}) is True

    def test_level_1_blocks_side_effect_2(self):
        tc = {"deployer": ToolClassification(tool_name="deployer", side_effect_level=2)}
        pe = PolicyEngine(autonomy_level=1, tool_classifications=tc)
        assert pe.check("deployer", "cap", {}) is False

    def test_unclassified_tool_defaults_safe(self):
        """An unclassified tool is treated as level 0 (safe)."""
        pe = PolicyEngine(autonomy_level=0)
        assert pe.check("unknown_tool", "cap", {}) is True


class TestArgumentValidator:
    def test_validator_deny(self):
        def no_empty_url(tool_name, args):
            if not args.get("url"):
                return "url argument is required"
            return None

        pe = PolicyEngine(argument_validators=[no_empty_url])
        assert pe.check("fetch", "cap", {}) is False

    def test_validator_allow(self):
        def no_empty_url(tool_name, args):
            if not args.get("url"):
                return "url argument is required"
            return None

        pe = PolicyEngine(argument_validators=[no_empty_url])
        assert pe.check("fetch", "cap", {"url": "https://example.com"}) is True


class TestDomainHook:
    def test_domain_hook_deny(self):
        def block_all(tool_name, capability, args):
            return "blocked by domain policy"

        pe = PolicyEngine(domain_policy_hook=block_all)
        result = pe.check_detailed("tool", "cap", {})
        assert result.allowed is False
        assert result.rule_name == "domain_hook"


class TestCheckDetailed:
    def test_returns_rule_name(self):
        pe = PolicyEngine(denylist={"tool_x"})
        result = pe.check_detailed("tool_x", "cap", {})
        assert result.rule_name == "denylist"
        assert "tool_x" in result.denied_reason


class TestRuntimeMutation:
    def test_add_and_remove_denylist(self):
        pe = PolicyEngine()
        assert pe.check("tool_a", "cap", {}) is True
        pe.add_to_denylist("tool_a")
        assert pe.check("tool_a", "cap", {}) is False
        pe.remove_from_denylist("tool_a")
        assert pe.check("tool_a", "cap", {}) is True
