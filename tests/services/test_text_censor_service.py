from bot.services.text_censor import TextCensorService


def test_censor_text_replaces_known_hateful_examples():
    service = TextCensorService()

    assert service.censor_text("jews did 911") == "[censored]"
    assert service.censor_text("i hate nig-ventura-27-07-2") == "[censored]"
    assert service.censor_text("niggas young fly on the tra") == "[censored]"


def test_censor_text_leaves_safe_text_unchanged():
    service = TextCensorService()

    assert service.censor_text("normal sound name.mp3") == "normal sound name.mp3"
    assert service.censor_text(None) is None
