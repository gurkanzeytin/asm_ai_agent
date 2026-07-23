import logging
import time
from functools import lru_cache

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome

logger = logging.getLogger(__name__)

_EXAMPLE_QUESTIONS = (
    "Bugün kaç randevu oluşturuldu?",
    "Şubelere göre randevu sayılarını göster.",
    "Son 6 ayın randevu eğilimini özetle.",
)
_UNSAFE_WRITE_SIGNAL_PREFIX = "unsafe_write_intent:"


def _unsafe_write_markdown() -> str:
    return "\n".join(
        [
            "# Bu İstek Güvenlik Nedeniyle Çalıştırılamaz",
            "",
            "Bu ajan yalnızca salt-okunur analiz sorguları üretebilir ve çalıştırabilir.",
            "Tablo silme, kayıt güncelleme, veri ekleme veya şema değiştirme amaçlı SQL üretemem.",
            "",
            "Randevu verileri üzerinde analiz yapmak isterseniz şu tarz sorular sorabilirsiniz:",
            '- "Bugünkü randevu sayısı kaç?"',
            '- "Son 20 randevuyu getir."',
            '- "Branşlara göre randevu grafiği çiz."',
        ]
    )


@lru_cache(maxsize=1)
def _build_capability_markdown() -> str:
    """Derives the 'what I can answer' guidance from the real catalogs
    (AI-INTELLIGENCE-018, item 4) instead of a hardcoded, stale capability
    list — the previous static text claimed support for prescriptions,
    diagnoses, invoices, laboratory tests, and hospitalizations, none of
    which exist on the single allowed view (dbo.vw_RandevuRaporu)."""
    from app.semantics import catalog

    try:
        columns = catalog.load_column_catalog().columns
        metrics = catalog.load_metric_catalog().metrics
    except Exception as error:  # never block guidance on a catalog load failure
        logger.error("Capability catalog load failed; using minimal guidance: %s", error)
        columns, metrics = [], []

    dimension_lines = sorted(
        {
            spec.business_name
            for spec in columns
            if spec.groupable and not spec.pii and spec.data_role != "time_dimension"
        }
    )
    metric_lines = sorted({metric.name for metric in metrics})

    sections = ["# Bu Soru Veri Kapsamı Dışında", "", (
        "Bu soru, hastane randevu veritabanındaki verilerle yanıtlayabileceğim "
        "bir soruya benzemiyor."
    ), "", "## Yanıtlayabileceğim konular"]
    if metric_lines:
        sections.append("")
        sections.append("**Ölçümler:** " + ", ".join(metric_lines))
    if dimension_lines:
        sections.append("")
        sections.append("**Kırılımlar:** " + ", ".join(dimension_lines))
    sections.append("")
    sections.append("## Örnek sorular")
    sections.extend(f'- "{example}"' for example in _EXAMPLE_QUESTIONS)
    sections.append("")
    sections.append("Sorunuzu bu veriler üzerinden yeniden ifade ederseniz yardımcı olabilirim.")
    return "\n".join(sections)


class GenerateOutOfScopeNode(IAgentNode):
    """Returns guidance when a question is outside the data domain."""

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateOutOfScopeNode execution started.")
        start_time = time.perf_counter()

        unsafe_write_requested = any(
            signal.startswith(_UNSAFE_WRITE_SIGNAL_PREFIX)
            for signal in state.answerability_signals
        )
        if unsafe_write_requested:
            report_dto = GeneratedReport(
                title="Güvenli Olmayan SQL İsteği",
                markdown=_unsafe_write_markdown(),
                provider="static",
                model="read_only_safety_guidance",
                latency_ms=0.0,
            )
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "outcome": AgentOutcome.OUT_OF_SCOPE.value,
                    "current_node": "generate_out_of_scope",
                    "completed_nodes": state.completed_nodes + ["generate_out_of_scope"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_out_of_scope": duration},
                }
            )

        report_dto = GeneratedReport(
            title="Veri Kapsamı Dışında",
            markdown=_build_capability_markdown(),
            provider="static",
            model="out_of_scope_node",
            latency_ms=0.0,
        )

        duration = (time.perf_counter() - start_time) * 1000
        logger.info(
            "GenerateOutOfScopeNode completed: question diverted to schema guidance.",
            extra={"question": state.question},
        )

        return state.model_copy(
            update={
                "generated_report": report_dto,
                "outcome": AgentOutcome.OUT_OF_SCOPE.value,
                "current_node": "generate_out_of_scope",
                "completed_nodes": state.completed_nodes + ["generate_out_of_scope"],
                "duration_ms": state.duration_ms + duration,
                "node_timings": {**state.node_timings, "generate_out_of_scope": duration},
            }
        )
