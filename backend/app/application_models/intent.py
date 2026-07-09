from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    DATABASE_QUERY = "database_query"
    GENERAL_CHAT = "general_chat"
    HELP = "help"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    intent: IntentType = Field(..., description="The classified intent type.")
    confidence: float = Field(..., description="Classification confidence score.")
    reason: Optional[str] = Field(default=None, description="Detailed explanation of classification.")
    matched_keywords: List[str] = Field(default_factory=list, description="Keywords matched.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata dictionary for routing details.")
