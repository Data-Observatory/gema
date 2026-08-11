# Prompt-engineering review — `config/agents.yaml` (5 production agents)

Reviewed by an independent pass (Opus) against the actual production prompts, the schema/normalizers they feed, and the 6 committed golden outputs — several findings below are not speculative, they're measured against 100% of recorded production outputs, with counts cited.

Prompt sizes: `core_metadata` 13.7k chars (~4.2k tok), `creators_publishers` 9.4k, `classification` 9.0k, `rights_funding_citations` 7.4k, `media_files` 7.0k — ~14k prompt tokens per resource total.

---

## TIER 1 — Guidance that is provably discarded, or that teaches the wrong thing

### 1. `core_metadata` — `language_description` is written to a key the schema throws away (100% data loss)
The prompt spends ~12 lines on it: *"language_description DEBE ser una oración clara y útil para el usuario final… NUNCA dejar language_description vacío"*, with 4 worked variants and a self-check bullet. But `_normalize_languages` (datacite.py:322-354) only emits `{"lang_code", "language", "description"}` and reads `item.get("description", "")`. `language_description` is never read.
**Evidence:** 0 of 6 golden records have a non-empty `languages[].description`. Every one is `""`.
**Fix:** rename the key to `description` in the prompt (template, all 4 examples, the PASO 4 body, the rules block, and the autocheck), or add `language_description` to the normalizer's fallback chain. Cheapest large win in the whole file.

### 2. `core_metadata` — `date_description` likewise discarded (100% data loss)
PASO 5 is the single largest block in the largest prompt (~40 lines): 4 date types each with a mandated `date_description`, 4 JSON examples, *"date_description NUNCA debe ser genérico… siempre contextualizar al recurso específico"*, plus a rules-block restatement and an autocheck bullet. `_normalize_dates` reads `item.get("date_information") or item.get("context") or item.get("description")` — `date_description` is not in the chain.
**Evidence:** 0 of 6 golden records have a non-empty `dates[].date_information`.
**Fix:** rename to `date_information` throughout. (Renaming in the prompt is safer than touching the normalizer, which the golden fixtures are recorded against.)

### 3. `media_files` — the casing rule is exactly backwards, killing the whole `collections` feature
Rule: *"Los nombres de los campos DEBEN ser EXACTAMENTE en minúsculas: \"collections\", NO \"Collections\""*. `_normalize_media_files` reads `item.get("Collections", [])` — capital C, and CLAUDE.md documents that capital C as **intentional and not to be "fixed"**. So the prompt instructs the model to emit precisely the key that gets dropped.
**Evidence:** 0 of 4 golden media_files have `Collections` populated; PASO 6 (`accrual_method` / `accrual_periodicity` / `accrual_policy`) has never produced output.
**Fix:** invert the rule to require `"Collections"` with capital C and say why, or delete PASO 6 + the `collections` block from the template entirely (it has never yielded a value; see also #47).

### 4. `core_metadata` — the few-shot examples teach the model to omit the schema's only required field
`_REQUIRED_FIELDS = ["titles"]` (datacite.py:143; merger.py:43-51 logs `Missing required fields`). Yet 3 of 4 examples show `"titles": []` and **4 of 4** show `"descriptions": []` — including EJEMPLO 1 whose input literally begins *"Dataset de gastos municipales"* and EJEMPLO 3 which has a full descriptive sentence. For a cheap model, few-shot output shape dominates prose rules.
**Evidence:** `sample_input05.json` ships with `"titles": []` — the required field genuinely missing in a recorded golden.
**Fix:** every example must populate `titles` and `descriptions` from its own input. Add an autocheck bullet: *"¿titles tiene al menos un objeto con name no vacío?"*

### 5. `core_metadata` — examples leave `identifier`/`identifier_type` empty in 4 of 4, and don't match the real input format
All four examples show `"identifier": ""`, even though production always supplies a URL. Worse, the examples' input is a free-text blob (`Entrada: "Dataset de gastos municipales. Publicado el…"`), whereas `base.py:84-91` appends a labelled block:
```
=== RECURSO A PROCESAR ===
- url: … / - title: … / - description: … / - doi: … / - detected_country: …
```
The model is shown one input format and given another. The identifier is arguably the most important field in the record.
**Fix:** rewrite all 4 examples using the exact appended block format, and populate `identifier` from `url` (or `doi`, with `identifier_type: "DOI"`) in every one. Add the explicit rule: *"identifier = el valor de `- url` (o `- doi` si existe) de la sección RECURSO A PROCESAR; NUNCA vacío si esa sección trae uno."*

### 6. `all` — the chain-of-thought is theater: the model has no channel to reason in
Three facts combine badly. (a) `use_chain_of_thought: true` is dead config — read only by `config/models.py:60` and `config/migrate.py:22`; `BaseAgent` and the whole `llm/` stack ignore it. (b) `DataCiteOutputModel` has no reasoning field, so Instructor forces the first generated token to be part of the answer. (c) Every prompt ends *"Devuelve ÚNICAMENTE el JSON, sin texto adicional ni explicaciones."* So *"CADENA DE PENSAMIENTO (sigue estos pasos en orden)"* and especially *"PASO 5/9 — AUTO-VERIFICACIÓN (obligatorio antes de responder) ✓ ¿No inventé ningún dato?"* are instructions the model physically cannot execute — it must emit the JSON directly. Cheap non-reasoning models get zero benefit; you pay ~14k tokens/resource for scaffolding that never runs. This is the highest-leverage structural change available.
**Fix, pick one:** (a) add a leading `reasoning: str` field to the response model (`extra="allow"` already accommodates it; drop it before merge) so the step-by-step tokens are actually generated *before* the fields — the standard Instructor CoT pattern, and the only version where "AUTO-VERIFICACIÓN" means anything; or (b) accept there is no reasoning phase, delete the CoT framing and all self-verification checklists, and rewrite the steps as flat imperative extraction rules. Do not keep the current middle ground.

### 7. `all` — the resource data lands *after* the final instruction, and nothing tells the model it's coming
`base.py:80-91` appends `=== RECURSO A PROCESAR ===` after the whole prompt, i.e. after *"Devuelve UNICAMENTE el JSON, sin texto adicional ni explicaciones."* No prompt mentions that section by name, so the model meets the closing instruction, then unannounced data. Also `base.py:64-67` computes a deterministic `detected_country` hint and injects it into that block — **no prompt references `detected_country` at all**, so a free, reliable signal is wasted (and `core_metadata` instead guesses country from prose: *"Si el recurso es de una institución chilena sin indicación contraria → asumir español"*).
**Fix:** add near the top of every prompt: *"Los datos del recurso llegan al FINAL de este mensaje, en la sección `=== RECURSO A PROCESAR ===`. Extrae información ÚNICAMENTE de ahí."* Consume `detected_country` explicitly in `core_metadata` (language default, `geo_locations`) and `classification` (the `-- País` subject suffix). Optionally move the closing instruction into the (currently unused) `system_prompt` so it stays last in effective priority.

### 8. `core_metadata` — `publication_year` is never reconciled with `dates`
No rule links them. DataCite makes `publicationYear` mandatory.
**Evidence:** 3 of 6 goldens have `publication_year: ""` while `dates` is populated — e.g. `sample_input01` has `dates: [2026-03-15 Updated]` and an empty year; `sample_input04` has `2021-01-01 Collected` and an empty year.
**Fix:** add a rule: *"publication_year = el año de la fecha `Issued`; si no hay `Issued`, el año de la fecha más antigua disponible; si no hay ninguna fecha, el año que aparezca en la URL o el título. NUNCA dejarlo vacío si existe alguna fecha en la salida."* Plus an autocheck bullet.

---

## TIER 2 — Rules that actively manufacture facts

### 9. `core_metadata` — the "4 obligatory geo fields" rule forces bounding-box invention
*"REGLA CRÍTICA: NUNCA devolver geo_location con solo geo_location_place. Siempre los 4 campos."* The agent has no gazetteer (BACKLOG's core known gap) and the prompt supplies exactly one bbox — Chile national. This rule is in direct conflict with the same prompt's *"✓ ¿No inventé ningún dato?"*.
**Evidence:** 5 of 5 golden geo_locations have a non-empty box, **none** empty; 3 are the prompt's Chile string copied verbatim (including `sample_input02`, a plant-traits platform, and `sample_input04`); the other 2 are model-generated coordinate strings (`-76.5337,-56.7392,-69.0261,-16.9754`) with no source.
**Fix:** make `geo_location_box` conditional — *"rellena geo_location_box SOLO si (a) la cobertura es Chile nacional, usando la caja canónica, (b) las coordenadas aparecen literalmente en el texto, o (c) el lugar está en la tabla de regiones de abajo. En cualquier otro caso deja geo_location_box vacío."* Then either ship a small region/comuna bbox table or accept empty boxes. Also note the canned Chile box excludes Easter Island and the Antarctic claim — say so, or label it "Chile continental" as `sample_input03` correctly did.

### 10. `classification` — subjects are asserted as LCSH with an authority URI the model cannot verify
*"Prioriza esquemas de clasificación conocidos: LCSH, UNESCO, JEL / Formato LCSH: \"Tema -- Subtema -- País\""*, and every example stamps `"subject_scheme": "LCSH", "scheme_uri": "https://id.loc.gov/authorities/subjects.html"` onto free-text Spanish phrases that are almost certainly not real Library of Congress headings.
**Evidence:** 18 of 20 golden subjects claim `LCSH`; **0 of 20** carry a `value_uri`. Real headings include `"Rasgos funcionales (Biología) -- Plantas -- Chile"` and `"Gastos municipales -- Chile"` — invented headings wearing an authority label. This is a metadata-integrity problem, not a cosmetic one: downstream consumers trust `subject_scheme`.
**Fix:** *"subject_scheme = \"\" salvo que el recurso declare explícitamente el esquema al que pertenece el término. NUNCA declares LCSH, UNESCO ni JEL sin un value_uri concreto — un término en formato LCSH no es un término LCSH."* Also resolve the contradiction with *"Usa SOLO términos que aparecen explícitamente en el texto fuente"* — the `-- País` suffix construction violates it; state explicitly that normalising/compounding source terms is allowed but introducing new concepts is not.

### 11. `media_files` — `application/zip` by default manufactures files that don't exist
*"**REGLA POR DEFECTO: Si NO se puede determinar el formato por ninguna via anterior, usar \"application/zip\"**"*, stated twice, plus a dedicated EJEMPLO 5 endorsing it.
**Evidence:** 3 of 4 golden media_files are `application/zip`. `sample_input06`'s media_file is `{"format": "application/zip", "file_uri": ""}` — a phantom file record with no URI at all, i.e. the record asserts a downloadable ZIP that has no location. That is the default rule plus "SIEMPRE incluir todos los campos" producing pure fiction.
**Fix:** gate it — *"Aplica el default `application/zip` SOLO si existe una URL de descarga real y el texto indica un paquete de datos (shapefile, capa, \"descargar\"). Si no hay URL, no crees el objeto. Si hay URL pero ninguna pista de formato, deja format vacío."* Add a hard rule: *"NUNCA crear un objeto en media_files con file_uri vacío."*

### 12. `media_files` / `rights_funding_citations` — plausible-looking fake values in the prompt get copied
`rights_funding_citations`: *"Busca numeros de proyectos o award numbers (formato tipico: 1234567, 11191101, 3220245, etc.)"*, and EJEMPLO 1 uses `"award_number": "1234567"`. Cheap models regurgitate concrete in-prompt identifiers when the source has none — the same class of bug as the geo bbox in #9. `11191101` and `3220245` are real-looking FONDECYT numbers.
**Fix:** describe the shape, not instances: *"los award numbers de ANID son cadenas de 7-8 dígitos"*. In examples, use unmistakable placeholders (`NNNNNNN`) or clearly-fake values, and add: *"NUNCA copies un número de ejemplo de estas instrucciones."*

### 13. `creators_publishers` — a factual error repeated 3× that breaks ROR resolution
The prompt says `"Ministerio de Economía, Desarrollo y Turismo"` three times (SERNATUR's affiliation, INE's affiliation, and the NIVEL 2 list). The correct official name is **"Ministerio de Economía, Fomento y Turismo"**. With `enable_identifier_enrichment: true`, this name is fed to the ROR resolver, which fuzzy-matches at `threshold=90.0` WRatio (`enrichers/fuzzy_matcher.py:73`) — a wrong content word in a 5-word name risks `nomatch` or a wrong match, and the wrong name ships in the record either way.
**Fix:** correct all three. Also audit the rest of the table against current official names (SENAME's child-protection functions moved to *Servicio Nacional de Protección Especializada a la Niñez* in 2021 — decide whether historical resources should keep SENAME).

### 14. `rights_funding_citations` — PRIORIDAD 3 still force-assigns CC-BY-4.0, the same class as the bug just fixed
The golden rule now correctly says *"NUNCA asumir una licencia por el tipo de institucion"*, but PRIORIDAD 3 fires on *"el texto o URL mencionan explicitamente \"datos abiertos\", \"datos.gob.cl\""* and then hardcodes `rights_identifier: "CC-BY-4.0"`, `rights_identifier_scheme: "SPDX"`, `rights_uri: creativecommons.org/licenses/by/4.0/`. Being *hosted on* datos.gob.cl is an institution/platform inference, not a license statement, and datos.gob.cl datasets carry per-dataset terms.
**Evidence:** `sample_input01` golden ships `rights: [{"rights": "Datos Abiertos del Estado de Chile", "rights_identifier": "CC-BY-4.0", "rights_identifier_scheme": "SPDX", …}]` — a specific SPDX license asserted from a URL pattern.
**Fix:** keep the human-readable label `"Datos Abiertos del Estado de Chile"` and `rights_holder: "Estado de Chile"`, but **drop `rights_identifier` / `rights_identifier_scheme`** unless the page names a specific license. Also the parenthetical *"(NUNCA usar datos.gob.cl porque esa URL no funciona)"* leaks an implementation note — restate positively as *"rights_uri debe apuntar a la página de términos de uso citada; si no hay ninguna, déjalo vacío."*

### 15. `all` — no rule separating resource-level from site-level information in `fetched_content`
`fetched_content` is raw page text (BACKLOG confirms up to ~6000-8000 chars). Nothing warns about nav bars, footers, cookie notices, or portal-wide boilerplate. `core_metadata`'s *"Busca ACTIVAMENTE en TODO el texto: Correos electrónicos: cualquier dirección con @"* will happily harvest `webmaster@`/`contacto@portal` footer addresses; a footer CC badge will become the dataset's license; a portal-wide "Actualizado" date will become the resource's `Updated`.
**Fix:** add a shared block: *"El contenido puede incluir texto del sitio completo (menús, pie de página, avisos de cookies, buscador). Extrae SOLO información sobre este recurso específico. Ignora emails/teléfonos/licencias/fechas genéricos del portal (webmaster@, contacto@, mesa de ayuda) salvo que el texto los asocie explícitamente a este recurso."*

### 16. `all` — no negative/contrastive examples anywhere
All 25-ish few-shot examples across the 5 prompts are positive. For models at this tier, ❌/✅ contrast pairs are among the highest-yield techniques available, and your failure modes are known and repetitive.
**Fix:** add 1-2 contrast pairs per agent targeting the exact observed failures: placeholder-echo objects, the copied Chile bbox on a non-national resource, the LCSH label on a free-text keyword, the phantom `application/zip` with empty `file_uri`, the CC-BY-by-institution license. Format: `❌ MAL (y por qué): {...}` / `✅ BIEN: {...}`.

### 17. `core_metadata` — `"Si solo tienes año → usar \"AAAA-01-01\""` fabricates day-level precision
This directly contradicts *"NUNCA inventar fechas"* two lines later, and destroys the distinction between "published 1 January" and "published sometime in 2021". DataCite accepts year-only values and ISO 8601 intervals.
**Evidence:** goldens 04 and 06 carry `2021-01-01` / `2020-01-01`, neither of which is a real day.
**Fix:** *"Si solo conoces el año, usa \"AAAA\". Si conoces año y mes, \"AAAA-MM\". Usa AAAA-MM-DD solo cuando el día aparezca en la fuente."* This also fixes the related loss in PASO 5: *"Si el período es un rango (ej: \"2019-2021\"), usar el año de inicio"* throws away the end year — use the ISO interval `2019/2021`, which DataCite supports, instead of stuffing the range into prose.

### 18. `core_metadata` — `temporal_events` has no evidence requirement, and the normalizer silently drops half-filled ones
PASO 8b is two lines (`frequency_type`, `description`) with no "only if stated" guard and no example.
**Evidence:** 3 of 6 goldens contain invented update cadences — `"frequency_type": "yearly", "description": "La plataforma se actualiza anualmente con nueva información…"` (sample 02), `"monthly"` (sample 01), `"yearly"` (sample 04) — none of which is evidenced. Separately, `_normalize_temporal_events` only accepts a dict `if "start_date" in item or "description" in item`, so `{"frequency_type": "monthly"}` alone is silently discarded, and `frequency_number` exists in the schema but is never mentioned in the prompt.
**Fix:** add *"Crea temporal_events SOLO si el texto declara explícitamente una frecuencia de actualización (\"se actualiza mensualmente\", \"datos anuales\"). No infieras la frecuencia del tipo de recurso. Incluye SIEMPRE `description` (obligatorio) y `start_date`/`frequency_number` si están disponibles."* Note `"quarterly"` is offered in the prompt's allowed list but absent from `_FREQ_MAP`.

### 19. `classification` — `audiences` is forced fabrication, and the examples collapse it to two canned rows
*"PASO 4 — DETERMINA AUDIENCIAS (mínimo 2, máximo 6)"* / *"audiences: mínimo 2 elementos cuando hay contexto suficiente"*, sitting three lines below *"NUNCA inventar subjects"*. There is no source evidence for `mediator` / `education_level` / `instructional_method` — ever. And all 4 examples reuse the identical pair `Investigadores/Autodirigido/Postgrado/Análisis` and `Tomadores de decisiones/Analista/Profesional/Consultoría`.
**Evidence:** those two exact rows appear in essentially every golden record. The field carries near-zero information per resource.
**Fix, pick one:** (a) accept it's deterministic and **move it out of the LLM entirely** — derive audiences in code from the chosen category, saving tokens and guaranteeing consistency; or (b) keep it in the prompt but give an explicit mapping table (category → plausible audience set), diversify example rows so no combination repeats, and require that at least one audience be justified by something in the text.

### 20. `core_metadata` — the `resource_type` instruction is guaranteed to be overwritten
*"¿Qué tipo de recurso es? → resource_type (ej: \"Census Data\", \"Financial Data\")"*. `_normalize_resource` (datacite.py:672-674) checks `resource_type.lower()` against `VALID_RESOURCE_TYPES` (dataset, software, text, image, video, audio, collection, event, interactive resource, model, physical object, service, sound, workflow, other) and replaces anything else with `"Dataset"`. Both suggested values are guaranteed rejects. The prompt's own output template then says `"resource_type": "Dataset"` — self-contradiction.
**Fix:** replace the free-text invitation with the closed list verbatim and drop the misleading examples. Same treatment for `resource_type_general` (*"normalmente \"Dataset\""* with no vocabulary — `sample_input05` shipped `""`); state DataCite's `resourceTypeGeneral` closed list and mark it mandatory.

---

## TIER 3 — Contradictions, corruption, and under-specified fields

### 21. `creators_publishers` — literal text corruption right before the output format
Rendered exactly as:
```
- Si no hay creadores → {"creators": [], "publishers": []=== FORMATO EXACTO DE SALIDA ===
```
The closing `}` and the `\n\n` section break are both missing (agents.yaml:269), so the last strict rule fuses into the section header and demonstrates malformed JSON immediately before the model is shown the required output shape. Also in the same prompt: an empty checklist bullet `  ✓ ` (line 256, leftover from removing the identifier check).
**Fix:** repair both. See #48 for why they went unnoticed.

### 22. `creators_publishers` — PASO 3 contradicts all 5 of its own examples on identifiers
PASO 3: *"Deja name_identifiers como lista vacía ([]) para instituciones"*, *"Deja publisher_identifier como string vacío"*. Yet every example emits a stub such as `"name_identifiers": [{"name_identifier": "", "name_identifier_scheme": "ROR", "scheme_uri": ""}]`, and the scheme varies arbitrarily across examples (`ROR`, `ISNI`, `""`, `""`, `""`) with no stated reason. An empty-valued slot labelled with a scheme is an open invitation for a cheap model to fill it with a hallucinated ROR ID — and `enrichers/identifier_enricher.py:86-104` replaces the whole list anyway when no real ID is present, so the stub is pure downside.
**Fix:** set `"name_identifiers": []` and `"publisher_identifier": ""` / `"publisher_identifier_scheme": ""` in all five examples, matching PASO 3.

### 23. `rights_funding_citations` — two adjacent, directly contradictory funder-identifier rules
```
- NO incluyas identificadores ROR para financiadores. Deja funder_identifier vacío.
  Los identificadores se resolverán automáticamente.
- Para otros financiadores, buscar su ROR si es conocido
```
The second line is a leftover from before enrichment moved into code.
**Fix:** delete the second line. Also drop EJEMPLO 1's typed-but-empty `funder_identifiers: [{"funder_identifier": "", "funder_identifier_type": "ROR", …}]` stub, for the same reason as #22.

### 24. `rights_funding_citations` — `citations` is semantically undefined, and the prompt contradicts its own examples
The agent description says *"informacion para citar el recurso"*, and the rule says *"Titulo del recurso (obligatorio para cita)"* — but EJEMPLO 1 and EJEMPLO 2 both return `"citations": []` while their inputs clearly contain resource titles. So the model has no trigger condition.
**Evidence:** the goldens are incoherent as a result — `sample_input03` and `sample_input06` put an *external paper's* title in `citations` (`"Climatic regionalization of continental Chile", volume 13`), while `sample_input05` puts the resource's own title with every other field empty. Also the schema has no container-title, author, or year field, so a citation object holding only a title is unusable.
**Fix:** state one definition and a hard trigger, e.g. *"Crea un objeto en citations SOLO si el recurso está publicado dentro de una publicación anfitriona (revista, congreso, libro) y el texto entrega al menos uno de: volumen, número, páginas, edición, o lugar/fecha de conferencia. El campo `title` es el título de esa publicación anfitriona / del artículo asociado, NO el título del dataset. Si solo tienes el título del recurso → citations: []."* Add a ❌/✅ pair.

### 25. `core_metadata` — the EDITOR vs MANTENEDOR distinction yields zero signal
~15 lines distinguish `editor` from `maintainer`, including *"REGLA: maintainer NO es lo mismo que producer. Maintainer = quien lo publica/mantiene online"* — which is itself circular (that's the definition given for `editor`).
**Evidence:** `editor == maintainer` in **6 of 6** goldens; in samples 01 and 04, `editor == maintainer == producer` (all `"Ministerio de Hacienda - Gobierno de Chile"` / `"Instituto Nacional de Estadísticas (INE)"`). `maintainer` is never independently populated in any recorded output.
**Fix:** either give a single crisp disambiguation plus one example where the three genuinely differ (e.g. a Universidad de Chile dataset hosted on geoportal.cl: producer = department, editor/publisher = portal, maintainer = portal operator), or delete `maintainer` from the prompt and let the normalizer default it.

### 26. `core_metadata` vs `creators_publishers` — two agents answer the same question differently, with no shared vocabulary
`depends_on: []` for both (correctly, per BACKLOG), so neither sees the other. `core_metadata` defines *"EDITOR (quien publica/conserva el recurso - para citas)"*; `creators_publishers` independently produces `publishers`. Nothing reconciles them, and nothing standardises name formatting.
**Evidence:** sample 01 — `resource.editor: "Ministerio de Hacienda - Gobierno de Chile"` vs `publishers[0]: "Ministerio de Hacienda"`. Sample 03 — `resource.editor: "Geoportal de Chile"` vs `publishers[0]: "Departamento de Geografía, Universidad de Chile"`. The same document asserts two different publishers.
**Fix:** put shared definitions of editor/publisher/producer/maintainer into the (currently unused) `system_prompt` so both agents read identical text, and add a naming rule to both: *"usa el nombre oficial de la institución tal cual, sin sufijos añadidos como \" - Gobierno de Chile\" ni acrónimos entre paréntesis"* — the appended suffix is also what degrades ROR matching (#13).

### 27. `all` — the `""`-placeholder output templates get echoed, and the normalizers don't filter all of them
Every prompt's `=== FORMATO EXACTO DE SALIDA ===` shows a one-element array of an all-empty object (`"dates": [{"date":"", "date_type":"", "date_description":""}]`, `"geo_locations": [{4 empty fields}]`, `"sizes": [{"size": 0, "unit": ""}]`), combined with *"SIEMPRE incluir todos los campos"* / *"Cada campo debe estar presente aunque sea array vacio"*. `_normalize_dates` does drop empty-date entries, but `_normalize_geo_locations` accepts an all-empty object (its guard is `if "geo_location_place" in item` — key presence, not value) and `_normalize_media_files` appends **any** dict unconditionally.
**Evidence:** `sample_input06`'s media_file with `file_uri: ""` (see #11).
**Fix:** replace `""` placeholders with angle-bracket descriptors (`"date": "<AAAA-MM-DD>"`, `"geo_location_box": "<oeste,sur,este,norte o vacío>"`) so a literal echo is visually wrong, and add a cross-cutting rule: *"Si no hay datos para una lista, devuelve `[]`. NUNCA devuelvas un objeto con todos sus campos vacíos."*

### 28. `core_metadata` — PASO 6 and PASO 7 are one-liners for two structured fields
```
PASO 6 — IDENTIFICADORES ALTERNATIVOS
  - Códigos internos, IDs locales, abreviaciones
PASO 7 — IDENTIFICADORES RELACIONADOS
  - APIs, documentación, datasets relacionados
```
No object shape, no vocabulary, no example, and all 4 examples show `[]` for both. Meanwhile the normalizers expect `alternate_name`/`alternate_identifier`/`alternate_identifier_type` and `related_identifier`/`related_identifier_type`/`relation_type`.
**Evidence:** sample 03 emitted `{"alternate_name": "", "alternate_identifier": "{FC85D54E-34B7-416D-ABC3-E0E3FAC45A31}", "alternate_identifier_type": "Local"}` — a raw internal GUID as a public identifier with no label; sample 04 put the abbreviation `"EPF"` in `alternate_identifier` with an empty `alternate_name` (it belongs in `alternate_name`, or as an `AlternativeTitle`). Sample 03's relation types (`IsReferencedBy`, `HasPart`, `IsDescribedBy`) were produced with no vocabulary supplied — they happen to be valid, which is luck.
**Fix:** give both fields the full object shape, DataCite's closed `relationType` and `relatedIdentifierType` vocabularies (or the ~6 you actually want), one worked example each, and a rule against emitting opaque platform GUIDs — plus *"la abreviatura de un recurso va en alternate_name, no en alternate_identifier."*

### 29. `core_metadata` — the `date_type` list isn't declared closed
PASO 5 lists Issued / Created / Updated / Collected without saying these are the only permitted values; DataCite 4.6 defines ten (Accepted, Available, Copyrighted, Collected, Created, Issued, Submitted, Updated, Valid, Withdrawn). A cheap model will invent `"Published"` or `"Modified"`.
**Fix:** *"date_type debe ser EXACTAMENTE uno de: … (lista cerrada). Si ninguno encaja, no incluyas la fecha."* Consider adding `Available` — it's the right type for portal-publication dates and is currently unavailable to the model.

### 30. `creators_publishers` — no Personal-creator example exists, yet most real creators are people
All 6 examples are organizational. The Personal branch is specified only in prose: *"Persona → name_type = \"Personal\", extraer given_name y family_name por separado"* and *"Formato de nombre personal: \"Apellido, Nombre\" en creator_name"*.
**Evidence:** 5 of 9 golden creators are `Personal` — the majority path has zero few-shot coverage.
**Fix:** add two examples: a single named author with an affiliation, and multiple authors sharing one affiliation (matching sample 03's real shape). Cover initials (`"Sarricolea, P."`), compound Spanish surnames (`"Meseguer-Ruiz, O."` — two-part family name), and particles (`de la`, `van`).

### 31. `creators_publishers` — the `type` field is unmentioned, so every person is labelled an Organization
`_normalize_creators` sets `"type": item.get("type", "Organization")`. The prompt's output template has no `type` field, so the default always wins.
**Evidence:** all 5 Personal golden creators carry `"creator_name_type": "Personal"` alongside `"type": "Organization"` — internally contradictory records.
**Fix:** either add `"type"` to the prompt template (`"Person"` / `"Organization"`, consistent with `name_type`), or better, derive it in the normalizer from `creator_name_type` so it can't diverge. Same for `genre`, `email`, and `contributor_type`, which the normalizer emits but no prompt ever mentions (always `""`).

### 32. `creators_publishers` — the NIVEL 1 list contains entries that violate NIVEL 1's own rule
NIVEL 1 states *"Su afiliación es el MINISTERIO del que dependen (NO el Gobierno de Chile directamente)"*, then lists `SHOA → "Armada de Chile"` and `BCN → "Congreso Nacional de Chile"` — neither is a ministry, and the Biblioteca del Congreso is in a different branch of government entirely (so "Gobierno de Chile" would be wrong for it at NIVEL 2). Unflagged exceptions teach a cheap model that the rule is soft.
**Fix:** either complete the chains (`SHOA → Armada de Chile → Ministerio de Defensa Nacional`) or move both under an explicit *"EXCEPCIONES (no siguen la cadena ministerial)"* heading.

### 33. `creators_publishers` — dead reference to a removed lookup table
`DIFROL → affiliation = "Ministerio de Relaciones Exteriores" (sin ROR en tabla)`. The identifier table was removed (PASO 3 now says identifiers resolve downstream), so "sin ROR en tabla" refers to nothing and hints at a table the model will assume exists.
**Fix:** delete the parenthetical.

### 34. `creators_publishers` — the examples teach unconditional creator→publisher duplication
Examples 1-5 all copy the same organisation into both `creators` and `publishers`, including EJEMPLO 1 whose input is only *"Informe del Ministerio de Educación sobre matrícula escolar."* with no publishing statement. PASO 2b only says *"Puede ser ambos"*.
**Fix:** if unconditional duplication is the intent, say so as a rule (*"para instituciones públicas chilenas, si no se identifica un publicador distinto, el creador también es el publicador"*). If not, add a counterexample where creator ≠ publisher (sample 03's real shape: authors as creators, the portal/department as publisher).

### 35. `creators_publishers` — the table enumerates ~19 instances but misses the highest-frequency patterns
Two long enumerations (NIVEL 1's 11 agencies, NIVEL 2's 7 ministries) cost tokens while the general rule *"Ministerios → Gobierno de Chile"* already generalises. Meanwhile the patterns that dominate Chilean public data have no rule at all: `Municipalidad de X`, `Gobierno Regional de X`, `SEREMI de X Región de Y`, `Servicio de Salud X`, `Delegación Presidencial`, and university sub-units.
**Evidence:** sample 03 chose `"Departamento de Geografía, Universidad de Chile"` as the *publisher* — is a department a publisher? The prompt only says *"Universidad → affiliations = [] (entidad independiente)"*, silent on departments.
**Fix:** replace most of the enumeration with pattern rules — *"`Municipalidad de X` → affiliation = \"\" (autónoma)"*, *"`SEREMI de <área>` → affiliation = el ministerio del área"*, *"`Departamento/Facultad/Centro de <Universidad>` → creator = la unidad; affiliation = la universidad"* — and keep the explicit list only for genuinely non-derivable acronyms (ODEPA, CONAF, DIFROL, SHOA, BCN).

### 36. `rights_funding_citations` — accent-stripped Spanish, including inside example *outputs*
This prompt is the only one written without accents (*"informacion"*, *"licencia explicita"*, *"titulo"*, *"Tecnologia"*, *"cientificos"*), and critically the accentless spelling appears in example output values: `"rights_holder": "Ministerio de Ciencia, Tecnologia, Conocimiento e Innovacion"`. The model will imitate that in real records, producing misspelled Spanish institution names in shipped metadata and weakening ROR fuzzy matching (`fuzzy_matcher.normalize_org_name` lowercases and strips punctuation but does **not** fold accents).
**Fix:** restore accents throughout, and add a cross-cutting rule: *"Copia los nombres de instituciones con su ortografía y acentuación oficial completa, exactamente como aparecen en la fuente."*

### 37. `rights_funding_citations` — license version is hardcoded to 4.0
`CC BY → rights_identifier: "CC-BY-4.0"`, with no branch for a stated 3.0 / 2.0 / 2.5-CL.
**Fix:** *"Extrae la versión del texto (CC BY 3.0 → CC-BY-3.0). Usa 4.0 solo si el texto menciona Creative Commons sin versión."* Also add `CC-BY-NC-SA` and `CC-BY-ND` to the mapping (currently absent, so they'll be forced into the nearest listed option).

### 38. `rights_funding_citations` — the CC trigger word `"atribucion"` is too loose
*"usar SOLO si el texto menciona CC, Creative Commons, o \"atribucion\""*. Spanish public-data pages routinely say *"se requiere atribución de la fuente"* without any Creative Commons license — a false positive that reintroduces exactly the forced-license failure just fixed.
**Fix:** require *"CC"*, *"Creative Commons"*, or a `creativecommons.org` URL. Treat a bare *"atribución"* as a `rights_condition`, not a license.

### 39. `rights_funding_citations` — `rights_holder` conflates contributors with copyright owners
*"rights_holder: TODAS las instituciones contribuyentes separadas por punto y coma"*. Contributing to a dataset does not make you its rights holder; this asserts legal ownership without evidence, in a prompt whose golden rule forbids exactly that for licenses.
**Fix:** *"rights_holder = la entidad que el texto identifica como titular de los derechos o del copyright. Si no se identifica ninguna, usa el publicador. Si tampoco hay publicador, déjalo vacío."*

### 40. `rights_funding_citations` — `start_date` and `rights_condition` appear only in the template
Neither is mentioned in any reasoning step, rule, or example, so both are permanently `""` (confirmed across all goldens).
**Fix:** either explain them (`start_date` = when the license took effect if stated; `rights_condition` = non-license usage restrictions such as *"requiere registro"*, *"uso no comercial"* — genuinely useful for Chilean portals) or remove them from the template.

### 41. `rights_funding_citations` — the funder acronym→official-name split is only implicit
The CoT step just lists acronyms (*"ANID, FONDECYT, CONICYT, FONDEQUIP, FONDEF, REGIONAL, PAI, FIC, FOVI, CORFO, INNOVA"*) without saying what to do with them. EJEMPLO 1 silently demonstrates the right decomposition (`funder_name: "Agencia Nacional de Investigacion y Desarrollo"`, `funding_stream: "FONDECYT"`) — one example carrying a rule that's never stated.
**Fix:** state it: *"funder_name = el nombre oficial completo de la agencia financiadora (expande el acrónimo); funding_stream = el instrumento o programa (FONDECYT, FONDEF, FIC…). NUNCA pongas el instrumento en funder_name."* Specify CONICYT handling (predecessor of ANID — map or preserve?), and note FONDECYT/FONDEF/PAI all belong to ANID while CORFO and FIC do not.
**Evidence:** 0 of 6 goldens have any `funding_references` — worth verifying against inputs whether that's correct or a silent miss.

### 42. `classification` — nothing validates that the sub-category belongs to the chosen category
The autocheck asks *"¿La categoría está en la lista validada?"* but never *"¿la subcategoría pertenece a esa categoría?"* — and there is no instruction to reproduce the strings byte-exactly, even though these are facet values where `"Ciencias de la Tierra"` vs `"ciencias de la tierra"` matters.
**Fix:** add the autocheck bullet, and *"Copia `name` y `sub_category` EXACTAMENTE como aparecen en la lista, con la misma acentuación y mayúsculas."*

### 43. `classification` — the "suficiente contexto" threshold is undefined
*"audiences: mínimo 2 elementos cuando hay contexto suficiente"*, with EJEMPLO 4 (*"Base de datos sobre actividad económica"* — 5 words) producing a full category plus 2 audiences, and EJEMPLO 5 (*"Recurso sin descripción temática"*) producing all-empty. The boundary between them is invisible.
**Fix:** define it operationally: *"Si puedes nombrar el tema del recurso en una frase, hay contexto suficiente → clasifica y entrega audiencias. Si el texto no dice de qué trata el recurso, devuelve todo vacío."*

### 44. `classification` — `value_uri` and `classification_code` are template-only
Never explained, never populated in any example, 0 of 20 populated in the goldens.
**Fix:** explain them (they're the natural home for a real authority URI, which would also make #10's LCSH claim verifiable) or drop them from the template. Same for the *"UNESCO, JEL"* schemes — mentioned but never demonstrated, so effectively dead guidance.

### 45. `media_files` — the `sizes` template contradicts the `sizes` rule
Template: `"sizes": [{"size": 0, "unit": ""}]` plus *"SIEMPRE incluir todos los campos"*. Rule: *"Si NO se menciona el peso → sizes = []"*.
**Evidence:** 0 of 4 golden media_files have a non-empty `sizes` — so the rule wins here, but the contradiction is live. Also `"size": numero` as a float (`2.5`) is unusual for DataCite `size`, which is conventionally a string like `"2.5 MB"`; nothing normalizes it.
**Fix:** remove the placeholder element from the template (`"sizes": []`), and decide/state the numeric-vs-string convention.

### 46. `media_files` — invariants that belong in code, not in the prompt
*"physical_carrier SIEMPRE debe ser \"digital\""* is a constant the model can get wrong for free; the same is true of the `Collections` capitalization (#3) and `rights_identifier_scheme: "SPDX"` in the rights agent (the normalizer already defaults it: `item.get("rights_identifier_scheme", "SPDX")`).
**Fix:** move constants to normalizer defaults and delete them from the prompts. Every token spent stating an invariant is a token not spent on judgment the model actually has to make.

### 47. `media_files` — the output template demonstrates invalid JSON
```
"collections": [
  { "accrual_method": "", "accrual_periodicity": "", "accrual_policy": "", }
]
```
Trailing comma after `"accrual_policy": ""` (agents.yaml:632-633). The `creators_publishers` autocheck elsewhere asks *"¿El JSON es válido sin comas finales?"* while this prompt shows one.
**Fix:** remove it — or remove the block entirely per #3.

### 48. `all` — YAML double-quoted scalars are why these defects went unnoticed
All 5 prompts are stored as escaped double-quoted YAML strings with `\n` escapes and line-continuation backslashes. Consequences: the corruption in #21 is invisible on review; the empty `✓` bullet in #21 is invisible; and continuation artifacts inject hard newlines mid-sentence in the delivered prompt, e.g. PASO 3 actually renders as `"...en los campos name_identifiers,\n      affiliation_identifier o publisher_identifier."` — a line break plus six spaces inside one sentence, in several places.
**Fix:** convert all five to YAML block scalars (`prompt: |`). What's in the file then *is* what's sent, diffs become reviewable, and this class of silent corruption disappears. Highest maintainability-per-effort change in the file.

### 49. `all` — no shared `system_prompt`, so ~14k tokens/resource of boilerplate drift independently
`AgentConfig.system_prompt` exists (`config/models.py:54`) and is fully wired — `registry.py:94` → `BaseAgent.__init__` → `instructor_client.py:123-124` prepends it as a real system message — but it is `None` for all 5 agents (already in BACKLOG). Duplicated across prompts today: the null/empty-value rule (3 of 5 have it, `core_metadata` and `rights_funding_citations` don't), the "return only JSON" closer (5 variants, some accented, some not), the CoT framing, "NUNCA inventar", and the Data Observatory framing.
**Fix:** hoist into a shared `system_prompt`: the org framing, the null/empty convention, the no-invention rule, the institution-name-fidelity rule (#36), the site-vs-resource rule (#15), the shared publisher/producer/editor definitions (#26), and the `=== RECURSO A PROCESAR ===` forward reference (#7). This is also the fix that makes the remaining recommendations stay fixed.

### 50. `all` — temperature is inconsistent across identical task types
`core_metadata` 0.2, `media_files` 0.2, the other three 0.0 — on pure extraction tasks, with `seed: 42`, a diskcache layer, and a golden-fixture regression suite gated at semantic-diff ≥ 0.85.
**Fix:** set 0.0 everywhere unless there's a recorded reason for 0.2. Nondeterminism on `core_metadata` specifically undermines the regression tier, since it owns the required field.

### 51. `all` — instructions the model cannot act on
*"Mantener el orden: rights → funding_references → citations"* (`rights_funding_citations`) — Instructor/Pydantic controls serialization order; the model cannot affect it. *"Devolver SOLO JSON valido"* / *"Devuelve UNICAMENTE el JSON, sin texto adicional ni explicaciones"* — near-no-ops under structured output (cheap insurance, fine to keep, but note the last one must be **deleted** if you adopt the reasoning field in #6, or it will fight the new field).
**Fix:** drop the ordering instruction. Audit each prompt for other instructions with no mechanism behind them — they train the model that instructions are advisory.

### 52. `core_metadata` — the prompt is overloaded and its weakest fields sit last
9 reasoning steps and 9 output fields in 4.2k tokens — twice the size of any other prompt. The fields with the worst measured quality (`geo_locations`, `temporal_events`, `alternate_identifiers`, `related_identifiers` — see #9, #18, #28) are all in PASO 7-8, at the far end of a long prompt where a cheap model's instruction-following is weakest.
**Fix:** consider splitting into `core_metadata` (resource / titles / descriptions / languages / dates) and a second agent for geo / temporal / alternate+related identifiers. Adding an agent is config-only. Since `max_workers: 1`, this costs wall-clock — weigh against the quality gain, or at minimum reorder so the highest-value fields (identifier, titles, descriptions) come last, closest to the appended data.

### 53. `core_metadata` — `"MainTitle"` is not a DataCite 4.6 `titleType`
DataCite's vocabulary is AlternativeTitle / Subtitle / TranslatedTitle / Other; the main title carries **no** `titleType`. `_normalize_titles` also uses `"MainTitle"` for index 0, so the pipeline is internally consistent — low urgency — but flag it for whenever real DataCite XML/JSON export happens. Relatedly, `descriptions` only ever solicits `Abstract`; `Methods`, `TechnicalInfo`, and `SeriesInformation` are valid and often extractable from Chilean dataset pages (methodology sections), and are currently never requested.

### 54. `core_metadata` — `thumbnail` invites a guessed image URL
*"¿Hay thumbnail? → thumbnail (URL de imagen)"*, with no evidence requirement. Sample 02 got a real `og:image`, so this works today, but the rule doesn't constrain it.
**Fix:** *"thumbnail solo si una URL de imagen aparece literalmente en el contenido (og:image, miniatura del catálogo). NUNCA construyas ni adivines una URL."*

### 55. `creators_publishers` — the publisher template's `scheme_uri` doesn't match the normalizer's fallback key
The prompt asks for `"scheme_uri"` on publisher objects; `_normalize_publishers`'s `"name"`-branch emits `"publisher_scheme_uri"` instead. Today the model emits `publisher_name`, which takes the pass-through branch, so `scheme_uri` survives — and then the enricher adds `publisher_scheme_uri` too.
**Evidence:** sample 01's publisher carries **both** `"scheme_uri": ""` and `"publisher_scheme_uri": "https://isni.org"` — a redundant, half-empty key pair in shipped output.
**Fix:** pick one key name and align prompt, normalizer, and enricher.

### 56. `all` — no policy on output language for a non-Spanish resource
Every prompt hardcodes Spanish defaults (`language: "es" por defecto` appears repeatedly, `"language": "es"` in most templates), but nothing states what language the *generated* prose fields should be in when the resource is English.
**Evidence:** `sample_input06` (GFZ, English) correctly got `lang_code: "en"` and an English description, while its `categories` and `audiences` stayed Spanish (as the closed vocabularies require) — the right outcome, arrived at by accident.
**Fix:** state it once in the shared `system_prompt`: *"Los valores de vocabularios controlados (categorías, audiencias, tipos) van SIEMPRE en español. Los campos de texto libre copiados o resumidos del recurso (títulos, descripciones, geo_description) van en el idioma del recurso."* Also reframe the language default as evidence-first: *"Detecta el idioma del contenido; usa \"es\" solo si no hay evidencia del idioma"* — currently *"es por defecto"* is asserted before any detection step.

---

## Suggested execution order

If you want a short path to most of the value: **#1, #2, #3** are one-line key renames that unlock three fields currently at 100% data loss. **#4, #5** are example rewrites in one prompt that fix the required field and the identifier. **#9, #10, #11, #14** remove the four rules that demonstrably manufacture facts. **#21** is a typo repair. **#48 + #49** (block scalars + shared `system_prompt`) are the structural changes that keep everything else from regressing. **#6** is the biggest single quality lever but also the only one requiring a code change and a golden re-record.

Everything in Tier 1 and Tier 2 will change output shape — plan on `make record-golden` and a `make live-eval` pass afterwards, and note that the golden fixtures currently encode several of these defects as "expected", so the diff will be large and mostly desirable.
