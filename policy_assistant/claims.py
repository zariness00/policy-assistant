"""Deterministic helpers for claim triage: which peril a claim falls under, which excess
applies from the client's schedule, and which common exclusions the facts hint at.
The final judgement stays with the broker and the insurer."""

import re
from dataclasses import dataclass, field


@dataclass
class Peril:
    key: str
    label: str
    keywords: list[str]
    cover_query: str
    exclusion_query: str
    excess_field: str = "standard_excess"
    needs_optional_cover: str | None = None


PERILS = [
    Peril("escape_of_water", "Escape of water / burst pipe",
          ["burst", "pipe", "leak", "water tank", "radiator", "escape of water", "washing machine",
           "dishwasher", "plumbing", "frozen", "freezing", "overflow", "damp", "sealant", "silicone", "grout"],
          "escape of water leaking from fixed water installation burst pipe pipes tanks heating system",
          "escape of water not covered exclusions gradual unoccupied sealant grout wear and tear trace and access",
          excess_field="escape_of_water_excess"),
    Peril("storm", "Storm", ["storm", "wind", "gale", "hail", "roof tiles"],
          "storm damage cover", "storm damage not covered exclusions wear and tear gates fences"),
    Peril("flood", "Flood", ["flood", "river", "rising water", "surface water"],
          "flood damage cover", "flood not covered exclusions"),
    Peril("fire", "Fire, smoke or explosion", ["fire", "smoke", "explosion", "burnt", "scorch", "lightning"],
          "fire smoke explosion lightning cover", "fire smoke not covered scorching exclusions"),
    Peril("theft", "Theft or attempted theft", ["theft", "stolen", "burglary", "break-in", "broke in", "burgled"],
          "theft or attempted theft cover", "theft not covered unoccupied lodgers forcible entry exclusions"),
    Peril("subsidence", "Subsidence, heave or landslip", ["subsidence", "crack", "heave", "landslip", "settlement"],
          "subsidence ground heave landslip cover", "subsidence not covered exclusions settlement erosion",
          excess_field="subsidence_excess"),
    Peril("accidental_damage", "Accidental damage",
          ["dropped", "spilled", "spill", "knocked", "accidentally", "accidental", "broke the", "smashed"],
          "accidental damage cover", "accidental damage not covered exclusions",
          needs_optional_cover="accidental_damage"),
]

RED_FLAGS = [
    (r"\b(gradual|over (?:time|several|many|the past)|for (?:weeks|months)|slowly|damp patch|ongoing)\b",
     "Facts suggest gradual damage - most wordings exclude damage caused gradually."),
    (r"\b(unoccupied|empty|vacant|away for|on holiday for|abroad for)\b",
     "Possible unoccupancy - check the unoccupancy limit and conditions in the wording/endorsements."),
    (r"\b(wear and tear|old|rust|rusted|corrod\w*|perished|deteriorat\w*)\b",
     "Possible wear and tear - repairs to the failed item itself are often excluded."),
    (r"\b(sealant|grout|silicone)\b",
     "Failed sealant/grout is commonly excluded for escape of water."),
    (r"\b(deliberate|on purpose|intentional)\b", "Deliberate damage is excluded."),
    (r"\b(diy|renovat\w*|building work|builder|contractor)\b",
     "Damage during building/renovation work may be excluded or restricted."),
    (r"\b(gutter|downpipe|rainwater)\b",
     "Water from guttering/rainwater pipes is usually not 'escape of water' - may fall under storm instead."),
]


@dataclass
class Triage:
    perils: list[Peril]
    red_flags: list[str] = field(default_factory=list)


def classify(description: str) -> Triage:
    text = description.lower()
    scored = []
    for p in PERILS:
        hits = sum(1 for k in p.keywords if re.search(rf"\b{re.escape(k)}(?:s|es|ed|ing)?\b", text))
        if hits:
            scored.append((hits, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    flags = [msg for pattern, msg in RED_FLAGS if re.search(pattern, text)]
    return Triage([p for _, p in scored], flags)


def applicable_excess(policy: dict, peril: Peril) -> dict:
    compulsory = policy.get(peril.excess_field)
    basis = peril.excess_field
    if compulsory is None:
        compulsory, basis = policy["standard_excess"], "standard_excess"
    voluntary = policy.get("voluntary_excess") or 0
    return {
        "compulsory_excess_gbp": compulsory,
        "compulsory_excess_basis": basis,
        "voluntary_excess_gbp": voluntary,
        "total_excess_gbp": compulsory + voluntary,
        "note": "From the client's policy schedule. Check the wording for whether the excess applies per "
                "section (buildings and contents claimed together may attract two excesses).",
    }


def optional_cover_missing(policy: dict, peril: Peril) -> str | None:
    has_ad = policy.get("accidental_damage_buildings") or policy.get("accidental_damage_contents")
    if peril.needs_optional_cover == "accidental_damage" and not has_ad:
        return "Accidental damage is optional cover and is NOT shown on this client's schedule."
    return None
