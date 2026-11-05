from policy_assistant.redact import mask_email, mask_name, mask_phone, redact_text


def test_redacts_common_pii():
    text = ("Call Sarah on 07700 900123 or +44 7700 900123, email sarah.t@example.com, "
            "postcode LS6 2AB, NI AB 12 34 56 C, card 4111 1111 1111 1111, DOB: 12/03/1984")
    out = redact_text(text, ["Sarah"])
    for leaked in ["07700", "example.com", "LS6", "AB 12", "4111", "1984", "Sarah"]:
        assert leaked not in out
    assert "[PHONE]" in out and "[EMAIL]" in out and "[POSTCODE]" in out


def test_keeps_money_and_policy_terms():
    text = "Escape of water excess is £250 under POL-1001, page 24."
    assert redact_text(text) == text


def test_masks():
    assert mask_name("Sarah Thompson") == "Sarah T."
    assert mask_email("sarah.thompson@example.com") == "s***@example.com"
    assert mask_phone("07700 900123") == "*** *** 123"


def test_bracketed_landline_is_redacted():
    assert "496" not in redact_text("Call me on (0113) 496 0163 after 5pm")
