# Sistema de Enriquecimiento de Metadatos con DSPy

Este sistema toma una URL y metadatos opcionales como entrada, ejecuta múltiples agentes de IA en paralelo y genera metadatos enriquecidos en formato JSON compatible con `metadata_template.json`.

## Estructura del Proyecto

```
├── config/
│   ├── agents.json        # Definiciones de agentes (12 agentes, config original)
│   ├── agents_v2.json     # Config alternativa (18 agentes, un campo por agente)
│   └── providers.json     # Configuraciones de proveedores LLM
├── examples/
│   ├── sample_input01.json  # Ejemplo con fetched_content prellenado
│   └── sample_input02.json  # Ejemplo sin fetched_content (se auto-descarga)
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

Hay dos archivos de configuración de agentes:

- `config/agents.json`: 12 agentes, múltiples `output_fields` por agente (original)
- `config/agents_v2.json`: 18 agentes, un `output_field` por agente (recomendado)

Usa el flag `-c` o `--config` para seleccionar cuál config usar:

```bash
uv run python metadata_enricher.py -i examples/sample_input02.json -c config/agents_v2.json
```

Para modificar agentes, edita el archivo de configuración correspondiente. Cada agente tiene:

- `id`: Identificador único
- `name`: Nombre para mostrar
- `description`: Qué hace el agente
- `output_fields`: Lista de campos de salida
- `prompt_template`: Instrucciones para el LLM
- `depends_on`: Lista de IDs de agentes de los que depende
- `llm_config`: Configuración del modelo (objeto con `model`, `provider`, `temperature`, `max_tokens`)
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
uv run python metadata_enricher.py --input examples/sample_input.json --output mis_resultados.json
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

## Agentes Disponibles

### agents.json (12 agentes)

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

### agents_v2.json (18 agentes, recomendado)

| Agente | Propósito |
|--------|-----------|
| `resource` | Metadatos del recurso |
| `alternate_identifiers` | Identificadores alternativos |
| `audiences` | Audiencia objetivo |
| `categories` | Clasificación por categorías |
| `citations` | Información de citas |
| `creators` | Información de creadores |
| `dates` | Fechas del recurso |
| `descriptions` | Descripciones |
| `funding_references` | Información de financiamiento |
| `geo_locations` | Ubicaciones geográficas |
| `languages` | Idiomas |
| `media_files` | Archivos multimedia |
| `publishers` | Editores/publicadores |
| `related_identifiers` | Identificadores relacionados |
| `rights` | Licencias y derechos |
| `subjects` | Palabras clave y temas |
| `temporal_events` | Eventos temporales |
| `titles` | Títulos |

---

## ⚠️ Reglas Críticas de Configuración de Agentes

Para que el sistema funcione correctamente, los agentes deben seguir estas reglas obligatorias:

### Regla 1: Un solo campo en `output_fields`

Cada agente debe tener **exactamente un campo** en `output_fields` — su campo primario.

```json
// ✅ CORRECTO
"output_fields": ["creators"]

// ❌ INCORRECTO — causa campos huérfanos en la salida
"output_fields": ["creators", "name_identifier", "affiliations"]
```

Los sub-campos (como `name_identifier`, `affiliations`) deben estar **anidados dentro** del objeto en el `prompt_template`, no declarados como output_fields separados.

### Regla 2: El prompt SIEMPRE debe envolver la salida en el campo primario

El `prompt_template` de cada agente debe retornar JSON **envuelto** en su campo primario:

```json
// ✅ CORRECTO — envuelto en el campo primario
{
  "creators": [
    {
      "creator_name": "...",
      "creator_name_type": "Organizational",
      "name_identifiers": [],
      "affiliations": []
    }
  ]
}

// ❌ INCORRECTO — plano, causa campos huérfanos
{
  "creator_name": "...",
  "creator_name_type": "Organizational",
  "name_identifiers": [],
  "affiliations": []
}
```

### Regla 3: Los arrays anidados van DENTRO del objeto padre

Cuando un campo tiene sub-arrays (como `funder_identifiers` dentro de `funding_references`), estos deben estar anidados:

```json
// ✅ CORRECTO
{
  "funding_references": [
    {
      "funder_name": "ANID",
      "funder_identifiers": [
        {"funder_identifier": "...", "funder_identifier_type": "ROR"}
      ]
    }
  ]
}

// ❌ INCORRECTO — funder_identifiers como campo separado
"output_fields": ["funding_references", "funder_identifiers"]
```

### Regla 4: Cuando no hay datos, retornar array vacío

```json
// ✅ CORRECTO
{"funding_references": []}

// ❌ INCORRECTO — sin wrapper
[]
```

### Excepción: el agente `resource`

El agente `resource` es la única excepción. Su `output_fields` es `["resource"]` pero el prompt retorna campos planos que el merger automáticamente reubica al dict `resource`:

```json
// El agente resource retorna:
{
  "identifier": "https://...",
  "identifier_type": "URL",
  "publication_year": "2024",
  "resource_type": "Dataset"
}
// El merger los reubica a: resource.identifier, resource.identifier_type, etc.
```

### ¿Qué pasa si no se siguen estas reglas?

Si un agente retorna campos planos (no envueltos), el merger:
1. Crea el array correcto a partir de los datos
2. PERO también deja los campos planos como atributos huérfanos de nivel superior en `attributes`
3. Resultado: la salida tiene campos duplicados o basura

Ejemplo de salida con problema:
```json
{
  "attributes": {
    "creators": [{"creator_name": "..."}],
    "creator_name": "...",        // ← huérfano, no debería estar aquí
    "creator_name_type": "...",   // ← huérfano
    "type": "Organization",       // ← huérfano
    "name_identifiers": [],       // ← huérfano
    "affiliations": []            // ← huérfano
  }
}
```

---

## Agregar Nuevos Agentes

Agrega la configuración a `config/agents_v2.json` (recomendado) o `config/agents.json`:

```json
{
  "id": "mi_agente",
  "name": "Mi Agente Personalizado",
  "description": "Extrae campos personalizados",
  "output_fields": ["campo_personalizado"],
  "prompt_template": "Extrae campo_personalizado del contexto...\n\nFORMATO:\n{\"campo_personalizado\": [{\"sub_campo1\": \"\", \"sub_campo2\": \"\"}]}\n\nSin información:\n{\"campo_personalizado\": []}\n\nDevuelve solo JSON.",
  "depends_on": ["resource"],
  "use_chain_of_thought": true,
  "llm_config": {
    "model": "glm-4.7",
    "provider": "zai-coding-plan",
    "temperature": 0.1,
    "max_tokens": null
  }
}
```

Nota: el `llm_config` es un objeto con `model`, `provider`, `temperature` y `max_tokens`. El prompt debe envolver la salida en su campo primario.

---

## Estrategias de Contexto

- **accumulative** (por defecto): Cada agente recibe todas las salidas anteriores
- **layered**: Los agentes solo reciben la salida del explorer + entrada inicial

---

## Asignación de Modelos por Nivel

Para optimizar costo y calidad, los agentes se asignan a 3 niveles de modelos:

| Nivel | Modelo | Uso | Agentes |
|-------|--------|-----|---------|
| Tier 1 | `glm-5.1` | Razonamiento complejo | resource, descriptions, titles, creators, categories, subjects, rights |
| Tier 2 | `glm-4.7` | Complejidad moderada | dates, publishers, funding_references, citations, audiences, geo_locations, temporal_events |
| Tier 3 | `glm-4.7-flash` | Extracción simple/rápida | languages, alternate_identifiers, media_files, related_identifiers |

---

## Solución de Problemas

| Problema | Solución |
|----------|----------|
| `FileNotFoundError` | Verifica que las rutas de archivo sean correctas |
| `AuthenticationError` | Verifica la API key en `.env` |
| `Invalid JSON` | Valida el formato del archivo de entrada |
| Timeout del agente | Verifica la conectividad con la API |
| Campos duplicados/huérfanos en salida | El prompt del agente no envuelve la salida en su campo primario. Ver "Reglas Críticas de Configuración" |
| Campo no aparece en salida | El agente retornó `[]` y fue limpiado, o falló por rate limit. Verificar logs |
| Rate limit en agentes flash | El sistema reintenta automáticamente. Si persiste, considerar mover el agente a `glm-4.7` |

### Mecanismo de Reintento

El orquestador reintenta automáticamente agentes que fallan por rate limiting con delays incrementales:

```
Delays: [0.5s, 1s, 2s, 3s, 5s, 7s, 10s] (hasta 8 intentos total)
```

- Solo reintenta en `RateLimitError` (otros errores se propagan inmediatamente)
- Cada intento se registra en los logs
- El uso de tokens del intento exitoso se registra correctamente

---

## Prueba Rápida

```bash
uv run python metadata_enricher.py --input examples/sample_input.json
```

---

## Licencia

MIT
