"""Visor UI translations — Spanish (default) and English.

Scope is deliberately narrow: only visor's own chrome (labels, buttons,
captions, notifications) is translated here. Pipeline/agent content --
config/agents.yaml's prompts, LLM responses, log lines from the library --
stays whatever language it already is; translating that is a metadata
quality/prompt-engineering concern, not a visor UI concern.

Language choice lives in NiceGUI's app.storage.user (a signed per-browser
cookie, see visor/settings.py's storage_secret()) rather than the shared
settings.json used for API keys -- keeping it per-browser matters for
hosted mode (see visor/AGENTS.md's session-isolation history): one
person's language choice must never change the UI language for anyone
else connected to the same process. current_language()/set_language()
must only be called from inside a NiceGUI page/event context (never at
import time), since that's what app.storage.user requires.
"""

from __future__ import annotations

from typing import Any

from nicegui import app

DEFAULT_LANGUAGE = "es"

# Value -> display label, in the order shown in the language picker.
LANGUAGES: dict[str, str] = {
    "es": "Español",
    "en": "English",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        # -- app.py: tabs, language picker --
        "app.tab.settings": "Configuración",
        "app.tab.agents": "Agentes",
        "app.tab.run": "Ejecutar",
        "app.language.label": "Idioma",
        "app.config_error.title": "Problema de configuración",
        "app.config_error.unknown": "Error de configuración desconocido",
        # -- settings_page.py --
        "settings.title": "Configuración",
        "settings.intro": (
            "Las claves de API se guardan solo en este equipo y se usan solo "
            "para hablar con el proveedor al que pertenece cada clave — "
            "nunca se incluyen en la aplicación ni se comparten con nadie."
        ),
        "settings.providers.title": "Proveedores",
        "settings.providers.intro": (
            "Datos de conexión y clave de API de cada proveedor — qué "
            "proveedor usa cada agente se define en la pestaña Agentes."
        ),
        "settings.providers.used_by": "usado por: {agents}",
        "settings.providers.not_used": "no usado actualmente por ningún agente",
        "settings.providers.remove_blocked": "No se puede quitar '{name}' — usado por: {users}",
        "settings.providers.removed": "Proveedor '{name}' eliminado",
        "settings.providers.dataverse_subject_classifier": "Clasificador de tema de exportación a Dataverse",
        "settings.base_url.label": "URL base",
        "settings.key.label": "Clave de {env}",
        "settings.add_provider.title": "Añadir un proveedor",
        "settings.add_provider.help": (
            "Elige uno de la lista para autocompletar sus datos de conexión, "
            "o \"Otro (personalizado)\" para un proveedor que no aparece aquí."
        ),
        "settings.add_provider.custom": "Otro (personalizado)",
        "settings.add_provider.provider_label": "Proveedor",
        "settings.add_provider.name_label": "Nombre",
        "settings.add_provider.url_label": "URL base",
        "settings.add_provider.env_label": "Nombre de la variable de entorno para su clave",
        "settings.add_provider.key_label": "Clave de API",
        "settings.add_provider.name_required": "El nombre del proveedor es obligatorio",
        "settings.add_provider.duplicate": "El proveedor '{name}' ya existe",
        "settings.add_provider.added": "Proveedor '{name}' añadido — define su clave abajo y guarda",
        "settings.add_provider.submit": "Añadir proveedor",
        "settings.orcid.title": "Opcional — permite buscar por nombre de autor en ORCID",
        "settings.save": "Guardar y continuar",
        "settings.saved": "Configuración guardada",
        # -- run_page.py --
        "run.title": "Ejecutar un recurso",
        "run.mode.form": "Rellenar un formulario",
        "run.mode.paste": "Pegar JSON",
        "run.mode.upload": "Subir un archivo",
        "run.field.url": "URL",
        "run.field.title": "Título",
        "run.field.description": "Descripción",
        "run.field.doi": "DOI (opcional)",
        "run.field.publisher": "Editor (opcional)",
        "run.field.frequency": "Frecuencia (opcional)",
        "run.field.fetched_content": "Contenido obtenido (opcional)",
        "run.field.context_hints": "Pistas de contexto (opcional)",
        "run.field.fetched_content.hint": (
            "Opcional — déjalo en blanco para que el pipeline lo obtenga "
            "automáticamente de la URL (ver Comportamiento del pipeline en "
            "la pestaña Agentes)."
        ),
        "run.field.context_hints.hint": (
            "Opcional — pistas verificadas externamente que el propio texto "
            "del recurso no indica (año de publicación, número de archivos, "
            "autores, licencia, cualquier cosa que ya sepas). Se confía en "
            "ellas igual que en el contenido del recurso, salvo que su texto "
            "diga lo contrario."
        ),
        "run.json_template.title": "Título del dataset",
        "run.json_template.description": "Una breve descripción de lo que contiene este dataset.",
        "run.json_template.doi": "DOI existente, si este recurso ya tiene uno (opcional)",
        "run.json_template.publisher": "Organización que publica (opcional)",
        "run.json_template.frequency": "Frecuencia de actualización, p. ej. Mensual (opcional)",
        "run.json_template.fetched_content": "HTML/texto ya obtenido de la URL, si lo tienes (opcional)",
        "run.json_template.context_hints": (
            "Pistas verificadas externamente que el propio texto del recurso no indica -- "
            "p. ej. año de publicación, número de archivos, autores (opcional)"
        ),
        "run.paste.help": "¿Cómo debería ser este JSON?",
        "run.paste.label": "Pega el JSON en bruto",
        "run.upload.label": "Subir un archivo .json de entrada",
        "run.upload.loaded": "Se cargó {filename}",
        "run.button.run": "Ejecutar",
        "run.button.clear_cache": "Vaciar caché",
        "run.clear_cache.hint": (
            "Con la misma entrada, ahora mismo se repite al instante una "
            "respuesta ya guardada en caché — vacía la caché primero para "
            "forzar una llamada nueva al LLM."
        ),
        "run.clear_cache.done": "Caché vaciada — la próxima ejecución volverá a llamar al LLM.",
        "run.error.fill_one": "Rellena al menos URL, título o descripción.",
        "run.error.paste_empty": "Pega primero algo de JSON.",
        "run.error.upload_first": "Sube primero un archivo.",
        "run.error.read_input": "No se pudo leer la entrada: {error}",
        "run.gate.title": "Añade primero una clave de API",
        "run.gate.missing": "Falta: {fields}",
        "run.gate.button": "Ir a Configuración",
        "run.running.title": "Ejecutando…",
        "run.running.hint": "Esto puede tardar un minuto o más — una llamada al LLM por cada paso del pipeline.",
        "run.running.elapsed": "Transcurrido: {duration}",
        "run.result.download_json": "Descargar JSON",
        "run.result.download_dataverse": "Descargar JSON de Dataverse",
        "run.result.run_another": "Ejecutar otro",
        "run.result.completed_in": "Completado en {duration}",
        "run.result.warnings_title": "Algunos campos están incompletos o un PID no se verificó:",
        "run.result.title": "Resultado",
        "run.result.failure_title": "Este recurso no se pudo procesar",
        "run.result.unknown_error": "Error desconocido",
        "run.result.auth_error": (
            "El proveedor rechazó la clave de API. Revísala en Configuración "
            "— puede faltar, tener un error o estar revocada. ({raw})"
        ),
        "run.result.show_details": "Ver detalles ({count} líneas)",
        "run.submitted_input": "Entrada enviada",
        "run.tokens_used": "Tokens usados: {prompt:,} entrada / {completion:,} salida ({total:,} total)",
        "run.models_used": "Modelos usados:",
        "run.dataverse.provider_missing": (
            "Proveedor de exportación a Dataverse '{provider}' no encontrado "
            "en esta configuración — el tema será 'Other' por defecto"
        ),
        "run.dataverse.build_failed": "No se pudo construir el JSON de Dataverse: {error}",
        "run.dataverse.no_result": "No se pudo construir el JSON de Dataverse: sin resultado",
        # -- agents_page.py --
        "agents.title": "Agentes",
        "agents.intro": (
            "Cada paso del pipeline lo gestiona un agente. Define abajo qué "
            "proveedor y modelo usa — deja el modelo en blanco para usar el "
            "predeterminado del proveedor. Añade la clave de API "
            "correspondiente en la pestaña Configuración."
        ),
        "agents.download": "Descargar configuración (JSON)",
        "agents.upload": "Subir configuración (JSON)",
        "agents.pipeline_behavior.title": "Comportamiento del pipeline",
        "agents.pipeline_behavior.intro": "Se aplica a todo el pipeline, no a un solo agente.",
        "agents.checkbox.content_fetch": "Obtener el contenido de la página automáticamente",
        "agents.checkbox.content_fetch.tooltip": (
            "Obtiene la URL de cada recurso y pasa el texto de la página a "
            "los agentes cuando aún no lo tienen."
        ),
        "agents.checkbox.doi_resolution": "Resolver DOIs automáticamente",
        "agents.checkbox.doi_resolution.tooltip": (
            "Busca un DOI aislado para ayudar a completar metadatos que falten."
        ),
        "agents.checkbox.identifier_enrichment": "Enriquecer identificadores (ROR / ORCID / ISNI)",
        "agents.checkbox.identifier_enrichment.tooltip": (
            "Resuelve identificadores ROR/ISNI de autores, editores y "
            "financiadores que los agentes dejaron en blanco."
        ),
        "agents.checkbox.validate_pids": "Validar identificadores persistentes",
        "agents.checkbox.validate_pids_live": "Validar PIDs en vivo (llamadas reales a la red)",
        "agents.provider_label": "Proveedor",
        "agents.model_label": "Modelo",
        "agents.pick_provider_first": "Elige primero un proveedor",
        "agents.refresh_models.tooltip": "Obtener la lista real de modelos de este proveedor",
        "agents.temperature_label": "Temperatura",
        "agents.advanced": "Avanzado",
        "agents.runs_after": "Se ejecuta después de: {deps}",
        "agents.runs_after.nothing": "(nada — se ejecuta primero)",
        "agents.produces_fields": "Produce los campos: {fields}",
        "agents.tools": "Herramientas: {tools}",
        "agents.extra_body": "Opciones extra de la petición: {extra_body}",
        "agents.prompt_readonly": "Prompt (solo lectura aquí — edítalo en el JSON descargado)",
        "agents.dataverse.title": "Exportación a Dataverse — Clasificador de tema",
        "agents.dataverse.intro": (
            "Opcional: clasifica este recurso en la categoría de tema que "
            "Dataverse exige al descargar un JSON en formato Dataverse. "
            "Desactívalo para usar siempre \"Other\", sin ninguna llamada "
            "adicional al LLM."
        ),
        "agents.dataverse.enabled": "Activado",
        "agents.dataverse.model_label": "Modelo — basta un nivel rápido/económico para clasificar entre 14 opciones",
        "agents.save": "Guardar cambios",
        "agents.save.done": "Configuración de agentes actualizada para esta sesión",
        "agents.models.fetch_failed": "No se pudieron obtener los modelos de '{provider}': {error}",
        "agents.models.loaded": "Se cargaron {count} modelos para '{provider}'",
        "agents.upload.rejected": "No se pudo aplicar este archivo: {error}",
        "agents.upload.applied": "Configuración subida aplicada ({count} agentes)",
    },
    "en": {
        "app.tab.settings": "Settings",
        "app.tab.agents": "Agents",
        "app.tab.run": "Run",
        "app.language.label": "Language",
        "app.config_error.title": "Configuration problem",
        "app.config_error.unknown": "Unknown configuration error",
        "settings.title": "Settings",
        "settings.intro": (
            "API keys are saved only on this computer and used only to talk "
            "to the provider each key belongs to — never bundled with the "
            "app or shared with anyone else."
        ),
        "settings.providers.title": "Providers",
        "settings.providers.intro": (
            "Connection details and API key for every provider — which "
            "one each agent actually uses is set in the Agents tab."
        ),
        "settings.providers.used_by": "used by: {agents}",
        "settings.providers.not_used": "not currently used by any agent",
        "settings.providers.remove_blocked": "Can't remove '{name}' — used by: {users}",
        "settings.providers.removed": "Removed provider '{name}'",
        "settings.providers.dataverse_subject_classifier": "dataverse export's Subject Classifier",
        "settings.base_url.label": "Base URL",
        "settings.key.label": "{env} key",
        "settings.add_provider.title": "Add a provider",
        "settings.add_provider.help": (
            "Pick one from the list to autofill its connection details, "
            "or choose \"Other (custom)\" for a provider not listed here."
        ),
        "settings.add_provider.custom": "Other (custom)",
        "settings.add_provider.provider_label": "Provider",
        "settings.add_provider.name_label": "Name",
        "settings.add_provider.url_label": "Base URL",
        "settings.add_provider.env_label": "Environment variable name for its key",
        "settings.add_provider.key_label": "API key",
        "settings.add_provider.name_required": "Provider name is required",
        "settings.add_provider.duplicate": "Provider '{name}' already exists",
        "settings.add_provider.added": "Added provider '{name}' — set its key below and Save",
        "settings.add_provider.submit": "Add provider",
        "settings.orcid.title": "Optional — lets ORCID be searched by author name",
        "settings.save": "Save & Continue",
        "settings.saved": "Settings saved",
        "run.title": "Run a resource",
        "run.mode.form": "Fill a form",
        "run.mode.paste": "Paste JSON",
        "run.mode.upload": "Upload a file",
        "run.field.url": "Url",
        "run.field.title": "Title",
        "run.field.description": "Description",
        "run.field.doi": "DOI (optional)",
        "run.field.publisher": "Publisher (optional)",
        "run.field.frequency": "Frequency (optional)",
        "run.field.fetched_content": "Fetched Content (optional)",
        "run.field.context_hints": "Context hints (optional)",
        "run.field.fetched_content.hint": (
            "Optional — leave blank to let the pipeline fetch this "
            "automatically from the URL (see Pipeline behavior in "
            "the Agents tab)."
        ),
        "run.field.context_hints.hint": (
            "Optional — externally verified clues the resource's own "
            "text doesn't state (publish year, file count, authors, "
            "license, anything you already know). Trusted like the "
            "resource's own content unless its text says otherwise."
        ),
        "run.json_template.title": "Dataset title",
        "run.json_template.description": "A short description of what this dataset contains.",
        "run.json_template.doi": "Existing DOI, if this resource already has one (optional)",
        "run.json_template.publisher": "Publishing organization (optional)",
        "run.json_template.frequency": "Update frequency, e.g. Monthly (optional)",
        "run.json_template.fetched_content": "Raw HTML/text already fetched from the URL, if you have it (optional)",
        "run.json_template.context_hints": (
            "Externally verified clues the resource's own text doesn't state -- "
            "e.g. publish year, file count, authors (optional)"
        ),
        "run.paste.help": "What should this JSON look like?",
        "run.paste.label": "Paste raw JSON",
        "run.upload.label": "Upload a .json input file",
        "run.upload.loaded": "Loaded {filename}",
        "run.button.run": "Run",
        "run.button.clear_cache": "Clear cache",
        "run.clear_cache.hint": (
            "Same input currently reruns instantly from a cached response — "
            "clear the cache first to force a fresh LLM call."
        ),
        "run.clear_cache.done": "Cache cleared — the next run will call the LLM again.",
        "run.error.fill_one": "Fill at least url, title, or description.",
        "run.error.paste_empty": "Paste some JSON first.",
        "run.error.upload_first": "Upload a file first.",
        "run.error.read_input": "Could not read input: {error}",
        "run.gate.title": "Add an API key first",
        "run.gate.missing": "Missing: {fields}",
        "run.gate.button": "Go to Settings",
        "run.running.title": "Running…",
        "run.running.hint": "This can take a minute or more — one LLM call per pipeline step.",
        "run.running.elapsed": "Elapsed: {duration}",
        "run.result.download_json": "Download JSON",
        "run.result.download_dataverse": "Download Dataverse JSON",
        "run.result.run_another": "Run another",
        "run.result.completed_in": "Completed in {duration}",
        "run.result.warnings_title": "Some fields are incomplete or a PID didn't check out:",
        "run.result.title": "Result",
        "run.result.failure_title": "This resource could not be processed",
        "run.result.unknown_error": "Unknown error",
        "run.result.auth_error": (
            "The API key for this provider was rejected. Check it in "
            "Settings — it may be missing, mistyped, or revoked. ({raw})"
        ),
        "run.result.show_details": "Show details ({count} lines)",
        "run.submitted_input": "Submitted input",
        "run.tokens_used": "Tokens used: {prompt:,} in / {completion:,} out ({total:,} total)",
        "run.models_used": "Models used:",
        "run.dataverse.provider_missing": (
            "Dataverse export provider '{provider}' not found in this "
            "config — Subject will default to 'Other'"
        ),
        "run.dataverse.build_failed": "Could not build Dataverse JSON: {error}",
        "run.dataverse.no_result": "Could not build Dataverse JSON: no result",
        # -- agents_page.py --
        "agents.title": "Agents",
        "agents.intro": (
            "Each step of the pipeline is handled by one agent. Set which provider "
            "and model it uses below — leave model blank to use the provider's "
            "default. Add the matching API key in the Settings tab."
        ),
        "agents.download": "Download configuration (JSON)",
        "agents.upload": "Upload configuration (JSON)",
        "agents.pipeline_behavior.title": "Pipeline behavior",
        "agents.pipeline_behavior.intro": "These apply to the whole pipeline, not a single agent.",
        "agents.checkbox.content_fetch": "Fetch page content automatically",
        "agents.checkbox.content_fetch.tooltip": (
            "Fetches each resource's URL and feeds the page text to the "
            "agents when they don't already have it."
        ),
        "agents.checkbox.doi_resolution": "Resolve DOIs automatically",
        "agents.checkbox.doi_resolution.tooltip": "Looks up a bare DOI to help fill in missing metadata.",
        "agents.checkbox.identifier_enrichment": "Enrich identifiers (ROR / ORCID / ISNI)",
        "agents.checkbox.identifier_enrichment.tooltip": (
            "Resolves ROR/ISNI identifiers for creators, publishers, and "
            "funders the agents left blank."
        ),
        "agents.checkbox.validate_pids": "Validate persistent identifiers",
        "agents.checkbox.validate_pids_live": "Validate PIDs live (real network calls)",
        "agents.provider_label": "Provider",
        "agents.model_label": "Model",
        "agents.pick_provider_first": "Pick a provider first",
        "agents.refresh_models.tooltip": "Fetch this provider's real model list",
        "agents.temperature_label": "Temperature",
        "agents.advanced": "Advanced",
        "agents.runs_after": "Runs after: {deps}",
        "agents.runs_after.nothing": "(nothing — runs first)",
        "agents.produces_fields": "Produces fields: {fields}",
        "agents.tools": "Tools: {tools}",
        "agents.extra_body": "Extra request options: {extra_body}",
        "agents.prompt_readonly": "Prompt (read-only here — edit via the downloaded JSON)",
        "agents.dataverse.title": "Dataverse Export — Subject Classifier",
        "agents.dataverse.intro": (
            "Optional: classifies this resource into Dataverse's required Subject "
            "category when you download a Dataverse-format JSON. Turn off to always "
            "use \"Other\" instead, with no extra LLM call."
        ),
        "agents.dataverse.enabled": "Enabled",
        "agents.dataverse.model_label": "Model — a fast/cheap tier is enough for a 14-way classification",
        "agents.save": "Save changes",
        "agents.save.done": "Agent settings updated for this session",
        "agents.models.fetch_failed": "Could not fetch models for '{provider}': {error}",
        "agents.models.loaded": "Loaded {count} models for '{provider}'",
        "agents.upload.rejected": "Could not apply this file: {error}",
        "agents.upload.applied": "Applied uploaded configuration ({count} agents)",
    },
}


def current_language() -> str:
    """Normally called from inside a page render or event handler, where
    app.storage.user resolves via the request's session cookie. Falls back
    to the default language outside that context (e.g. a unit test calling
    a page-module function directly, with no app booted at all) instead of
    raising -- t() must stay safely callable from plain, non-UI code paths
    like _handle_upload's error branch."""
    try:
        value = app.storage.user.get("language", DEFAULT_LANGUAGE)
    except RuntimeError:
        return DEFAULT_LANGUAGE
    return value if value in _TRANSLATIONS else DEFAULT_LANGUAGE


def set_language(language: str) -> None:
    app.storage.user["language"] = language if language in _TRANSLATIONS else DEFAULT_LANGUAGE


def t(key: str, **kwargs: Any) -> str:
    """Look up *key* in the current language, falling back to the default
    language and then to the bare key itself (visible-but-ugly beats a
    crash if a key is ever missing from one table)."""
    table = _TRANSLATIONS.get(current_language(), _TRANSLATIONS[DEFAULT_LANGUAGE])
    template = table.get(key) or _TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs) if kwargs else template
