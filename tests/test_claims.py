from policy_assistant import claims


def test_burst_pipe_is_escape_of_water():
    t = claims.classify("A pipe burst under the kitchen sink and flooded the kitchen")
    assert t.perils[0].key == "escape_of_water"
    assert t.red_flags == []


def test_red_flags():
    t = claims.classify("Slow leak from a rusted pipe over several months while the house was empty")
    assert any("gradual" in f for f in t.red_flags)
    assert any("unoccupancy" in f for f in t.red_flags)
    assert any("wear and tear" in f for f in t.red_flags)


def test_excess_uses_schedule():
    policy = {"standard_excess": 50, "escape_of_water_excess": 250, "voluntary_excess": 100}
    peril = next(p for p in claims.PERILS if p.key == "escape_of_water")
    ex = claims.applicable_excess(policy, peril)
    assert ex["compulsory_excess_gbp"] == 250 and ex["total_excess_gbp"] == 350


def test_accidental_damage_needs_optional_cover():
    peril = next(p for p in claims.PERILS if p.key == "accidental_damage")
    assert claims.optional_cover_missing({"accidental_damage_buildings": 0, "accidental_damage_contents": 0}, peril)
    with_ad = {"accidental_damage_buildings": 0, "accidental_damage_contents": 1}
    assert claims.optional_cover_missing(with_ad, peril) is None


def test_keywords_match_whole_words():
    t = claims.classify("Someone smashed the window")
    assert "storm" not in [p.key for p in t.perils]
    assert claims.classify("The toilet overflowed").perils[0].key == "escape_of_water"
