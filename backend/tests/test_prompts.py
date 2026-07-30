import pytest

from app.prompts.loader import PromptLoaderError, prompt_loader
from app.prompts.renderer import PromptRendererError, prompt_renderer


def test_prompt_loader_caching():
    """Verifies that PromptLoader works as a singleton and resolves requests from cache."""
    prompt_loader.clear_cache()

    # First load reads from disk
    first_load = prompt_loader.get_prompt("system_prompt")
    assert "Mitis" in first_load

    # Manually overwrite cache memory data to prove cache hit verification
    prompt_loader._cache["system_prompt.md"] = "CACHE OVERRIDE VALUE"

    # Second read retrieves cached payload
    second_load = prompt_loader.get_prompt("system_prompt")
    assert second_load == "CACHE OVERRIDE VALUE"

    # Cleared cache reads from disk again
    prompt_loader.clear_cache()
    reloaded_load = prompt_loader.get_prompt("system_prompt")
    assert "Mitis" in reloaded_load


def test_prompts_include_natural_turkish_style_rules():
    prompt_loader.clear_cache()

    system_prompt = prompt_loader.get_prompt("system_prompt")
    report_prompt = prompt_loader.get_prompt("report_generation")

    assert "natural" in system_prompt
    assert "Doğal, kısa ve konuşulur Türkçe kullan" in report_prompt
    assert "Mekanik rapor kalıpları" in report_prompt
    assert "Sorgu sonucu" not in report_prompt
    assert "listelenmiştir" not in report_prompt
    assert "tespit edilmiştir" not in report_prompt


def test_prompt_loader_missing_file():
    """Verifies that PromptLoader raises PromptLoaderError when requested files are missing."""
    with pytest.raises(PromptLoaderError) as exc:
        prompt_loader.get_prompt("unknown_template_file")
    assert "could not be found at path" in str(exc.value)


def test_prompt_renderer_substitution():
    """Verifies that the renderer replaces template placeholders successfully."""
    template = "Hello {user}, dialect is {dialect}."
    variables = {"user": "Alice", "dialect": "PostgreSQL"}

    output = prompt_renderer.render(template, variables)
    assert output == "Hello Alice, dialect is PostgreSQL."


def test_prompt_renderer_missing_parameters():
    """Verifies that the renderer raises PromptRendererError when variables are missing."""
    template = "Dialect is {dialect}."
    variables = {"not_dialect": "MySQL"}

    with pytest.raises(PromptRendererError) as exc:
        prompt_renderer.render(template, variables)
    assert "Missing required parameter" in str(exc.value)
