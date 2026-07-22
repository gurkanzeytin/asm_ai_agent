"""Hard result-size limits shared by execution and presentation boundaries."""

DEFAULT_TABLE_PAGE_SIZE = 100
MAX_UI_ROWS_PER_PAGE = 100
MAX_API_ROWS = 500
MAX_DATABASE_FETCH_ROWS = 1000
DEFAULT_GROUPED_RESULT_LIMIT = 100

MAX_LLM_TOP_ROWS = 10
MAX_LLM_BOTTOM_ROWS = 10

OVERSIZED_ANALYTICAL_RESULT_MESSAGE = (
    "Bu sorgu beklenenden fazla ayrıntılı kayıt üretti. Sonuçlar güvenli biçimde "
    "sınırlandırıldı. Daha anlamlı bir analiz için bölüm, doktor, şube veya tarih "
    "bazında bir kırılım kullanılabilir."
)

