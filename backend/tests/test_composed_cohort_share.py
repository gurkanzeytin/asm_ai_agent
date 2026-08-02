"""Plan-composed cohort share (metric algebra, first slice).

The metric catalog freezes each rate's condition into its formula: seven
`conditional_rate` metrics are ONE SQL shape with seven hard-coded predicates.
A share the catalog never anticipated ("kadın hasta oranı", "Kardiyoloji
randevularının payı") therefore had no way to be expressed and degraded to a
plain appointment count — a different answer, delivered at full confidence.

Composing the predicate instead answers the whole family without a metric per
question. These tests pin the behaviour AND the two ways it can silently break,
both of which produce a share that is 100% by construction.
"""

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.state import AgentState
from app.database_intelligence.models import ViewMetadata
from app.database_intelligence.value_catalog import ValueCatalog
from app.planning.planner import QueryPlanner
from app.planning.predicates import extract_measure_threshold
from app.planning.value_resolver import (
    UNRESOLVED_COHORT_FIELD,
    ValueResolver,
    extract_candidate_phrases,
    extract_cohort_share_mentions,
)
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
SHARE_ALIAS = "cohort_share_rate"

_VALUES = {
    "department": ["Kardiyoloji", "Radyoloji"],
    "branch": ["Gebze Şubesi"],
    "gender": ["E", "K", "D"],
    "nationality": ["Türkiye", "Bulgaristan", "Suriye", "Almanya"],
    "service": ["Muayene"],
    "category": ["Genel"],
    "appointment_type": ["Poliklinik"],
    "appointment_status": ["Gerçekleşti", "Gelmedi"],
}


class _FakeValueCatalog(ValueCatalog):
    def __init__(self) -> None:  # noqa: D107 - deliberately skips the DB engine
        pass

    async def get_distinct_values(self, field_name: str) -> list[str]:
        return _VALUES.get(field_name, [])

    async def search_candidates(self, field_name: str, _text: str) -> list[str]:
        return _VALUES.get(field_name, [])


async def _resolved_plan(question: str):
    plan = QueryPlanner().build_plan(
        question, QueryAnalyzer().analyze(question), tables=[], views=[VIEW]
    )
    node = ResolveFilterValuesNode(resolver=ValueResolver(catalog=_FakeValueCatalog()))
    state = await node.execute(
        AgentState(question=question, raw_question=question, query_plan=plan)
    )
    return state.query_plan


# ---------------------------------------------------------------------------
# Extraction: share reading vs filter reading vs breakdown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        # Gender is the one field the wording itself identifies (E/K/D codes
        # have curated aliases); everything else is left for grounding to place.
        ("Hangi bölümde kadın hasta oranı en yüksek?", {"gender": "kadin"}),
        ("Kadın hastaların payı nedir?", {"gender": "kadin"}),
        ("Erkek hasta yüzdesi kaç?", {"gender": "erkek"}),
        ("Kardiyoloji randevularının payı nedir?", {UNRESOLVED_COHORT_FIELD: "Kardiyoloji"}),
        ("Bulgaristanlı hastaların oranı nedir?", {UNRESOLVED_COHORT_FIELD: "Bulgaristanlı"}),
        # The field's own dimension noun may sit between value and share word.
        (
            "Bulgaristan uyruklu hastaların oranı nedir?",
            {UNRESOLVED_COHORT_FIELD: "Bulgaristan"},
        ),
    ],
)
def test_share_wording_yields_a_cohort_mention(question, expected):
    assert extract_cohort_share_mentions(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        # A metric between the cohort and the share word measures something
        # ABOUT the cohort — that is a filter, and already worked.
        "Kadın hastaların gelmeme oranı nedir?",
        # Two cohorts named together is a breakdown across the dimension.
        "Kadın ve erkek randevu oranını karşılaştır",
        # No cohort at all.
        "Bölüm bazında gelmeme oranı",
        "Erkek hastaların en çok gittiği ilk 5 bölüm",
    ],
)
def test_non_share_wording_yields_no_cohort_mention(question):
    assert extract_cohort_share_mentions(question) == {}


# ---------------------------------------------------------------------------
# The composed metric
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,predicate,label",
    [
        (
            "Hangi bölümde kadın hasta oranı en yüksek?",
            "SUM(CASE WHEN CinsiyetId = N'K' THEN 1 ELSE 0 END)",
            "Kadın oranı",
        ),
        (
            "Şube bazında erkek hasta oranı",
            "SUM(CASE WHEN CinsiyetId = N'E' THEN 1 ELSE 0 END)",
            "Erkek oranı",
        ),
    ],
)
async def test_cohort_share_is_composed_and_rendered(question, predicate, label):
    plan = await _resolved_plan(question)
    sql = DeterministicSQLBuilder().build(plan).sql

    assert plan.analysis_type == "ratio"
    assert plan.metrics[0] == SHARE_ALIAS, "the asked-for metric leads, so ranking follows it"
    assert plan.metric_specs[SHARE_ALIAS].label == label
    assert predicate in sql
    assert "NULLIF(COUNT(*), 0)" in sql
    assert SQLValidator().validate(sql).valid


@pytest.mark.asyncio
async def test_composite_department_share_uses_containment_not_equality():
    """GenelRandevuBolumAdi stores comma-separated composites ("Genel Cerrahi,
    Ameliyathane, "), so `= 'Kardiyoloji'` matches nothing and the share would
    read 0% everywhere."""
    plan = await _resolved_plan("Kardiyoloji randevularının payı nedir?")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert "GenelRandevuBolumAdi = N'Kardiyoloji'" not in sql
    assert "LIKE N'%,Kardiyoloji,%'" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,cohort_column",
    [
        ("Hangi bölümde kadın hasta oranı en yüksek?", "CinsiyetId"),
        ("Kardiyoloji randevularının payı nedir?", "GenelRandevuBolumAdi"),
    ],
)
async def test_cohort_never_narrows_its_own_denominator(question, cohort_column):
    """Both silent-100% failure modes: the cohort as a WHERE filter shrinks the
    denominator to itself; the cohort as a GROUP BY dimension puts it alone on
    its own row."""
    plan = await _resolved_plan(question)
    sql = DeterministicSQLBuilder().build(plan).sql

    assert cohort_column not in plan.dimensions
    where_clause = sql.split("WHERE", 1)[1].split("GROUP BY")[0] if "WHERE" in sql else ""
    assert cohort_column not in where_clause


@pytest.mark.asyncio
async def test_a_catalog_rate_always_wins_over_composition():
    """`no_show_rate` expresses "gelmeyenlerin payı" exactly; composing a second
    metric for it would answer the same thing twice."""
    plan = await _resolved_plan("Gelmeyenlerin payi ne durumda?")

    assert plan.metrics == ["no_show_rate"]
    assert plan.metric_specs == {}


@pytest.mark.asyncio
async def test_the_base_volume_survives_alongside_the_share():
    """A share cannot be sanity-checked without the count it is a share of."""
    plan = await _resolved_plan("Hangi bölümde kadın hasta oranı en yüksek?")

    assert "appointment_count" in plan.metrics
    assert plan.dimensions == ["GenelRandevuBolumAdi"]


@pytest.mark.asyncio
async def test_an_ungrounded_cohort_composes_nothing():
    """No predicate is ever invented from a value the database does not have."""
    plan = await _resolved_plan("Kadıköy randevularının payı nedir?")

    assert SHARE_ALIAS not in plan.metrics
    assert plan.metric_specs == {}


# ---------------------------------------------------------------------------
# Numeric thresholds — the bound is whatever the user wrote
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,column,operator,value",
    [
        ("Randevu süresi 30 dakikadan uzun olanların oranı nedir?", "RandevuSuresi", ">", 30),
        ("Randevu süresi 20 dakikadan kısa olanların oranı", "RandevuSuresi", "<", 20),
        ("60 dakikadan uzun randevuların yüzdesi", "RandevuSuresi", ">", 60),
        ("45 dakikadan fazla süren randevular", "RandevuSuresi", ">", 45),
        ("Süresi 90 dakikayı aşan randevuların payı", "RandevuSuresi", ">", 90),
        # Turkish attaches case suffixes to numerals with an apostrophe.
        ("Randevu süresi 15'ten az olanlar", "RandevuSuresi", "<", 15),
        # "en az/en fazla N" is the same construction, inverted and inclusive.
        ("En az 30 dakika süren randevuların oranı", "RandevuSuresi", ">=", 30),
        ("En fazla 15 dakika süren randevular", "RandevuSuresi", "<=", 15),
    ],
)
def test_any_numeric_bound_is_parsed(question, column, operator, value):
    """Nothing here is specific to a particular number: 20, 30, 45, 60, 90 and
    every other value take the same path."""
    predicate = extract_measure_threshold(question)

    assert predicate is not None
    assert (predicate.column, predicate.operator, predicate.values[0]) == (
        column,
        operator,
        float(value),
    )


@pytest.mark.parametrize(
    "question",
    [
        "2024 yılında kaç randevu var?",
        "Bölüm bazında randevu sayısı",
        "En yoğun ilk 10 bölüm",
        "2024 ve 2025 randevu sayılarını karşılaştır",
        # Age already has its own DATEDIFF rendering; two parsers claiming the
        # same wording would fight over it.
        "60 yaş üstü hastaların gelmeme oranı",
    ],
)
def test_no_threshold_is_invented(question):
    assert extract_measure_threshold(question) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [20, 30, 45, 60])
async def test_threshold_share_renders_for_any_bound(minutes):
    plan = await _resolved_plan(f"Randevu süresi {minutes} dakikadan uzun olanların oranı nedir?")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert f"SUM(CASE WHEN RandevuSuresi > {minutes} THEN 1 ELSE 0 END)" in sql
    assert "NULLIF(COUNT(*), 0)" in sql
    assert plan.metric_specs[SHARE_ALIAS].label == f"{minutes} dakikadan uzun randevu oranı"
    assert SQLValidator().validate(sql).valid


@pytest.mark.asyncio
async def test_threshold_without_share_wording_is_a_row_filter():
    """"…sayısı" counts the cohort; only "…oranı" needs the full denominator."""
    plan = await _resolved_plan("60 dakikadan uzun randevu sayısı nedir?")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert SHARE_ALIAS not in plan.metrics
    assert "RandevuSuresi > 60" in sql
    assert "COUNT(*)" in sql


# ---------------------------------------------------------------------------
# Nationality: a named cohort, and every nationality's own share
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Yabancı hasta oranı nedir?",
        "2024 yılında Türk olmayan uyrukların oranı nedir?",
        "Türkiye dışındaki uyrukların randevu payı nedir?",
    ],
)
async def test_foreign_cohort_is_a_negation_predicate(question):
    """"Yabancı" names a SET of values, not one, so it cannot be grounded like
    an ordinary filter value. Curated in view_semantics.json so the home-country
    assumption stays visible and configurable."""
    plan = await _resolved_plan(question)
    sql = DeterministicSQLBuilder().build(plan).sql

    assert "SUM(CASE WHEN Uyruk <> N'Türkiye' THEN 1 ELSE 0 END)" in sql
    assert plan.metric_specs[SHARE_ALIAS].label == "Yabancı uyruklu oranı"
    assert "Uyruk" not in plan.dimensions, "the cohort column never groups its own share"
    assert not any(extra.startswith("NEGATION:") for extra in plan.extra_filters)
    assert SQLValidator().validate(sql).valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Uyruklara göre randevu oranı",
        "Bölümlere göre randevu oranı",
        "Şubelere göre randevu yüzdesi",
        "Hizmetlere göre randevu payı",
    ],
)
async def test_per_group_share_of_total_is_rendered(question):
    """Every value's own proportion of the whole — the counterpart to naming a
    single cohort. Asking for it in any of these ways must reach the builder's
    window function, not return bare counts."""
    plan = await _resolved_plan(question)
    sql = DeterministicSQLBuilder().build(plan).sql

    assert "pay_yuzdesi" in sql
    assert "NULLIF(SUM(COUNT(*)) OVER (), 0)" in sql
    assert SQLValidator().validate(sql).valid


@pytest.mark.asyncio
async def test_only_one_percentage_per_answer():
    """`share_of_total` renders a percentage OF the primary metric; with a
    composed share leading that would be a percentage of a percentage."""
    plan = await _resolved_plan("Bölüm bazında yabancı hasta oranı")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert "100.0 * 100.0" not in sql
    assert sql.count("pay_yuzdesi") == 0


@pytest.mark.asyncio
async def test_a_period_change_percentage_is_not_a_share_of_total():
    """"Bu farkı yüzde olarak özetle" asks how much the two periods differ, not
    what each group's slice of the whole is — both are "yüzde"."""
    question = "2025 Mayis ile Haziran 2025 arasindaki farki yuzde olarak ozetle."
    plan = await _resolved_plan(question)

    assert not any(
        calculation.startswith("share_of_total:") for calculation in plan.derived_calculations
    )


# ---------------------------------------------------------------------------
# A named value's field is decided by grounding, never guessed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,column,value,label",
    [
        # Turkish forms the demonym with a suffix the stored value does not
        # carry: "Bulgaristanlı" -> "Bulgaristan", "Suriyeli" -> "Suriye".
        ("Bulgaristanlı hastaların oranı nedir?", "Uyruk", "Bulgaristan", "Bulgaristan oranı"),
        ("Suriyeli hastaların oranı", "Uyruk", "Suriye", "Suriye oranı"),
        (
            "Bulgaristan uyruklu hastaların oranı nedir?",
            "Uyruk",
            "Bulgaristan",
            "Bulgaristan oranı",
        ),
        ("Almanya uyruklu randevuların payı", "Uyruk", "Almanya", "Almanya oranı"),
    ],
)
async def test_a_named_value_finds_its_own_field(question, column, value, label):
    """Nothing in "Bulgaristanlı hastaların oranı" says WHICH column the value
    belongs to — only the data does. An earlier version offered every named
    value to `department` first, so a nationality never composed anything."""
    plan = await _resolved_plan(question)
    sql = DeterministicSQLBuilder().build(plan).sql

    assert plan.metric_specs[SHARE_ALIAS].predicate.column == column
    assert plan.metric_specs[SHARE_ALIAS].predicate.values == [value]
    assert plan.metric_specs[SHARE_ALIAS].label == label
    assert f"SUM(CASE WHEN {column} = N'{value}' THEN 1 ELSE 0 END)" in sql
    assert SQLValidator().validate(sql).valid


@pytest.mark.asyncio
async def test_named_cohort_share_keeps_the_full_denominator():
    """The named value must not also filter the rows it is a share of."""
    plan = await _resolved_plan("Bulgaristanlı hastaların oranı nedir?")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert "Uyruk" not in plan.dimensions
    where_clause = sql.split("WHERE", 1)[1].split("GROUP BY")[0] if "WHERE" in sql else ""
    assert "Uyruk" not in where_clause


@pytest.mark.asyncio
async def test_a_breakdown_still_works_beside_a_named_cohort():
    plan = await _resolved_plan("Bölüm bazında Bulgaristanlı hasta oranı")
    sql = DeterministicSQLBuilder().build(plan).sql

    assert plan.dimensions == ["GenelRandevuBolumAdi"]
    assert "SUM(CASE WHEN Uyruk = N'Bulgaristan' THEN 1 ELSE 0 END)" in sql


# ---------------------------------------------------------------------------
# Genericity: every value in the column, not the handful that were tried
# ---------------------------------------------------------------------------

_NATIONALITIES = [
    "Türkiye",
    "Almanya",
    "Arnavutluk",
    "İtalya",
    "ABD",
    "Bulgaristan",
    "Suriye",
    "Yunanistan",
    "Irak",
    "Rusya",
    "Azerbaycan",
    "Gürcistan",
    "İran",
    "Afganistan",
    "Fransa",
    "Hollanda",
    "Özbekistan",
    "Türkmenistan",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("country", _NATIONALITIES)
@pytest.mark.parametrize(
    "template", ["{} uyruklu hastaların oranı nedir?", "{} randevularının payı nedir?"]
)
async def test_every_nationality_composes_its_own_share(country, template, monkeypatch):
    """The predicate is bound by grounding against the column's real values, so
    coverage is the column's contents — not a list of countries in the code."""
    monkeypatch.setitem(_VALUES, "nationality", _NATIONALITIES)

    plan = await _resolved_plan(template.format(country))

    assert plan.metric_specs[SHARE_ALIAS].predicate.column == "Uyruk"
    assert plan.metric_specs[SHARE_ALIAS].predicate.values == [country]


@pytest.mark.parametrize(
    "question,field,value",
    [
        # "tur" is appointment_type's cue root and was prefix-matched, so every
        # value beginning with it was treated as a dimension noun: "Türkiye"
        # extracted NO filter and answered over every nationality, and a branch
        # name was truncated to its second word.
        ("Türkiye uyruklu hastaların randevu sayısı", "nationality", ["Türkiye"]),
        ("Turgut Özal Şubesindeki randevu sayısı", "branch", ["Turgut Özal"]),
    ],
)
def test_a_value_starting_with_a_short_cue_root_is_still_a_value(question, field, value):
    assert extract_candidate_phrases(question).get(field) == value


@pytest.mark.parametrize(
    "question",
    [
        # The guard these roots exist for must keep working: a dimension noun
        # introducing its own cue is never a value.
        "Randevu durumlarının dağılımını göster",
        "Bunu şubeye göre kır",
    ],
)
def test_dimension_nouns_are_still_not_values(question):
    assert extract_candidate_phrases(question) == {}
