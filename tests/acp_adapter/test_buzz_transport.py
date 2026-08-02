from acp_adapter.buzz_transport import build_buzz_publish_request


BUZZ_ENV = {
    "BUZZ_RELAY_URL": "wss://example.test",
    "BUZZ_PRIVATE_KEY": "secret",
}


def prompt(scope: str = "dm") -> str:
    return f"""[Context]
Scope: {scope}
Channel: DM (#f3f89666-d4b7-4465-b031-98eec7f66c9e)
[Buzz event: @mention]
Event ID: {'a' * 64}
From: Dave (npub: npub1example, hex: {'b' * 64})
"""


def test_buzz_auto_publish_is_opt_in():
    assert build_buzz_publish_request(
        user_text=prompt(),
        final_response="hello",
        config={},
        env=BUZZ_ENV,
    ) is None


def test_buzz_auto_publish_requires_managed_buzz_environment():
    assert build_buzz_publish_request(
        user_text=prompt(),
        final_response="hello",
        config={"acp": {"buzz_auto_publish": True}},
        env={},
    ) is None


def test_buzz_dm_publish_is_flat_by_default():
    request = build_buzz_publish_request(
        user_text=prompt("dm"),
        final_response="hello Dave",
        config={"acp": {"buzz_auto_publish": True}},
        env=BUZZ_ENV,
    )

    assert request is not None
    assert request.channel_id == "f3f89666-d4b7-4465-b031-98eec7f66c9e"
    assert request.reply_to is None
    assert request.content == "hello Dave\n"
    assert "--reply-to" not in request.argv()
    assert request.mention_pubkey == "b" * 64
    assert request.argv()[-2:] == ["--mention", "b" * 64]


def test_buzz_non_dm_publish_replies_to_trigger_event():
    request = build_buzz_publish_request(
        user_text=prompt("channel"),
        final_response="done",
        config={"acp": {"buzz_auto_publish": True}},
        env=BUZZ_ENV,
    )

    assert request is not None
    assert request.reply_to == "a" * 64
    assert ["--reply-to", "a" * 64] == request.argv()[7:9]


def test_buzz_dm_can_be_explicitly_threaded():
    request = build_buzz_publish_request(
        user_text=prompt("dm"),
        final_response="threaded",
        config={"acp": {"buzz_auto_publish": True, "buzz_flat_dms": False}},
        env=BUZZ_ENV,
    )

    assert request is not None
    assert request.reply_to == "a" * 64
