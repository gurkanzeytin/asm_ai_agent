import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome

logger = logging.getLogger(__name__)

_OUT_OF_SCOPE_MARKDOWN = """# Bu Soru Veri Kapsamı Dışında

Bu soru, hastane veritabanındaki verilerle yanıtlayabileceğim bir soruya benzemiyor.

## Yanıtlayabileceğim konular

- **Bölümler** — Kardiyoloji, Psikiyatri, Ortopedi vb. bölüm bazlı analizler
- **Doktorlar** — doktor listeleri, yoğunluk ve randevu sayıları
- **Hastalar** — hasta sayıları ve dağılımları
- **Randevular** — günlük/haftalık/aylık randevu istatistikleri
- **Reçeteler ve tanılar** — reçete ve tanı analizleri
- **Faturalar, laboratuvar testleri ve yatışlar**

## Örnek sorular

- "Bugün kaç randevu oluşturuldu?"
- "Kardiyoloji doktorlarını göster."
- "Son 6 ayın randevularını analiz et."

Sorunuzu bu veriler üzerinden yeniden ifade ederseniz yardımcı olabilirim.
"""


class GenerateOutOfScopeNode(IAgentNode):
    """Workflow node returning schema guidance when a question is outside the data domain (AG-022)."""

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateOutOfScopeNode execution started.")
        start_time = time.perf_counter()

        report_dto = GeneratedReport(
            title="Veri Kapsamı Dışında",
            markdown=_OUT_OF_SCOPE_MARKDOWN,
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
