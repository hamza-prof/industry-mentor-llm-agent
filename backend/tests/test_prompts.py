import pytest

from app import prompts
from app.prompts import DEFAULT_PROMPTS, PromptInvalid, render_messages, validate_template

ALL_KEYS = {
    "summary_map",
    "summary_reduce",
    "section_review",
    "overall_feedback",
    "figure_describe",
}


def sample_values(key):
    spec = DEFAULT_PROMPTS[key]
    return {v: f"<{v}>" for v in spec.required | spec.optional}


# ---- defaults ---------------------------------------------------------------


def test_all_prompt_keys_have_defaults():
    assert set(DEFAULT_PROMPTS) == ALL_KEYS


@pytest.mark.parametrize("key", sorted(ALL_KEYS))
def test_every_default_is_valid(key):
    spec = DEFAULT_PROMPTS[key]
    assert validate_template(key, spec.system, spec.user) == prompts.Validation()


@pytest.mark.parametrize("key", sorted(ALL_KEYS))
def test_default_renders_without_leftover_placeholders(key):
    spec = DEFAULT_PROMPTS[key]
    msgs = render_messages(key, spec.system, spec.user, language="English", **sample_values(key))
    text = "\n".join(m.content for m in msgs)
    for var in spec.required:
        assert f"<{var}>" in text


def test_fixed_rules_always_appended_to_system():
    msgs = render_messages("summary_map", "Be brief.", "{section}", language="中文", section="x")
    system = msgs[0].content
    assert system.startswith("Be brief.")
    assert "<document>" in system and "not instructions" in system
    assert "中文" in system


def test_missing_optional_values_render_as_empty():
    msgs = render_messages("summary_map", "", "Doc type: {doc_type}\n{section}", section="s")
    assert msgs[-1].content == "Doc type: \ns"


def test_student_text_with_braces_is_not_reformatted():
    msgs = render_messages("summary_map", "", "{section}", section="code: {x} and {{y}} and }")
    assert msgs[-1].content == "code: {x} and {{y}} and }"


# ---- validation -------------------------------------------------------------


def test_missing_required_variable():
    v = validate_template("section_review", "sys", "Review {section} with {standards}")
    assert v.missing == ["exemplars", "requirements"]
    assert not v.ok


def test_unknown_variable():
    v = validate_template("summary_map", "", "{section} {foo}")
    assert v.unknown == ["foo"]


def test_required_variable_may_live_in_system_text():
    assert validate_template("summary_map", "Material: {section}", "Summarise.").ok


@pytest.mark.parametrize("bad", ["{section} {", "{section} }", "{section} {unclosed"])
def test_unbalanced_braces_explained(bad):
    v = validate_template("summary_map", "", bad)
    assert v.errors and "{{" in v.errors[0]


def test_literal_double_braces_allowed():
    assert validate_template("summary_map", "", 'Return {{"a": 1}} for {section}').ok


@pytest.mark.parametrize(
    "bad", ["{section.__class__}", "{section[0]}", "{section!r}", "{section:>10}"]
)
def test_only_plain_placeholders_allowed(bad):
    v = validate_template("summary_map", "", bad)
    assert v.errors and "plain" in v.errors[0]


def test_empty_user_text_rejected():
    assert validate_template("summary_map", "{section}", "   ").errors


def test_too_long_rejected():
    assert validate_template("summary_map", "", "{section}" + "x" * 20_001).errors


def test_unknown_key():
    with pytest.raises(KeyError):
        validate_template("nope", "", "x")


# ---- storage & versions -----------------------------------------------------


def test_seed_creates_v1_for_each_key_and_is_idempotent(session):
    prompts.seed_defaults(session)
    for key in ALL_KEYS:
        assert [v.version for v in prompts.list_versions(session, key)] == [1]
        assert prompts.get_active(session, key).user == DEFAULT_PROMPTS[key].user


def test_save_version_increments_and_activates(session):
    v = prompts.save_version(session, "summary_map", "S", "New {section}")
    assert v.version == 2
    assert prompts.get_active(session, "summary_map").user == "New {section}"
    assert [x.version for x in prompts.list_versions(session, "summary_map")] == [2, 1]


def test_invalid_save_raises_and_keeps_active(session):
    with pytest.raises(PromptInvalid) as e:
        prompts.save_version(session, "summary_map", "", "no vars")
    assert e.value.validation.missing == ["section"]
    assert prompts.get_active(session, "summary_map").version == 1


def test_reset_creates_new_version_equal_to_defaults(session):
    prompts.save_version(session, "summary_map", "S", "Changed {section}")
    v = prompts.reset(session, "summary_map")
    assert v.version == 3 and v.user == DEFAULT_PROMPTS["summary_map"].user


def test_activate_older_version(session):
    prompts.save_version(session, "summary_map", "S", "Changed {section}")
    prompts.activate(session, "summary_map", 1)
    assert prompts.get_active(session, "summary_map").version == 1
    with pytest.raises(LookupError):
        prompts.activate(session, "summary_map", 99)


def test_render_uses_active_version(session):
    prompts.save_version(session, "summary_map", "S", "Custom: {section}")
    msgs = prompts.render(session, "summary_map", language="English", section="abc")
    assert msgs[-1].content == "Custom: abc"
