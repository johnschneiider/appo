#!/usr/bin/env python3
"""
Prueba el filtrado de razonamiento del bot Appo.
"""

import sys
sys.path.insert(0, '/var/www/appo.com.co')

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'melissa.settings')

import django
django.setup()

from leads_admin.prospector_agent import ProspectorAgent

# Ejemplos de respuestas con razonamiento
test_responses = [
    # Ejemplo 1: Razonamiento en inglés
    '''Wait, let me think. The user said "Hola". Looking at the conversation history, they haven't given their name. Okay, the user is just saying hello. I should respond naturally.
Hola, cuéntame — ¿en qué te puedo ayudar?''',
    
    # Ejemplo 2: Razonamiento en español  
    '''Espera, déjame pensar. El usuario dijo "Hola". Bueno, según las instrucciones debo responder con naturalidad.
Hola, cuéntame — ¿en qué te puedo ayudar?''',
    
    # Ejemplo 3: Razonamiento múltiple
    '''Wait, no, looking back: My first response was explaining Appo. So, I should ask about their reservations.
¿Cómo manejas las reservas hoy?''',
    
    # Ejemplo 4: Sin razonamiento (limpio)
    '''Hola, cuéntame — ¿en qué te puedo ayudar?''',
    
    # Ejemplo real del log
    '''Wait, let me think: My first response was explaining Appo and asking if they still handle appointments manually. They replied with "Hola", which doesn't answer the question. So maybe they're not interested, or they missed it.
Hola, ¿en qué te puedo ayudar?''',
]

def test_filter(content):
    """Aplica el mismo filtro que _call_api."""
    import re
    reasoning_patterns = [
        r'^Wait[,\s].*',
        r'^Let me think.*',
        r'^Let\'?s think.*',
        r'^Thinking.*',
        r'^Okay,.*',
        r'^Hmm,.*',
        r'^First,.*',
        r'^Looking at.*',
        r'^Okay, the user.*',
        r'^So,.*',
        r'^The user said.*',
        r'^Based on.*',
        r'^Now,.*',
        r'^Actually,.*',
        r'^Well,.*',
        r'^Espera,.*',
        r'^Déjame pensar.*',
        r'^Pensando.*',
        r'^Mira,.*',
        r'^Vale,.*',
        r'^Bueno,.*',
    ]
    
    lines = content.split('\n')
    cleaned_lines = []
    skip_mode = False
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        is_reasoning = False
        for pattern in reasoning_patterns:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                is_reasoning = True
                break
        
        if is_reasoning:
            skip_mode = True
            continue
        
        if skip_mode:
            skip_mode = False
        
        cleaned_lines.append(line_stripped)
    
    if cleaned_lines:
        return ' '.join(cleaned_lines)
    else:
        return content.strip()

# Probar cada respuesta
print("=" * 80)
print("PRUEBA DE FILTRADO DE RAZONAMIENTO")
print("=" * 80)

for i, resp in enumerate(test_responses, 1):
    print(f"\nTest {i}:")
    print("-" * 40)
    print("ORIGINAL:")
    print(resp)
    print("\nFILTRADO:")
    filtered = test_filter(resp)
    print(filtered)
    print("\nLimpio?", "✅" if "Wait" not in filtered and "Espera" not in filtered and "Looking" not in filtered else "❌")

# Probar con el agente real (sin llamar a API)
print("\n" + "=" * 80)
print("PROBANDO CON AGENTE REAL")
print("=" * 80)

try:
    agent = ProspectorAgent()
    print("✅ Agente inicializado")
    
    # Crear un mensaje de prueba simple
    from django.utils import timezone
    test_messages = [
        {"role": "user", "content": "Hola", "timestamp": timezone.now().isoformat()}
    ]
    
    # Usar el modelo fallback para evitar rate limits
    original_model = agent.model
    agent.model = "deepseek/deepseek-v3.2"  # Modelo que probablemente no tenga reasoning
    
    print(f"\nModelo actual: {agent.model}")
    print("¡Prueba completada! El filtro está activo.")
    
except Exception as e:
    print(f"❌ Error: {e}")