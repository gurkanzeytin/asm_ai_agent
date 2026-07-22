# AI Reporting Agent Backend (Refactored Clean Architecture)

This is a production-ready, highly modular Clean Architecture backend structure for the AI Reporting Agent project. The architecture is framework-agnostic and isolates core entities, services, and agent execution nodes from frameworks like FastAPI and LangGraph.

## Core Architectural Layout

```
. (Project Root)
├── .gitignore
├── requirements.txt            # Python package dependencies
├── .env.example                # Example environment variables template
├── README.md                   # Project documentation
│
└── backend/
    ├── app/                    # Primary application package
    │   ├── main.py             # FastAPI entrypoint
    │   │
    │   ├── api/                # Controllers & API routes
    │   │   ├── deps.py         # Dependencies registry (e.g. database sessions)
    │   │   └── v1/
    │   │       ├── api.py      # Route mapping aggregator
    │   │       └── endpoints/
    │   │           ├── health.py  # Diagnostic check routes
    │   │           └── reports.py # Agent execution endpoints
    │   │
    │   ├── agent/              # Agent workflow state, node layout & orchestration
    │   │   ├── state.py        # Lifecycle state tracker type definition
    │   │   ├── workflow.py     # Link and compile nodes into graphs
    │   │   └── nodes/          # Isolated single-responsibility nodes
    │   │       ├── analyze_question.py
    │   │       ├── load_schema.py
    │   │       ├── generate_sql.py
    │   │       ├── validate_sql.py
    │   │       ├── execute_query.py
    │   │       └── generate_report.py
    │   │
    │   ├── core/               # App configuration & logging
    │   │   ├── config.py       # Pydantic Settings env parser
    │   │   └── logging.py      # Structured JSON/Console logging setup
    │   │
    │   ├── database/           # Relational DB engine & session makers
    │   │   ├── base.py         # Alembic migration metadata registry
    │   │   └── session.py      # SQLAlchemy session builders
    │   │
    │   ├── llm/                # Abstract LLM layer interfaces
    │   │   ├── provider.py     # Base abstract LLMProvider
    │   │   ├── ollama.py       # Ollama integration (Qwen3 8B)
    │   │   ├── prompt_builder.py # Markdown file loader and formatter
    │   │   └── parser.py       # Dynamic parser tools (e.g. SQL tag cleaner)
    │   │
    │   ├── prompts/            # External markdown files for prompt engineering
    │   │   ├── system_prompt.md
    │   │   ├── sql_generation.md
    │   │   └── report_generation.md
    │   │
    │   ├── models/             # Database ORM classes
    │   │   └── base.py         # Base declarative models
    │   │
    │   ├── repositories/       # Core repository data layers
    │   │   └── base.py         # Generic CRUD SQL patterns
    │   │
    │   ├── schemas/            # Request/Response serializations (Pydantic v2)
    │   │   ├── health.py
    │   │   └── report.py
    │   │
    │   ├── services/           # Decoupled business logic services
    │   │   ├── health_service.py
    │   │   ├── sql_service.py
    │   │   └── reporting_service.py
    │   │
    │   ├── shared/             # Shared constants, custom exceptions, and types
    │   │   ├── constants.py
    │   │   ├── exceptions.py
    │   │   └── types.py
    │   │
    │   └── validators/         # Safety & validation filters
    │       └── sql_validator.py # Secure SQL read-only verification
    │
    └── tests/                  # Integration and Unit testing suites
        ├── conftest.py         # Pytest session setup (in-memory db client)
        └── test_health.py      # Route assertion specs
```

## Quick Start

### 1. Installation
Create and activate your virtual environment:

```bash
python -m venv venv
# Windows (cmd/PowerShell)
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Database (Microsoft SQL Server)

The runtime database is **Microsoft SQL Server** — there is no local/dummy database:

- **Server**: `ASMPSHISBCK2` (default instance)
- **Database**: `PusulaComed`
- **Allowed object**: `dbo.vw_RandevuRaporu` (VIEW — the only queryable object)
- **Authentication**: Windows Authentication (the Windows identity of the process
  running the backend; no username/password is ever configured)

Requirements:

- **Microsoft ODBC Driver 18 for SQL Server** must be installed on the host.
- The Windows account running the backend needs SELECT permission on the view.

The application is strictly **read-only**: the SQL validation layer only accepts a
single SELECT (or CTE ending in SELECT) referencing `dbo.vw_RandevuRaporu`, and
rejects DML/DDL, EXEC, multiple statements, SQL comments, system catalogs, temporary
tables, and any other object.

Verify connectivity safely (prints no row data):

```bash
cd backend
python scripts/verify_mssql_connection.py
```

### 3. Environment Configuration
Create a `.env` file mapping configurations:

```bash
cp .env.example .env
```

Key database variables (see `.env.example` for the full list): `DB_SERVER`,
`DB_DATABASE`, `DB_DRIVER`, `DATABASE_SCHEMA`, `DATABASE_ALLOWED_OBJECTS`.

Ensure your Ollama local service is running (configured with Qwen3 8B model):
```bash
ollama run qwen3:8b
```

### 4. Startup dev server
Change directories to `backend/` and run uvicorn:

```bash
cd backend
uvicorn app.main:app --reload
```
- **Interactive docs UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Status diagnostics**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### 5. Tests
Execute tests from the `backend/` directory:

```bash
pytest
```

## Development Setup

This project uses standard linting, formatting, and hooks configuration to keep styles consistent.

### 1. Pre-commit Hooks Setup
Ensure dependencies are installed, then hook pre-commit into your git repository:

```bash
pre-commit install
```

The hooks will run automatically before each git commit, preventing poorly formatted code or unused variables from reaching remote branches.

### 2. Style Verification & Formatting Commands
To manually format and check the codebase:

- **Code Formatter (Black)**:
  ```bash
  black .
  ```
- **Code Linter (Ruff)**:
  ```bash
  ruff check .
  ```
- **Import Sorting (isort)**:
  ```bash
  isort .
  ```
- **Execute pre-commit hooks on all files**:
  ```bash
  pre-commit run --all-files
  ```

### 3. Running Test Suite
Execute pytest from the `backend/` directory:
```bash
pytest
```
