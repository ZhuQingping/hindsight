"""The superseded-by-coding-agents notice."""

from lib.upgrade_notice import upgrade_notice


def test_shown_on_every_session():
    """No cap and no interval — a notice shown once is a notice that gets missed."""
    for _ in range(5):
        assert upgrade_notice({}) is not None


def test_names_this_plugin():
    """Whoever reads it must know WHICH plugin is deprecated — both are installed side by side."""
    assert "Claude Code" in upgrade_notice({})


def test_asks_for_the_configured_guide():
    assert "service administrator" in upgrade_notice({})
    assert "hindsight" not in upgrade_notice({}).lower()


def test_says_deprecated_outright():
    """ "Superseded" is jargon; a user needs to read one word and know to act."""
    assert "DEPRECATED" in upgrade_notice({})


def test_opt_out_silences_it():
    """The only thing making an every-session notice acceptable — so it must work."""
    assert upgrade_notice({"upgradeNotice": False}) is None


def test_opt_out_is_discoverable_from_the_message_itself():
    assert "upgradeNotice" in upgrade_notice({})


def test_never_raises():
    """A promotional message must never be why someone's session breaks."""

    class Hostile:
        def get(self, *a, **k):
            raise RuntimeError("boom")

    assert upgrade_notice(Hostile()) is None
