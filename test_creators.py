import json
import sys
sys.path.append('.')

from agents.registry import AgentRegistry

# Cargar el registro de agentes
registry = AgentRegistry('config/agente3.json', api_key='tu_api_key_aqui')  # PON TU API KEY

# Cargar los agentes
print("Cargando agentes...")
agents = registry.load_agents()
print(f"Agentes cargados: {list(agents.keys())}")

# Obtener el agente creators
creators_agent = registry.get_agent('creators')

# Datos de prueba - construir el context como espera el agente
test_data = {
    "resource": {
        "identifier": "https://datos.gob.cl/dataset/gastos-municipales",
        "identifier_type": "URL",
        "editor": "Municipios - Ministerio de Hacienda",
        "maintainer": "Municipios - Ministerio de Hacienda",
        "producer": "Municipios - Ministerio de Hacienda"
    },
    "descriptions": [
        {
            "description": "Dataset de gastos municipales",
            "description_type": "Abstract",
            "language": "es"
        }
    ]
}

# Ejecutar agente creators usando forward()
print("\nEjecutando agente creators...")
creators_result = creators_agent.forward(context=test_data)

# Mostrar resultado
print("\n" + "="*60)
print("DEBUG - creators raw output:")
print("="*60)
print(json.dumps(creators_result, indent=2, ensure_ascii=False))
print("="*60)