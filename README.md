# Sistema de Enriquecimiento de Metadatos con DSPy

Este sistema toma una URL y metadatos opcionales como entrada, ejecuta múltiples agentes de IA en paralelo y genera metadatos enriquecidos en formato JSON compatible con `metadata_template.json`.

## Estructura del Proyecto

```
code/
├── metadata_enricher.py   # CLI principal
├── orchestrator.py        # Orquestador de ejecución en paralelo
├── merger.py              # Fusión de resultados
├── agents/
│   ├── base.py            # Clase base de agentes con DSPy
│   └── registry.py        # Registro de agentes
├── schemas/
│   ├── input_schema.py    # Validación de entrada
│   ├── agent_config_schema.py  # Configuración de agentes/proveedores
│   ├── datacite_schema.py # Esquema DataCite
│   └── settings_schema.py # Configuración de la aplicación
├── config/
│   ├── agents.json        # Definiciones de agentes (12 agentes)
│   └── providers.json     # Configuraciones de proveedores LLM
├── examples/
│   └── sample_input.json  # Ejemplo de entrada
└── output/                # Directorio de salida (se crea automáticamente)
```

---

## Requisitos

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) para gestión de paquetes
- Variables de entorno:
  - `ZAI_API_KEY`: API key para ZAI Coding Plan (proveedor por defecto)

---

## Configuración

### 1. Configurar API keys

Copia `.env.example` a `.env`:

```bash
cp .env.example .env
```

Edita `.env` y configura tu `ZAI_API_KEY`.

### 2. Configurar proveedores (opcional)

Si deseas usar OpenAI, Anthropic u otros proveedores, edita `config/providers.json`:

```json
{
  "providers": {
    "zai-coding-plan": {
      "api_base": "https://api.z.ai/api/coding/paas/v4",
      "api_key_env": "ZAI_API_KEY"
    },
    "openai": {
      "api_key_env": "OPENAI_API_KEY"
    }
  }
}
```

### 3. Configurar agentes (opcional)

Edita `config/agents.json` para modificar, agregar o eliminar agentes. Cada agente tiene:

- `id`: Identificador único
- `name`: Nombre para mostrar
- `description`: Qué hace el agente
- `output_fields`: Lista de campos de salida
- `prompt_template`: Instrucciones para el LLM
- `depends_on`: Lista de IDs de agentes de los que depende
- `model`: Nombre del modelo (ej: `glm-5`, `gpt-4o`)
- `provider`: Nombre del proveedor desde `providers.json`
- `use_chain_of_thought`: Habilitar razonamiento CoT

### 4. Configurar datos de entrada

Crea archivos JSON en el directorio `examples/` (o usa un archivo individual):

```json
{
  "url": "https://datos.gob.cl/dataset/gastos-municipales",
  "title": "Gastos municipales (presupuesto abierto)",
  "description": "Datos abiertos sobre gastos municipales del presupuesto público..."
}
```

---

## Uso

### Procesar un archivo individual

```bash
uv run python metadata_enricher.py --input examples/sample_input.json
```

La salida se guardará en `output/sample_input_enriched.json`.

### Procesamiento por lote (múltiples archivos)

```bash
# Procesar todos los archivos JSON en un directorio
uv run python metadata_enricher.py --input examples/

# Procesar archivos que coinciden con un patrón glob
uv run python metadata_enricher.py --input "examples/*.json"
```

La salida se guardará en `output/` con un archivo resumen `_batch_summary.json`.

### Ubicación de salida personalizada

```bash
uv run python metadata_enricher.py --input examples/sample_input.json --output mis_resultados/
```

---

## Seguimiento de Tokens

El uso de tokens **siempre se rastrea** y se incluye en la salida. Los agentes se ejecutan en paralelo para maximizar el rendimiento mientras se registra el uso por agente.

```json
{
  "metadata": { ... },
  "token_usage": {
    "by_model": {
      "openai/glm-5": {
        "prompt_tokens": 7573,
        "completion_tokens": 6176,
        "total_tokens": 13749
      }
    },
    "by_agent": {
      "explorer": {
        "model": "openai/glm-5",
        "prompt_tokens": 580,
        "completion_tokens": 613,
        "total_tokens": 1193
      },
      "subject": {
        "model": "openai/glm-5",
        "prompt_tokens": 613,
        "completion_tokens": 654,
        "total_tokens": 1267
      }
    },
    "total": {
      "prompt_tokens": 7573,
      "completion_tokens": 6176,
      "total_tokens": 13749
    }
  },
  "processed_at": "2026-03-16T10:30:00",
  "input_file": "examples/sample_input.json"
}
```

Para procesamiento por lote, se crea un archivo resumen `_batch_summary.json` con los totales agregados.

---

## Archivos de Configuración

### providers.json

| Campo | Descripción |
|-------|-------------|
| `providers` | Objeto con configuraciones de proveedores |
| `providers.<nombre>.api_base` | URL del endpoint API |
| `providers.<nombre>.api_key_env` | Nombre de la variable de entorno para la API key |

### agents.json

| Campo | Descripción |
|-------|-------------|
| `id` | Identificador del agente |
| `name` | Nombre para mostrar |
| `description` | Qué hace el agente |
| `output_fields` | Lista de campos a extraer |
| `prompt_template` | Instrucciones para el LLM |
| `depends_on` | Lista de IDs de agentes dependientes |
| `model` | Modelo a usar |
| `provider` | Nombre del proveedor |
| `use_chain_of_thought` | Habilitar CoT |

---

## Formato de Salida

La salida coincide con la estructura de `metadata_template.json` con el wrapper `{"attributes": {...}}`.

### Campos Disponibles (todos opcionales, los campos vacíos se omiten)

| Campo | Descripción |
|-------|-------------|
| `titles` | Lista de objetos título |
| `descriptions` | Lista de objetos descripción |
| `languages` | Lista de objetos idioma |
| `resource` | Metadatos del recurso |
| `creators` | Lista de objetos creador |
| `publishers` | Lista de objetos editor |
| `subjects` | Lista de palabras clave |
| `dates` | Lista de objetos fecha |
| `temporal_events` | Lista de eventos temporales |
| `geo_locations` | Lista de ubicaciones geográficas |
| `rights` | Lista de derechos/licencias |
| `categories` | Lista de categorías |
| `audiences` | Lista de audiencias |
| `alternate_identifiers` | Lista de identificadores alternativos |
| `related_identifiers` | Lista de recursos relacionados |
| `funding_references` | Lista de información de financiamiento |
| `citations` | Lista de citas |
| `media_files` | Lista de archivos multimedia |

---

## Agentes Disponibles (12 en total)

| Agente | Propósito |
|--------|-----------|
| `explorer` | Extracción básica de metadatos |
| `creator_publisher` | Información de creador y editor |
| `subject` | Palabras clave y temas |
| `media_files` | Información de archivos multimedia |
| `temporal_geo` | Fechas y datos geográficos |
| `rights` | Licencias y derechos |
| `funding` | Información de financiamiento |
| `related_ids` | Identificadores relacionados |
| `alternate_ids` | Identificadores alternativos |
| `audiences` | Audiencia objetivo |
| `categories` | Clasificación por categorías |
| `citations` | Información de citas |

---

## Agregar Nuevos Agentes

Agrega la configuración a `config/agents.json`:

```json
{
  "id": "mi_agente",
  "name": "Mi Agente Personalizado",
  "description": "Extrae campos personalizados",
  "output_fields": ["campo_personalizado"],
  "prompt_template": "Extrae campo_personalizado del contexto...",
  "depends_on": ["explorer"],
  "use_chain_of_thought": true,
  "model": "glm-5",
  "provider": "zai-coding-plan"
}
```

---

## Estrategias de Contexto

- **accumulative** (por defecto): Cada agente recibe todas las salidas anteriores
- **layered**: Los agentes solo reciben la salida del explorer + entrada inicial

---

## Solución de Problemas

| Problema | Solución |
|----------|----------|
| `FileNotFoundError` | Verifica que las rutas de archivo sean correctas |
| `AuthenticationError` | Verifica la API key en `.env` |
| `Invalid JSON` | Valida el formato del archivo de entrada |
| Timeout del agente | Verifica la conectividad con la API |

---

## Desarrollo

### Estructura del Proyecto

```
code/
├── metadata_enricher.py   # Punto de entrada CLI
├── orchestrator.py        # Ejecución en paralelo
├── merger.py              # Fusión de salidas
├── agents/
│   ├── base.py            # Clase base de agente
│   └── registry.py        # Registro de agentes
├── schemas/
│   ├── input_schema.py    # Validación de entrada
│   ├── agent_config_schema.py  # Esquemas de configuración
│   ├── datacite_schema.py # Esquema DataCite
│   └── settings_schema.py # Configuración de la app
├── config/
│   ├── agents.json        # Definiciones de agentes
│   └── providers.json     # Configuraciones de proveedores
├── examples/
│   └── sample_input.json  # Ejemplo de entrada
├── output/                # Directorio de salida
└── .env                   # API keys
```

### Prueba Rápida

```bash
uv run python metadata_enricher.py --input examples/sample_input.json
```

---

## Licencia

MIT
