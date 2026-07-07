from fastapi import APIRouter, HTTPException

from app.schemas.report import ReportRequest, ReportResponse
from app.services.reporting_service import ReportingService

router = APIRouter()


@router.post("/", response_model=ReportResponse)
async def generate_report_endpoint(payload: ReportRequest) -> ReportResponse:
    """Takes user prompt and returns compiled analytical reports via ReportingService."""
    try:
        results = await ReportingService.generate_report(payload.query)
        return ReportResponse(**results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report execution failed: {str(e)}") from e
