"""Regression coverage for expert SQL UI probes observed in 2024/2023 data."""

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.state import AgentState
from app.context import ContextManager
from app.context.analytical_signals import merge_query_plans
from app.context.session_store import SessionStore
from app.database_intelligence.models import ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import DateFilterPlan, QueryPlan, ResolvedFilterPlan
from app.planning.planner import QueryPlanner
from app.planning.value_resolver import (
    ResolvedValue,
    extract_comparison_pair,
    extract_filter_only_phrase,
)
from app.services.deterministic_sql_builder import (
    DeterministicSQLBuilder,
    UnsupportedPlan,
)
from app.services.query_analyzer import QueryAnalyzer


VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _planned(question: str) -> QueryPlan:
    return QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )


def _sql(plan: QueryPlan) -> str:
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    compliance = PlanComplianceValidator().check(
        built.sql,
        plan,
        built.expected_aliases,
        deterministic=True,
    )
    assert compliance.compliant, compliance.missing
    return built.sql


def test_azalan_sirala_is_desc_ranking_not_percentage_change():
    plan = _planned("2024 yilinda sube bazinda randevu sayisini azalan sirala")
    sql = _sql(plan)

    assert plan.analysis_type == "ranking"
    assert plan.dimensions == ["SubeAdi"]
    assert plan.ranking == "DESC"
    assert "GROUP BY SubeAdi" in sql
    assert "ORDER BY appointment_count DESC" in sql
    assert "percentage_change" not in sql


def test_at_least_threshold_keeps_desc_sorting():
    plan = _planned(
        "2023 yilinda doktorlara gore en az 1000 randevusu olanlari "
        "randevu sayisina gore sirala"
    )
    sql = _sql(plan)

    assert plan.analysis_type == "ranking"
    assert plan.aggregate_threshold is not None
    assert plan.aggregate_threshold.operator == ">="
    assert plan.aggregate_threshold.metric == "appointment_count"
    assert "HAVING COUNT(*) >= 1000" in sql
    assert "ORDER BY appointment_count DESC" in sql


@pytest.mark.parametrize(
    ("question", "date_column", "metric_alias"),
    [
        (
            "2024 yilinda olusturulan randevulari olusturulma ayina gore say",
            "CreatedDate",
            "monthly_appointment_count",
        ),
        (
            "2024 yilinda protokolu acilan randevulari protokol acilis ayina gore say",
            "ProtokolAcilisTarihi",
            "protocol_created_count",
        ),
    ],
)
def test_month_bucket_variations_use_requested_date_column(
    question: str,
    date_column: str,
    metric_alias: str,
):
    plan = _planned(question)
    sql = _sql(plan)
    bucket = f"DATEFROMPARTS(YEAR({date_column}), MONTH({date_column}), 1)"

    assert plan.analysis_type == "time_trend"
    assert plan.grouping_granularity == "month"
    assert bucket in sql
    assert f"GROUP BY {bucket}" in sql
    assert metric_alias in sql


def test_three_requested_dimensions_are_preserved_without_grouping_counted_patient_id():
    plan = _planned(
        "2023 yilinda uyruk cinsiyet ve randevu tipi bazinda "
        "tekil hasta sayisini goster"
    )
    sql = _sql(plan)

    assert plan.dimensions == ["RandevuTipiAdi", "CinsiyetId", "Uyruk"]
    assert "COUNT(DISTINCT HastaId)" in sql
    assert "GROUP BY RandevuTipiAdi, CinsiyetId, Uyruk" in sql
    assert "GROUP BY RandevuTipiAdi, HastaId" not in sql


def test_duration_breakdown_sirala_orders_by_average_duration_desc():
    plan = _planned(
        "2024 yilinda hizmet ve kategori kiriliminda ortalama randevu suresini sirala"
    )
    sql = _sql(plan)

    assert plan.ranking == "DESC"
    assert "GROUP BY KategoriAdi, HizmetAdi" in sql
    assert "ORDER BY appointment_duration_average DESC" in sql


def test_creator_person_word_keeps_creator_dimension():
    plan = _planned(
        "2024 yilinda kaydedilen randevulari randevuyu veren kisiye gore goster"
    )
    sql = _sql(plan)

    assert plan.output_entity == "Creator"
    assert plan.dimensions == ["RandevuyuVeren"]
    assert "GROUP BY RandevuyuVeren" in sql


def test_ve_pair_before_department_cue_is_comparison_pair():
    assert extract_comparison_pair(
        "2024 yilinda Kadin Dogum ve Ortopedi bolumlerini "
        "randevu sayisiyla karsilastir"
    ) == ("Kadin Dogum", "Ortopedi")


class _GroundedResolver:
    async def resolve(self, field_name: str, original_text: str) -> ResolvedValue:
        values = {
            "Radyoloji": "Radyoloji",
            "Kadin Dogum": "Kadin Dogum",
            "Ortopedi": "Ortopedi",
        }
        matched = values.get(original_text)
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=original_text.lower(),
            matched_value=matched,
            confidence=1.0 if matched else 0.0,
            grounded=matched is not None,
            match_type="exact" if matched else "no_match",
            clarification_required=False,
        )


@pytest.mark.asyncio
async def test_filter_only_followup_uses_retained_department_dimension():
    plan = QueryPlan(
        question="sadece Radyoloji'yi goster",
        analysis_type="ranking",
        metrics=["no_show_rate"],
        dimensions=["GenelRandevuBolumAdi"],
        projection=["GenelRandevuBolumAdi"],
    )
    state = AgentState(question=plan.question, query_plan=plan)

    resolved = await ResolveFilterValuesNode(_GroundedResolver()).execute(state)
    resolved_plan = resolved.query_plan

    assert extract_filter_only_phrase(plan.question) == "Radyoloji"
    assert resolved_plan is not None
    assert resolved_plan.resolved_filters["department"].values == ["Radyoloji"]
    sql = _sql(resolved_plan)
    assert "LIKE N'%,Radyoloji,%'" in sql
    assert "dept_atomic.value = N'Radyoloji'" in sql


@pytest.mark.asyncio
async def test_ve_department_comparison_grounds_both_values():
    plan = _planned(
        "2024 yilinda Kadin Dogum ve Ortopedi bolumlerini "
        "randevu sayisiyla karsilastir"
    )
    state = AgentState(question=plan.question, query_plan=plan)

    resolved = await ResolveFilterValuesNode(_GroundedResolver()).execute(state)
    resolved_plan = resolved.query_plan

    assert resolved_plan is not None
    assert resolved_plan.analysis_type == "comparison"
    assert resolved_plan.resolved_filters["department"].values == [
        "Kadin Dogum",
        "Ortopedi",
    ]


def test_threshold_metric_binding_survives_metric_switch_followup():
    first = QueryPlan(
        question="2024 yilinda bolumlere gore randevu sayisini goster",
        analysis_type="count",
        metrics=["appointment_count"],
        dimensions=["GenelRandevuBolumAdi"],
        projection=["GenelRandevuBolumAdi"],
        date_filters=[
            DateFilterPlan(
                expression="2024",
                start_date="2024-01-01",
                end_date="2024-12-31",
                column="BaslangicTarihi",
            )
        ],
    )
    threshold_turn = _planned("tabloda 30000 den az olanlari goster")
    thresholded = merge_query_plans(
        current=threshold_turn,
        retained=first,
        raw_question=threshold_turn.question,
        follow_up_detected=True,
    )
    metric_turn = _planned("simdi bunlari gelmeme oranina gore sirala")
    switched = merge_query_plans(
        current=metric_turn,
        retained=thresholded,
        raw_question=metric_turn.question,
        follow_up_detected=True,
    )
    sql = _sql(switched)

    assert switched.metrics == ["no_show_rate"]
    assert switched.aggregate_threshold is not None
    assert switched.aggregate_threshold.metric == "appointment_count"
    assert "no_show_rate" in sql
    assert "HAVING COUNT(*) < 30000" in sql
    assert "no_show_rate < 30000" not in sql


def test_threshold_value_is_not_parsed_as_calendar_year():
    plan = _planned(
        "2024 Mayis ayinda bolumlere gore 2000 den az randevusu olanlari goster"
    )
    sql = _sql(plan)

    assert [(d.start_date, d.end_date) for d in plan.date_filters] == [
        ("2024-05-01", "2024-05-31")
    ]
    assert "2000-01-01" not in sql
    assert "HAVING COUNT(*) < 2000" in sql


def test_time_bucket_can_be_combined_with_dimension():
    plan = _planned(
        "2024 yilinda protokolu acilan randevulari "
        "protokol acilis ayina ve subeye gore say"
    )
    sql = _sql(plan)

    bucket = "DATEFROMPARTS(YEAR(ProtokolAcilisTarihi), MONTH(ProtokolAcilisTarihi), 1)"
    assert plan.grouping_granularity == "month"
    assert plan.dimensions == ["SubeAdi"]
    assert f"{bucket} AS period_start" in sql
    assert "SubeAdi AS SubeAdi" in sql
    assert f"GROUP BY {bucket}, SubeAdi" in sql


def test_space_separated_month_range_and_createddate_bucket():
    plan = _planned(
        "2024 Ocak Haziran arasi randevu olusturulma ayina gore "
        "ayni gun randevu alma oranini goster"
    )
    sql = _sql(plan)

    bucket = "DATEFROMPARTS(YEAR(CreatedDate), MONTH(CreatedDate), 1)"
    assert [(d.start_date, d.end_date, d.column) for d in plan.date_filters] == [
        ("2024-01-01", "2024-06-30", "CreatedDate")
    ]
    assert bucket in sql
    assert "2024-06-30" in sql
    assert "DATEFROMPARTS(YEAR(BaslangicTarihi)" not in sql


def test_appointment_type_unique_patient_count_does_not_group_by_patient_id():
    plan = _planned("2024 yilinda randevu tipine gore tekil hasta sayisini goster")
    sql = _sql(plan)

    assert plan.metrics == ["unique_patient_count"]
    assert plan.dimensions == ["RandevuTipiAdi"]
    assert "COUNT(DISTINCT HastaId)" in sql
    assert "appointments_per_type" not in sql
    assert "GROUP BY RandevuTipiAdi" in sql
    assert "GROUP BY HastaId" not in sql


def test_same_filter_year_followup_preserves_analytical_filter_context():
    retained = QueryPlan(
        question="sadece Radyoloji'yi goster",
        analysis_type="ranking",
        metrics=["no_show_rate"],
        dimensions=["GenelRandevuBolumAdi"],
        projection=["GenelRandevuBolumAdi"],
        ranking="DESC",
        order="DESC",
        date_filters=[
            DateFilterPlan(
                expression="2023",
                start_date="2023-01-01",
                end_date="2023-12-31",
                column="BaslangicTarihi",
            )
        ],
        resolved_filters={
            "department": ResolvedFilterPlan(
                field="department",
                values=["Radyoloji"],
                grounded=True,
                confidence=1.0,
                match_type="exact",
            )
        },
    )
    current = _planned("ayni filtreyle 2024 yilini goster")
    merged = merge_query_plans(
        current=current,
        retained=retained,
        raw_question=current.question,
        follow_up_detected=True,
    )
    sql = _sql(merged)

    assert merged.metrics == ["no_show_rate"]
    assert merged.dimensions == ["GenelRandevuBolumAdi"]
    assert [(d.start_date, d.end_date) for d in merged.date_filters] == [
        ("2024-01-01", "2024-12-31")
    ]
    assert "Id, BaslangicTarihi" not in sql
    assert "dept_atomic.value = N'Radyoloji'" in sql


def test_context_resolver_marks_same_filter_year_change_as_followup():
    manager = ContextManager(store=SessionStore())
    session_id = "same-filter-regression"
    first_resolution = manager.resolve("2023 yilinda bolumlere gore gelmeme oranini goster", session_id)
    retained_plan = QueryPlan(
        question="sadece Radyoloji'yi goster",
        analysis_type="ranking",
        metrics=["no_show_rate"],
        dimensions=["GenelRandevuBolumAdi"],
        projection=["GenelRandevuBolumAdi"],
        date_filters=[
            DateFilterPlan(
                expression="2023",
                start_date="2023-01-01",
                end_date="2023-12-31",
                column="BaslangicTarihi",
            )
        ],
        resolved_filters={
            "department": ResolvedFilterPlan(
                field="department",
                values=["Radyoloji"],
                grounded=True,
                confidence=1.0,
                match_type="exact",
            )
        },
    )
    assert manager.update(first_resolution, session_id, query_plan=retained_plan)

    resolution = manager.resolve("ayni filtreyle 2024 yilini goster", session_id)

    assert resolution.follow_up_detected is True
    assert resolution.retained_query_plan_snapshot is not None
