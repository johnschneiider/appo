import os
import json
import time
import logging
from typing import List, Dict, Optional
from django.conf import settings
from django.utils import timezone
import openai
import requests
import threading as _threading

logger = logging.getLogger(__name__)

# ── Semáforo global de concurrencia LLM ──
# Limita cuántas llamadas a OpenRouter pueden estar EN VUELO al mismo tiempo.
# Cuando muchos leads contestan a la vez, las respuestas se serializan en vez de
# disparar 50 requests simultáneos (que truenan la API free con 429 y tumban el bot).
# El resto de threads esperan su turno aquí sin romper nada.
_LLM_MAX_CONCURRENCY = int(os.getenv('LLM_MAX_CONCURRENCY', '4'))
_LLM_SEMAPHORE = _threading.BoundedSemaphore(_LLM_MAX_CONCURRENCY)

class ProspectorAgent:
    """
    Agente LLM para prospección de leads vía WhatsApp.
    Usa OpenRouter con modelos gratuitos y mantiene contexto aislado por lead.
    """

    # Respuestas prohibidas - si el LLM genera alguna de estas, se descarta y se usa fallback
    # Solo frases REALMENTE dañinas: call-center genérico + fuga de prompt.
    # NOTA: NO incluir "Gracias por escribir" ni "Perfecto/Excelente" - son válidas
    # y el propio prompt de Fase 1 usa "gracias por escribir". Bloquearlas causaba
    # autosabotaje (la respuesta buena se descartaba y caía en fallback rígido).
    FORBIDDEN_PATTERNS = [
        "Un asesor te contactará",
        "Un asesor se pondrá en contacto",
        "Un asesor se comunicará",
        "En breve nos comunicaremos",
        "Pronto te atenderemos",
        "Hemos recibido tu mensaje",
        "Tu mensaje ha sido recibido",
        "Uno de nuestros agentes",
        "Nuestro equipo de ventas",
        "Te contactaremos a la brevedad",
        "Estamos procesando tu solicitud",
        "Estimado cliente",  # Corporativo frío
        "Gusto en saludarte",  # Corporativo
        "Entendido. Estoy listo",  # Fuga de prompt
        "Quedo atento a los mensajes",  # Fuga de prompt
        "Estoy listo para empezar",  # Fuga de prompt
        "listo para responderles",  # Fuga de prompt
        "listo para empezar",  # Fuga de prompt
        "responderles como",  # Fuga de prompt
        "estoy listo para",  # Fuga de prompt
        "asesor te contactará",  # Fuga de prompt
    ]

    # Modelos de OpenRouter gratuitos (orden por fiabilidad verificada 2026-06-13).
    # Gemma 4 31B es el único estable hoy (3/3 OK). El resto se rate-limitea upstream
    # pero se recupera, por eso quedan como fallback en cascada.
    # Reordenado 2026-06-13: gpt-oss-120b probado en vivo da la mejor calidad/estabilidad
    # (natural, colombiano, sin fuga de prompt). Gemma soltaba frases de su propia blacklist.
    # Todos free, gran ventana de contexto, cascada para tolerar 429 upstream.
    FREE_MODELS = [
        "openai/gpt-oss-120b:free",                 # Primario: 131K ctx, mejor calidad probada, estable
        "google/gemma-4-31b-it:free",               # Fallback 1: 262K ctx, sin razonamiento
        "qwen/qwen3-next-80b-a3b-instruct:free",    # Fallback 2: 262K ctx
        "meta-llama/llama-3.3-70b-instruct:free",   # Fallback 3: 131K ctx
        "google/gemma-4-26b-a4b-it:free",           # Fallback 4: misma familia que Gemma
        "nvidia/nemotron-3-super-120b-a12b:free",   # Último recurso (1M ctx, emite razonamiento, lo limpia el filtro)
    ]

    # Conocimiento base sobre APPO - v6.0 (Jun 2026) - Venta consultiva ética, inbound+outbound
    BASE_KNOWLEDGE = """
IDENTIDAD
Eres Juan, colombiano, ~30 años. Ayudas a barberías y peluquerías a organizarse mejor con Appo.
Eres cálido, tranquilo, honesto y muy buena gente. Vendes sin presionar: persuades mostrando
valor real, no empujando. Escribes como un amigo que de verdad quiere ayudar, no como un robot.
Mensajes cortos, máximo 3 líneas. Una sola pregunta por mensaje. Usas emojis con medida.
Expresiones colombianas naturales: "parce", "dale", "tranqui", "bien", "¿cómo vas?". Tratas de "tú".

🔀 DOS TIPOS DE LEAD (clave: detecta cuál es por el primer mensaje)
1) INBOUND (te escribió primero, casi siempre por publicidad). Viene CALIENTE: ya vio el anuncio,
   tiene curiosidad o un dolor. NO lo trates como desconocido frío. Agradece que escribió, conecta
   rápido con lo que busca y avanza hacia la prueba. Suelen abrir con "info", "precios", "cómo
   funciona", "hola", o contando su problema. Aprovecha el interés: no lo enfríes con mil preguntas.
   Ej: "¡Hola! 👋 Soy Juan, qué bueno que escribiste. ¿Tienes barbería o peluquería? Te cuento rapidito cómo Appo te ayuda."
2) OUTBOUND (nosotros le escribimos a su negocio desde nuestra base). Viene FRÍO: no nos conoce.
   Primero confirma que es el negocio, preséntate y entiende su día a día ANTES de ofrecer.
   Ej: "¡Hola! 👋 Soy Juan. Gracias por responder. ¿Tú cómo manejas las citas ahorita, por WhatsApp o llamadas?"
Si dudas de cuál es: si el lead pregunta por Appo, precios o info → trátalo como inbound (caliente).

🎯 CÓMO VENDES (consultivo: primero entender, luego ayudar, después cerrar)
No es un guión rígido: es una conversación natural por etapas. Lée dónde está el lead y responde a eso.
El objetivo final SIEMPRE es que pruebe Appo gratis (es lo que más lo beneficia y a ti también).

ETAPA 1 - CONECTAR
Inbound: agradece que escribió y pregunta algo simple para enganchar ("¿tienes barbería o peluquería?").
Outbound: preséntate breve y pregunta cómo maneja las citas hoy.

ETAPA 2 - ENTENDER SU SITUACIÓN
Pregunta cómo gestiona las citas hoy. Escucha. Que sienta que te importa su negocio, no vender.
Conecta su realidad con un dolor concreto, sin dramatizar:
  "Claro, por WhatsApp se pierden mensajes y a veces se cruzan dos citas a la misma hora. ¿Te pasa?"

ETAPA 3 - MOSTRAR EL VALOR (cuando ya entendiste su dolor)
Presenta Appo como el alivio concreto a SU problema. Beneficio sobre función:
  "Con Appo tus clientes agendan solos 24/7, tú ves la agenda del día en el celu y ya. Sin chats, sin cruces."
  "Y como manda recordatorio automático antes de cada cita, llega menos gente tarde o sin avisar."

ETAPA 4 - INVITAR A PROBAR / CERRAR
El mejor cierre no es el precio: es la prueba gratis sin riesgo. Baja la barrera al máximo.
  "Lo bueno es que tiene una capa gratis para siempre, sin tarjeta. Entras a appo.com.co y la pruebas hoy mismo. ¿Te animas?"
Si muestra interés o pide precio: muestra los planes con [IMAGEN_PLANES].

💰 SOBRE EL PRECIO (manejo natural, NO evasivo)
No abras con precio. Pero si el lead pregunta precio directo, NO lo esquives de forma robótica.
  1a vez (sin contexto): "Depende de cuántos barberos tengan, por eso te preguntaba. ¿Cuántos son?"
  Si insiste o ya hubo contexto: "Tranqui, te muestro los planes. [IMAGEN_PLANES]"
NUNCA esquives el precio más de UNA vez. Si pregunta dos veces, muestra la imagen sí o sí.
La honestidad vende más que la evasión.

🚫 LO QUE NUNCA HACES (reglas éticas innegociables)
- Tirar el pitch completo en el primer mensaje
- Esquivar el precio más de 1 vez (suena a vendedor turbio)
- Presionar, meter urgencia falsa o exagerar resultados
- INVENTAR funciones que Appo no tiene. Solo prometes lo de la lista "QUÉ HACE APPO". Si preguntan
  por algo que no está, sé honesto: "Eso por ahora no lo tiene, pero sí hace X, Y, Z."
- Frases de call center: "Estimado cliente", "Gusto en saludarte", "Un asesor te contactará"
- Mentir. Si preguntan de dónde sacaste el número: "De directorios públicos como Google Maps."

📸 IMAGEN DE PLANES
Tenés una imagen que resume los planes. NO es un recurso de último recurso: es tu herramienta de
venta. Envíala cuando el lead muestre interés genuino o pregunte por precio (no esperes a que
insista 3 veces). Inbound que pregunta precio temprano: dale 1 pregunta de contexto y muéstrala.
Incluí [IMAGEN_PLANES] al final. No describas precios en texto, la imagen los muestra.
Ej: "Bien, mira: Appo tiene dos planes. [IMAGEN_PLANES]"
NO la envíes en el mensaje 1-2 de un lead frío, ni cuando ya dijo "no me interesa".

🎭 MANEJO DE OBJECIONES (máximo 1 pivot; si insiste el no, cierra cálido y digno)
- "Es caro": "Son $49.000 por barbero al mes. Con que evites 1 cliente perdido a la semana ya se paga solo. Y lo pruebas 30 días sin pagar ni poner tarjeta."
- "Ya tengo plataforma/sistema": NO te rindas, pivota UNA vez con curiosidad:
  "Bacano, ¿cuál usas? Te pregunto porque muchas plataformas solo dan la agenda. Appo aparte manda recordatorios automáticos, bloquea a los que no llegan y te calcula las comisiones de cada barbero. ¿Eso lo tienes hoy?"
  Si dice que su sistema le sirve y no quiere cambiar: "Dale, si ya te funciona, perfecto 🙌 Cualquier día que quieras comparar, ahí está appo.com.co. Buen día."
- "Uso Barberias.co (gratis)": "Claro, para agenda básica sirve. La diferencia es que Appo aparte te calcula comisiones, bloquea a los que nunca llegan y te muestra los ingresos del día. Es más asistente que agenda. Te muestro los planes 👇 [IMAGEN_PLANES]"
- "No uso tecnología": "Tranqui, es solo un link. Tus clientes entran y eligen. Tú ves la agenda en el celu, nada más."
- "No me interesa / estoy bien así": "Tranqui, sin afán 🙌 Si algún día se te enredan las citas o se te pierden clientes por no-show, ahí tienes appo.com.co — 30 días gratis sin tarjeta. Buen día." (aquí SÍ cierra, no insistas)
- "Déjame pensarlo": "Dale, sin afán. Te dejo appo.com.co por si quieres mirarlo con calma — 30 días gratis, sin tarjeta. Cuando gustes te ayudo a montarlo 🙌"

🚪 CIERRES
- Si dice NO: "Dale, tranqui. Buen día 🙌" (no insistas)
- Si está molesto: "Disculpá, no era la idea molestar. No te escribo más. Buen día." (NUNCA link)
- Si llega un mensaje automático de WhatsApp Business (bot de bienvenida/horarios): NO te rindas
  ni mandes un punto. Responde cálido y con curiosidad para que una PERSONA del equipo te lea y
  conteste. Ej: "Jaja veo que me contestó el asistente automático 🤖 Cuando me lea alguien del equipo:
  con Appo sus clientes agendan solos 24/7 y dejan de perder citas por no-show. ¿Les muestro en 1 min?"
- Si manda audio/imagen: "Recibí tu nota de voz 🎙️ Todavía no puedo escuchar audios. ¿Me lo cuentas por texto?"

📊 QUÉ HACE APPO (SOLO promete esto; es lo que existe de verdad)
Plataforma colombiana de reservas para barberías/peluquerías.
- Reservas online 24/7: tus clientes agendan solos desde un link, sin escribirte
- Recordatorios automáticos por WhatsApp antes de cada cita (1 día antes y 3 horas antes)
- Control de inasistencias con bloqueo automático: el cliente que falta varias veces no puede volver a reservar
- Comisiones automáticas por barbero: calcula cuánto le toca a cada uno, sin hacer cuentas a mano
- Estadísticas del día: ingresos, citas completadas/canceladas y ticket promedio
- Cada barbero tiene su propio perfil y agenda

PRECIO
- Capa gratuita para siempre, sin tarjeta, sin límite de barberos
- Plan Pro: $49.000/barbero/mes, 30 días gratis, sin permanencia

FAQ
- App: funciona en el navegador, no instalas nada
- Demo: la capa gratuita ES la demo, para siempre
- Pago: tarjeta o PSE, facturación electrónica
- Permanencia: cero · appo.com.co · soporte@appo.com.co · dev colombiano
"""

    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY no encontrada en variables de entorno")

        self.model = self.FREE_MODELS[0]
        self.fallback_model = self.FREE_MODELS[1]
        self.max_retries = 2
        self.retry_delay = 2  # segundos

    def _call_api(self, messages: List[Dict], model: str = None) -> Optional[str]:
        """Llamada a la API de OpenRouter con manejo de reintentos."""
        import requests as _requests
        if model is None:
            model = self.model

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://appo.com.co",
            "X-Title": "APPO Lead Prospector",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 1500,
            "extra_body": {
                "reasoning": False
            }
        }

        for attempt in range(self.max_retries):
            try:
                # El POST (lo único que consume cuota upstream) va dentro del semáforo
                # global para acotar la concurrencia. El procesamiento posterior queda fuera.
                with _LLM_SEMAPHORE:
                    resp = _requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                content = data['choices'][0]['message']['content']

                if content:
                    import re

                    # SOLO meta-razonamiento en INGLÉS (los modelos free a veces lo filtran).
                    # NO incluir conectores en español (Pero, Claro, Entonces, También, Porque,
                    # Así que, Sin embargo...) porque son aperturas NORMALES de un vendedor humano
                    # y al borrarlas se destruía la respuesta real → fallback rígido.
                    reasoning_patterns = [
                        r'^Wait[,\s].*',
                        r'^Let me think.*',
                        r'^Let\'?s think.*',
                        r'^Let me check.*',
                        r'^Let me see.*',
                        r'^Let\'?s see.*',
                        r'^Thinking[:\s].*',
                        r'^Okay, (the user|so|let|I).*',
                        r'^The user (said|wants|is|asked).*',
                        r'^Looking at (the|this).*',
                        r'^Looking back.*',
                        r'^Based on the (history|conversation|context|rules).*',
                        r'^I should (respond|reply|say|follow).*',
                        r'^I need to (respond|reply|follow|stick).*',
                        r'^In this case, (I|the|Juan).*',
                        r'^According to the (rules|script|instructions).*',
                        r'^As per the (rules|script|instructions).*',
                        r'^The (lead|system|instructions) (said|wants|already).*',
                        r'^.*\breasoning\b.*:',
                        r'^.*\bthinking\b.*:',
                        r'^.*\banalysis\b.*:',
                        r'^Espera, (the|let|I|debo|tengo).*',
                        r'^Déjame pensar.*',
                    ]

                    lines = content.split('\n')
                    cleaned_lines = []
                    skip_mode = False

                    for line in lines:
                        line_stripped = line.strip()
                        if not line_stripped:
                            if skip_mode:
                                skip_mode = False
                            continue

                        is_reasoning = False
                        for pattern in reasoning_patterns:
                            if re.match(pattern, line_stripped, re.IGNORECASE):
                                is_reasoning = True
                                break

                        if not is_reasoning and skip_mode:
                            continue

                        if is_reasoning:
                            skip_mode = True
                            continue

                        if skip_mode:
                            skip_mode = False

                        cleaned_lines.append(line_stripped)

                    if cleaned_lines:
                        content = ' '.join(cleaned_lines)
                        import re
                        content = re.sub(r'\s+', ' ', content).strip()
                    else:
                        content = content.strip()

                content = content.strip() if content else None

                # BLACKLIST CHECK: rechazar respuestas genéricas/de fuga de prompt
                if content:
                    for forbidden in self.FORBIDDEN_PATTERNS:
                        if forbidden.lower() in content.lower():
                            logger.warning(f'[SAFETY] Respuesta bloqueada por blacklist "{forbidden}": {content[:100]}...')
                            return None

                return content

            except Exception as e:
                logger.warning(f"Intento {attempt+1}/{self.max_retries} falló con modelo {model}: {e}")

                if "rate limit" in str(e).lower() or "429" in str(e):
                    wait_time = self.retry_delay * (attempt + 1)
                    logger.info(f"Rate limit detectado, esperando {wait_time}s")
                    time.sleep(wait_time)
                else:
                    time.sleep(self.retry_delay)

                # Cascada: en el último reintento de este modelo, saltar al siguiente
                # modelo de la lista FREE_MODELS (recorre toda la cadena, no solo 2).
                if attempt == self.max_retries - 1:
                    try:
                        idx = self.FREE_MODELS.index(model)
                    except ValueError:
                        idx = -1
                    next_idx = idx + 1
                    if 0 <= next_idx < len(self.FREE_MODELS):
                        next_model = self.FREE_MODELS[next_idx]
                        logger.info(f"Probando con siguiente modelo en cascada: {next_model}")
                        return self._call_api(messages, model=next_model)

        return None

    def generar_mensaje_inicial(self, nombre_establecimiento: str, ciudad: str = None) -> str:
        """
        Genera el primer mensaje estático de prospección con saludo horario colombiano.
        """
        import pytz
        from django.utils import timezone

        tz_col = pytz.timezone('America/Bogota')
        hora = timezone.now().astimezone(tz_col).hour

        if hora < 12:
            saludo = "buenos días"
        elif hora < 19:
            saludo = "buenas tardes"
        else:
            saludo = "buenas noches"

        return f"Hola, {saludo} 👋 ¿Aquí es {nombre_establecimiento}?"

    def generar_respuesta_autoreply(self,
                                    historial_conversacion: List[Dict],
                                    nombre_establecimiento: str = None) -> Optional[str]:
        """
        Genera una respuesta cuando el lead contestó con un mensaje AUTOMÁTICO de
        WhatsApp Business (bot de bienvenida/horarios). Objetivo: cruzar esa barrera
        sin sonar molesto, despertando curiosidad para que una persona real conteste.
        NO es una despedida. NO repite el saludo. Mantiene el interés.
        """
        nombre = nombre_establecimiento or 'el negocio'
        resumen = self._resumir_historial(historial_conversacion) if historial_conversacion else "Recién iniciamos contacto."
        instruccion = (
            "El lead respondió con el MENSAJE AUTOMÁTICO de su WhatsApp Business "
            "(un bot de bienvenida/horarios, no una persona). Tu objetivo es cruzar esa "
            "barrera con naturalidad y simpatía, para que una PERSONA real del equipo te lea "
            "y conteste. Reconoce con humor ligero que es el asistente automático, suelta UN "
            "beneficio concreto de Appo (agenda 24/7, no perder citas) y cierra con una pregunta "
            "breve y fácil de responder. NO te despidas, NO mandes link todavía, NO insistas, "
            "NO suenes a vendedor pesado. Máximo 2-3 líneas, cálido y colombiano."
        )
        system_content = f"""{self.BASE_KNOWLEDGE}

INSTRUCCIÓN ESPECÍFICA: {instruccion}

Negocio: {nombre}
Historial: {resumen}

Respondé SOLO con el texto del mensaje, sin explicaciones, sin metadatos."""
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Generá el mensaje para cruzar la barrera del auto-reply de {nombre}."},
        ]
        respuesta = self._call_api(messages)
        if respuesta:
            respuesta = respuesta.strip()
            if len(respuesta) < 15 or len(respuesta) > 500:
                return None
            for forbidden in self.FORBIDDEN_PATTERNS:
                if forbidden.lower() in respuesta.lower():
                    logger.warning(f'[AUTOREPLY] Bloqueada por blacklist: {respuesta[:80]}...')
                    return None
            return respuesta
        return None

    def generar_respuesta(self,
                         historial_conversacion: List[Dict],
                         ultimo_mensaje_cliente: str) -> Optional[str]:
        """
        Genera una respuesta contextual basada en el historial de conversación.
        Usa ventana deslizante: si el historial es largo, resume los mensajes antiguos
        y mantiene los últimos 10 textuales para preservar el context window del modelo.
        """
        logger.error(f'[GENERAR_RESPUESTA] historial_conversacion length: {len(historial_conversacion)}')
        logger.error(f'[GENERAR_RESPUESTA] ultimo_mensaje_cliente: {ultimo_mensaje_cliente}')
        if len(historial_conversacion) == 0:
            logger.error('[GENERAR_RESPUESTA] Historial vacío - primera interacción')

        # Verificar si el cliente expresó rechazo permanente
        if es_rechazo_permanente(ultimo_mensaje_cliente):
            logger.info(f'[RECHAZO] Cliente expresó rechazo permanente en generar_respuesta: {ultimo_mensaje_cliente[:80]}')
            return '[RECHAZO_PERMANENTE] Tranqui, sin afán 🙌 Si algún día te sirve, ahí tienes appo.com.co. Buen día.'

        # ── Construir mensajes con ventana deslizante ──
        KEEP_LAST = 10  # Últimos N mensajes que se mantienen textuales
        MAX_WINDOW = 15  # Umbral para activar compresión

        system_prompt = f"""{self.BASE_KNOWLEDGE}
        
IMPORTANTE: Responde SIEMPRE en español, natural y colombiano. Avanza por las etapas según dónde
esté el lead, sin sonar a guión. Si el historial está vacío, solo conecta (Etapa 1). El objetivo de
toda conversación es que el lead pruebe Appo gratis en appo.com.co. Sé persuasivo con valor y honestidad,
nunca con presión. Responde directo a lo que el lead pregunta; no esquives.
"""

        messages = [
            {"role": "system", "content": system_prompt}
        ]

        if len(historial_conversacion) > MAX_WINDOW:
            # ── Modo ventana deslizante: resumir historial antiguo ──
            older = historial_conversacion[:-KEEP_LAST]  # Lo que se resume
            recent = historial_conversacion[-KEEP_LAST:]   # Lo que se pasa textual

            logger.info(f'[CONTEXTO] Ventana deslizante activa: {len(older)} antiguos resumidos + {len(recent)} recientes')

            # Resumir historial antiguo en 2-3 líneas
            summary = self._resumir_historial(older)
            if summary:
                messages.append({
                    "role": "system",
                    "content": f"[RESUMEN DE LA CONVERSACIÓN ANTERIOR]\n{summary}\n[/RESUMEN]"
                })

            # Agregar mensajes recientes textuales
            for msg in recent:
                role = "assistant" if msg["role"] == "assistant" else "user"
                messages.append({"role": role, "content": msg["content"]})
        else:
            # ── Modo normal: historial completo ──
            for msg in historial_conversacion:
                role = "assistant" if msg["role"] == "assistant" else "user"
                messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": ultimo_mensaje_cliente})

        logger.error(f'[GENERAR_RESPUESTA] messages a enviar a API: {json.dumps(messages, ensure_ascii=False)[:1000]}')

        respuesta = self._call_api(messages)
        logger.error(f'[GENERAR_RESPUESTA] respuesta de API: {respuesta}')

        if respuesta:
            respuesta = respuesta.strip()

            # BLACKLIST CHECK en generar_respuesta (segunda capa)
            for forbidden in self.FORBIDDEN_PATTERNS:
                if forbidden.lower() in respuesta.lower():
                    logger.warning(f'[SAFETY] Respuesta bloqueada en generar_respuesta "{forbidden}": {respuesta[:100]}...')
                    return None

            razonamiento_markers = [
                'needs to stick to the script', 'need to follow', 'should respond with',
                'according to the rules', 'the system already', 'as per the',
                'let me think', 'let\'s think', 'wait, the', 'but wait',
                'in this case', 'the lead\'s response', 'looking at the',
                'first message from lead', 'second message from lead',
                'alternatively, maybe', 'so regardless', 'then juan',
                'so the lead', 'then the lead', 'so in this case',
            ]
            resp_lower = respuesta.lower()
            is_razonamiento = any(m in resp_lower for m in razonamiento_markers)
            is_too_long = len(respuesta) > 400

            if is_razonamiento or is_too_long:
                logger.warning(f'[SAFETY] Respuesta filtrada por safety: {respuesta[:100]}...')
                return None

        return respuesta if respuesta else None

    def generar_followup(self,
                        historial_conversacion: List[Dict],
                        etapa: str,
                        nombre_establecimiento: str = None) -> Optional[str]:
        """
        Genera un follow-up contextual para leads que no han respondido.
        SOLO genera followup_24h (máximo 1 follow-up total).
        Para followup_48h retorna None directamente (no insistir más).
        """
        logger.info(f'[FOLLOWUP] Generando {etapa} para {nombre_establecimiento or "lead"}')
        
        if etapa == 'followup_48h':
            # No generar segundo follow-up: si no respondió al primero, no insistir
            logger.info(f'[FOLLOWUP] Etapa followup_48h: retornando None (seguimiento único máximo)')
            return None
        
        if etapa == 'followup_24h':
            instruccion = (
                "El lead recibió el saludo inicial pero NO respondió. "
                "Genera UN follow-up natural, relajado, como si retomaras el tema con un amigo. "
                "NO repitas el saludo anterior. NO seas insistente. "
                "Presentá el valor de Appo de forma ligera: agenda automática 24/7, "
                "sin pérdida de citas, capa gratis sin tarjeta. "
                "Este es el ÚNICO follow-up que se envía. Si no responde, se archiva. "
                "Máximo 2-3 líneas. Terminá con una pregunta abierta."
            )
        else:
            raise ValueError(f'Etapa de follow-up desconocida: {etapa}')
        
        nombre = nombre_establecimiento or 'amigo'
        
        # Construir resumen del historial si existe
        resumen = self._resumir_historial(historial_conversacion) if historial_conversacion else "Aún no hay conversación."
        
        # Cantidad de intentos previos
        intentos_previos = len([m for m in historial_conversacion if m.get('role') == 'assistant'])
        
        system_content = f"""{self.BASE_KNOWLEDGE}

INSTRUCCIÓN ESPECÍFICA: {instruccion}

Lead: {nombre}
Intentos previos de contacto: {intentos_previos}
Historial: {resumen}

Respondé SOLO con el texto del follow-up, sin explicaciones, sin metadatos."""
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Generá el {etapa} para {nombre}."}
        ]
        
        respuesta = self._call_api(messages)
        if respuesta:
            respuesta = respuesta.strip()
            # Validar que sea coherente: entre 30 y 400 caracteres
            if len(respuesta) < 20 or len(respuesta) > 500:
                logger.warning(f'[FOLLOWUP] Respuesta fuera de rango ({len(respuesta)} chars): {respuesta[:80]}...')
                return None
            # Blacklist check
            for forbidden in self.FORBIDDEN_PATTERNS:
                if forbidden.lower() in respuesta.lower():
                    logger.warning(f'[FOLLOWUP] Bloqueada por blacklist: {respuesta[:80]}...')
                    return None
            return respuesta
        return None

    def generar_followup_virtual(self,
                               historial_whatsapp: list,
                               stage_name: str,
                               consecutive_bot: int) -> Optional[str]:
        """
        Genera follow-up para leads virtuales (inbound que dejó de responder).
        historial_whatsapp: lista de MensajeWhatsApp en orden cronológico.
        stage_name: 'recordatorio_30min', 'recordatorio_2h', 'cierre_24h'
        consecutive_bot: cuántos mensajes seguidos del bot sin respuesta del lead.
        """
        logger.info(f'[FOLLOWUP_VIRTUAL] Generando {stage_name}')
        
        # Convertir historial de WhatsApp a formato rol/content
        historial = []
        for m in historial_whatsapp:
            role = 'assistant' if m.from_me else 'user'
            content = (m.message_text or '').strip()
            if content and len(content) > 3:
                historial.append({'role': role, 'content': content})
        
        # Resumir el historial
        resumen = self._resumir_historial(historial) if historial else "El lead envió un mensaje inicial."
        
        # Instrucción según la etapa
        if stage_name == 'recordatorio_30min':
            instruccion = (
                "El lead nos escribió primero (inbound), le respondiste, y ahora lleva "
                "un rato sin responder. Generá un follow-up SUAVE para retomar la "
                "conversación. Soná natural, como retomando el tema sin presión. "
                "Máximo 2 líneas. Incluí una pregunta abierta."
            )
        elif stage_name == 'recordatorio_2h':
            instruccion = (
                "El lead no respondió al primer follow-up. Generá otro más directo. "
                "Presentá el valor concreto de Appo: agenda 24/7, capa gratis, "
                "prueba social (+11 barberías). "
                "Máximo 2-3 líneas. Sin presión pero más concreto."
            )
        elif stage_name == 'cierre_24h':
            instruccion = (
                "Este es el ÚLTIMO follow-up para un lead que no ha respondido "
                "a varios mensajes. Soná tranquilo, respetuoso, sin presión. "
                "Dejá la puerta abierta con appo.com.co y despedite cordialmente. "
                "Máximo 2-3 líneas."
            )
        else:
            raise ValueError(f'Etapa virtual desconocida: {stage_name}')
        
        system_content = f"""{self.BASE_KNOWLEDGE}

INSTRUCCIÓN ESPECÍFICA: {instruccion}

Historial de la conversación:
{resumen}

Respondé SOLO con el texto del follow-up, sin explicaciones, sin metadatos."""
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Generá el {stage_name} basado en la conversación."}
        ]
        
        respuesta = self._call_api(messages)
        if respuesta:
            respuesta = respuesta.strip()
            if len(respuesta) < 15 or len(respuesta) > 500:
                logger.warning(f'[FOLLOWUP_VIRTUAL] Fuera de rango ({len(respuesta)} chars): {respuesta[:80]}...')
                return None
            for forbidden in self.FORBIDDEN_PATTERNS:
                if forbidden.lower() in respuesta.lower():
                    logger.warning(f'[FOLLOWUP_VIRTUAL] Bloqueada por blacklist: {respuesta[:80]}...')
                    return None
            return respuesta
        return None

    def _resumir_historial(self, historial_antiguo: List[Dict]) -> Optional[str]:
        """
        Resume los mensajes antiguos de una conversación en 2-3 líneas.
        Usa una llamada separada al LLM (sin el system prompt de ventas).
        """
        if not historial_antiguo:
            return None

        # Construir texto de la conversación antigua
        lineas = []
        for msg in historial_antiguo:
            role = "Cliente" if msg.get("role") == "user" else "Appo"
            content = msg.get("content", "")[:200]
            if content.strip():
                lineas.append(f"{role}: {content}")

        if not lineas:
            return None

        dialogo = "\n".join(lineas[:30])  # Máximo 30 líneas para el resumen

        summary_messages = [
            {"role": "system", "content": "Eres un asistente que resume conversaciones. Resume en 2-3 líneas máximo, en español, en tercera persona. Solo hechos: quién es el cliente, qué preguntó, qué se le dijo, si mostró interés o no."},
            {"role": "user", "content": f"Resume esta conversación entre Appo (empresa de agenda para barberías) y un lead:\n\n{dialogo}\n\nResumen (2-3 líneas):"}
        ]

        resumen = self._call_api(summary_messages)
        if resumen and len(resumen) > 10:
            logger.info(f'[CONTEXTO] Resumen generado: {resumen[:150]}')
            return resumen.strip()
        return None

    def evaluar_intencion(self, mensaje_cliente: str) -> Dict:
        """
        Evalúa la intención del lead basado en su mensaje.
        """
        prompt = f"""Clasifica la intención del siguiente mensaje de un lead:

        "{mensaje_cliente}"

        Opciones:
        1. "pregunta_precio" - Pregunta por precios, costos, tarifas
        2. "interesado" - Muestra interés en el servicio
        3. "informacion" - Pide más información general
        4. "negativo" - Rechazo o desinterés
        5. "neutral" - Saludo o mensaje neutro

        Responde SOLO con el nombre de la categoría (una palabra)."""

        messages = [
            {"role": "system", "content": "Eres un clasificador de intenciones comerciales. Devuelves solo la palabra clave."},
            {"role": "user", "content": prompt}
        ]

        categoria = self._call_api(messages)
        if categoria:
            categoria = categoria.strip().lower()
            validas = ["pregunta_precio", "interesado", "informacion", "negativo", "neutral"]
            if categoria not in validas:
                if "precio" in categoria or "cuesta" in categoria or "costo" in categoria:
                    categoria = "pregunta_precio"
                elif "interesa" in categoria or "me gusta" in categoria:
                    categoria = "interesado"
                elif "información" in categoria or "más info" in categoria:
                    categoria = "informacion"
                elif "no" in categoria or "gracias" in categoria or "adiós" in categoria:
                    categoria = "negativo"
                else:
                    categoria = "neutral"
        else:
            categoria = "neutral"

        score = 0.7 if categoria in ["interesado", "pregunta_precio"] else 0.3

        return {"categoria": categoria, "score": score}


# --- Funciones de envío en partes ---
import time as _time
import random as _random

def formatear_saludo(nombre: str) -> list[str]:
    """
    Retorna el saludo inicial con horario colombiano.
    """
    import pytz
    from django.utils import timezone

    tz_col = pytz.timezone('America/Bogota')
    hora = timezone.now().astimezone(tz_col).hour

    if hora < 12:
        saludo = "buenos días"
    elif hora < 19:
        saludo = "buenas tardes"
    else:
        saludo = "buenas noches"

    # Variar el saludo: enviar el MISMO texto a cientos de números es una huella
    # fuerte de spam para Meta. Rotamos plantillas equivalentes manteniendo el tono.
    import random as _rnd
    plantillas = [
        f"Hola, {saludo} 👋 ¿Aquí es {nombre}?",
        f"¡Hola! {saludo.capitalize()} 😊 ¿Hablo con {nombre}?",
        f"{saludo.capitalize()} 👋 ¿Es {nombre}?",
        f"¡Hola, {saludo}! ¿Este es el WhatsApp de {nombre}? 🙌",
        f"Hola 👋 {saludo}, ¿me comunico con {nombre}?",
    ]
    return [_rnd.choice(plantillas)]

def guardar_mensaje(conversacion, role: str, contenido: str):
    """Guarda un mensaje en la conversación."""
    ahora = timezone.now()
    conversacion.mensajes.append({
        'role': role,
        'content': contenido,
        'timestamp': ahora.isoformat()
    })
    conversacion.ultimo_contacto = ahora
    conversacion.save()

def procesar_lead_inicial(lead_id: int) -> list[str]:
    """Retorna lista de partes para envío separado en lugar de un bloque único."""
    from leads_admin.models import Lead, LeadConversacion
    lead = Lead.objects.using('leads_db').get(id=lead_id)
    nombre = lead.nombre_establecimiento or "amigo"
    conv, _ = LeadConversacion.objects.using('leads_db').get_or_create(
        lead=lead,
        defaults={'mensajes': [], 'estado': 'nuevo'}
    )

    # DEDUP: verificar si ya se envió saludo para evitar envíos duplicados
    if conv.mensajes and len(conv.mensajes) > 0:
        for m in conv.mensajes:
            if m.get('role') == 'assistant' and '¿Aquí es' in m.get('content', ''):
                logger.warning(f'[DEDUP] Saludo ya enviado a {nombre}, saltando')
                return []  # No enviar nada, ya se envió

    partes = formatear_saludo(nombre)
    mensaje_completo = "\n\n".join(partes)
    guardar_mensaje(conv, "assistant", mensaje_completo)
    if conv.estado == 'nuevo':
        conv.estado = 'contactado'
        conv.save()
    return partes

def procesar_lead(lead_id: int, mensaje_entrante: str = None) -> str:
    """Procesa un lead y devuelve respuesta (string)."""
    from leads_admin.models import Lead, LeadConversacion
    from django.utils import timezone

    lead = Lead.objects.using('leads_db').get(id=lead_id)

    conv, _ = LeadConversacion.objects.using('leads_db').get_or_create(
        lead=lead,
        defaults={'mensajes': [], 'estado': 'nuevo'}
    )

    if mensaje_entrante is None:
        nombre = lead.nombre_establecimiento or "amigo"
        partes = formatear_saludo(nombre)
        mensaje_completo = "\n\n".join(partes)
        guardar_mensaje(conv, "assistant", mensaje_completo)
        if conv.estado == 'nuevo':
            conv.estado = 'contactado'
            conv.save()
        return mensaje_completo
    else:
        agent = get_prospector_agent()
        historial_previo = list(conv.mensajes) if conv.mensajes else []
        logger.error(f'[PROCESAR_LEAD] historial_previo length: {len(historial_previo)}')
        logger.error(f'[PROCESAR_LEAD] mensaje entrante: {mensaje_entrante}')
        respuesta = agent.generar_respuesta(historial_previo, mensaje_entrante)
        logger.error(f'[PROCESAR_LEAD] respuesta generada: {respuesta}' if respuesta else '[PROCESAR_LEAD] respuesta generada: None')

        guardar_mensaje(conv, "user", mensaje_entrante)
        if respuesta:
            # Detectar rechazo permanente
            if respuesta.startswith('[RECHAZO_PERMANENTE]'):
                logger.info(f'[RECHAZO_PERMANENTE] Marcando lead {lead_id} como rechazo_permanente')
                texto_limpio = respuesta.replace('[RECHAZO_PERMANENTE]', '', 1).strip()
                guardar_mensaje(conv, "assistant", texto_limpio)
                conv.estado = 'rechazo_permanente'
                conv.ultimo_contacto = timezone.now()
                conv.save(using='leads_db')
                lead.estado = 'rechazo_permanente'
                lead.save(using='leads_db')
                return texto_limpio
            guardar_mensaje(conv, "assistant", respuesta)
            conv.ultimo_contacto = timezone.now()
            conv.estado = 'respondio'  # Lead respondio: NO enviar follow-ups
            conv.save(using='leads_db')
            return respuesta
        else:
            fallback = _generar_fallback_contextual(conv, mensaje_entrante)
            if fallback.startswith('[RECHAZO_PERMANENTE]'):
                logger.info(f'[RECHAZO_PERMANENTE] Marcando lead {lead_id} como rechazo_permanente (fallback)')
                texto_limpio = fallback.replace('[RECHAZO_PERMANENTE]', '', 1).strip()
                guardar_mensaje(conv, "assistant", texto_limpio)
                conv.estado = 'rechazo_permanente'
                conv.ultimo_contacto = timezone.now()
                conv.save(using='leads_db')
                lead.estado = 'rechazo_permanente'
                lead.save(using='leads_db')
                return texto_limpio
            guardar_mensaje(conv, "assistant", fallback)
            conv.ultimo_contacto = timezone.now()
            conv.estado = 'respondio'  # Lead respondio: NO enviar follow-ups
            conv.save(using='leads_db')
            return fallback


def _generar_fallback_contextual(conv, mensaje_cliente: str) -> str:
    """Genera un fallback que continúa la conversación, no la resetea."""
    nombre = conv.lead.nombre_establecimiento or ""
    mensaje_cliente_lower = mensaje_cliente.lower().strip()

    # Verificar rechazo permanente
    if es_rechazo_permanente(mensaje_cliente):
        logger.info(f'[RECHAZO] Cliente expresó rechazo permanente en fallback: {mensaje_cliente[:80]}')
        return '[RECHAZO_PERMANENTE] Tranqui, sin afán 🙌 Si algún día te sirve, ahí tienes appo.com.co. Buen día.'

    # ── RESPUESTAS A MEDIA (audio, imagen, video, sticker) ──
    if mensaje_cliente in ('[AUDIO]', '[IMAGEN]', '[VIDEO]', '[STICKER]', '[DOCUMENTO]'):
        respuestas_media = {
            '[AUDIO]': 'Recibí tu nota de voz 🎙️ Todavía no puedo escuchar audios. ¿Me lo cuentas por texto? Así te respondo al toque.',
            '[IMAGEN]': 'Recibí la imagen 📸 ¡Gracias! Por ahora solo puedo leer texto. ¿Me cuentas por acá qué necesitas?',
            '[VIDEO]': 'Recibí el video 🎬 Qué bien. No puedo ver videos todavía, ¿me cuentas por texto de qué se trata?',
            '[STICKER]': 'Jaja 😄 ¿En qué andamos? Contame por texto y te ayudo.',
            '[DOCUMENTO]': 'Recibí el archivo 📎 Gracias. No puedo abrir documentos todavía. ¿Me hacés un resumen por texto?',
        }
        return respuestas_media.get(mensaje_cliente, 'Recibido 👍 ¿Me lo puedes contar por texto? Así te ayudo mejor.')

    msgs = conv.mensajes if isinstance(conv.mensajes, list) else []
    ultimo_nuestro = ""
    for m in reversed(msgs):
        if m.get('role') == 'assistant':
            ultimo_nuestro = m.get('content', '')
            break

    # ── FASE 1: Historial VACÍO (inbound, lead escribió de la nada) → solo saludar ──
    es_historial_vacio = len(msgs) == 0
    if es_historial_vacio and mensaje_cliente_lower in ('hola', 'hola?', 'hola!', 'quiénes?', 'quién habla', 'quién eres', 'dígame', 'digame', 'buenas', 'buenos días', 'buenas tardes', 'buenas noches', 'hey', 'alo', 'aló'):
        return f"¡Hola! 👋 Soy Juan, ¿cómo vas? Gracias por escribir."

    # ── FASE 2: Historial tiene 1 msg (nuestro saludo outbound) → lead respondió → presentarse ──
    if len(msgs) <= 1:
        return f"¡Hola! 👋 Soy Juan. Gracias por responder. ¿Tú cómo manejas las citas ahorita, por WhatsApp o llamadas?"

    # ⛔ REGLA DE ORO: NUNCA precio en primer mensaje. Redirigir SIEMPRE.
    # Solo mostrar [IMAGEN_PLANES] si la conversación ya tiene 3+ interacciones (Fase 4-5)
    total_mensajes = len(msgs) if isinstance(msgs, list) else 0
    if any(word in mensaje_cliente_lower for word in ['cuanto', 'precio', 'cuesta', 'vale', 'plan', 'planes']):
        if total_mensajes >= 3:  # ya hubo al menos 1 intercambio real → muestra los planes
            return f"Depende de cuántos barberos tengan. Mira, acá te dejo los planes. [IMAGEN_PLANES]"
        else:
            return f"Depende de cuántos barberos tengan. ¿Cuántos son en el negocio? Así te digo el plan que te sirve."

    if any(word in mensaje_cliente_lower for word in ['demo', 'probar', 'prueba']):
        return "Sí claro. La capa gratuita es la demo - para siempre, sin tarjeta, sin límite de barberos. Entrás a appo.com.co y la probás ya. ¿Te sirve?"

    if any(word in mensaje_cliente_lower for word in ['ver', 'mostrar', 'explicar', 'info', 'información', 'plataforma']):
        return "Mira, es sencillo: cada barbero tiene su perfil, los clientes entran al link de la barbería y agendan solos. Tú ves la agenda del día. ¿Te sirve algo así o manejan todo por WhatsApp?"

    if any(word in mensaje_cliente_lower for word in ['si', 'dale', 'bien', 'listo', 'ok', 'claro', 'interesa', 'adelante', 'cuéntame', 'dime']):
        return "Bien 🙌 Con Appo tus clientes agendan solos 24/7, les llega recordatorio antes de la cita y tú ves todo desde el celu. ¿Cómo manejas las citas hoy, por WhatsApp o libreta?"

    if any(word in mensaje_cliente_lower for word in ['no', 'ahorita no', 'después', 'gracias']):
        return "Dale, tranqui. Cuando quieras, en appo.com.co está toda la info. Buen día 🙌"

    # DETECCIÓN DE AGRESIVIDAD / MOLESTIA: cierre definitivo, sin link
    agresivas = ['joder', 'dejen de', 'paren de', 'molestar', 'fastidiar', 'spam', 'estafa',
                 'no joda', 'deje de', '🖕', 'hostigar', 'acosar', 'insistir', 'dejan de']
    if any(word in mensaje_cliente_lower for word in agresivas):
        return "Disculpá, no era la idea molestar. No te escribo más. Buen día."

    if nombre:
        return f"Bien 👍 Te cuento: con Appo tus clientes agendan solos sin escribirte y les llega recordatorio antes de la cita. ¿Cómo lo manejas ahorita?"
    else:
        return "Bien 👍 Con Appo tus clientes agendan solos sin escribirte y les llega recordatorio antes de la cita. ¿Cómo manejas las citas ahorita, por WhatsApp?"


# Marcador interno para identificar mensajes que cruzan la barrera de auto-reply.
_AUTOREPLY_MARKER = '\u200b'  # zero-width space invisible, no se ve en WhatsApp

def es_rechazo_permanente(contenido: str) -> bool:
    """
    Detecta si un mensaje del cliente expresa rechazo explícito y definitivo.
    Retorna True si se detecta intención de no ser contactado más.
    """
    if not contenido:
        return False
    contenido_lower = contenido.lower().strip()
    frases_rechazo = [
        "no me interesa",
        "ya tengo",
        "estoy bien",
        "no me escribas",
        "paren de molestar",
        "no quiero",
        "gracias pero no",
        "déjame en paz",
    ]
    for frase in frases_rechazo:
        if frase in contenido_lower:
            return True
    return False

def _ya_cruzo_barrera(mensajes: list) -> bool:
    """True si el último mensaje del bot ya fue un cruce de barrera de auto-reply.
    Evita loops infinitos cuando el WA Business del lead reenvía su auto-reply."""
    if not isinstance(mensajes, list):
        return False
    for m in reversed(mensajes):
        if m.get('role') == 'assistant':
            return _AUTOREPLY_MARKER in (m.get('content') or '')
        if m.get('role') == 'user':
            # Hubo un mensaje real del lead entremedio → ya no es barrera consecutiva
            return False
    return False

def procesar_lead_autoreply(lead_id: int, mensaje_entrante: str) -> Optional[str]:
    """Lead REAL respondió con auto-reply de WA Business. Cruza la barrera una vez."""
    from leads_admin.models import Lead, LeadConversacion
    lead = Lead.objects.using('leads_db').get(id=lead_id)
    conv, _ = LeadConversacion.objects.using('leads_db').get_or_create(
        lead=lead, defaults={'mensajes': [], 'estado': 'nuevo'})
    historial_previo = list(conv.mensajes) if conv.mensajes else []
    # Guardar el auto-reply entrante como contexto
    guardar_mensaje(conv, 'user', mensaje_entrante)
    if _ya_cruzo_barrera(historial_previo):
        logger.info(f'[AUTOREPLY] Lead {lead_id} ya cruzó barrera antes, no insisto.')
        conv.estado = 'contactado'
        conv.save(using='leads_db')
        return None
    agent = get_prospector_agent()
    respuesta = agent.generar_respuesta_autoreply(historial_previo, lead.nombre_establecimiento)
    if not respuesta:
        respuesta = (f"Jaja veo que tienen el asistente automático 🙌 Cuando me lea alguien "
                     f"del equipo: con Appo sus clientes agendan solos 24/7 y dejan de perder "
                     f"citas. ¿Les muestro en 1 minutico cómo funciona?")
    guardar_mensaje(conv, 'assistant', respuesta + _AUTOREPLY_MARKER)
    # Importante: marcar 'respondio' para que NO entre al pipeline de follow-up/despedida
    conv.estado = 'respondio'
    conv.ultimo_contacto = timezone.now()
    conv.save(using='leads_db')
    return respuesta

def procesar_mensaje_whatsapp_autoreply(remote_jid: str, mensaje_cliente: str, phone: str = None) -> Optional[str]:
    """Lead VIRTUAL (inbound no registrado) respondió con auto-reply. Cruza barrera una vez."""
    from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
    import uuid
    chat, _ = ChatWhatsApp.objects.using('leads_db').get_or_create(
        chat_id=remote_jid, defaults={'phone': phone or '', 'contact_name': ''})
    MensajeWhatsApp.objects.using('leads_db').create(
        chat=chat, message_key=f'in_{remote_jid}_{uuid.uuid4().hex[:12]}',
        message_text=mensaje_cliente, from_me=False, timestamp=timezone.now())
    historial_qs = MensajeWhatsApp.objects.using('leads_db').filter(
        chat__chat_id=remote_jid).order_by('timestamp')[:20]
    historial = [{'role': 'assistant' if m.from_me else 'user',
                  'content': m.message_text or ''} for m in historial_qs]
    # Loop guard: si el último bot ya cruzó barrera y solo recibimos auto-reply, parar
    if _ya_cruzo_barrera(historial[:-1]):
        logger.info(f'[AUTOREPLY] Virtual {remote_jid} ya cruzó barrera, no insisto.')
        return None
    agent = get_prospector_agent()
    respuesta = agent.generar_respuesta_autoreply(historial, None)
    if not respuesta:
        respuesta = ("Jaja veo que tienen el asistente automático 🙌 Cuando me lea alguien "
                     "del equipo: con Appo sus clientes agendan solos 24/7 y dejan de perder "
                     "citas. ¿Les muestro en 1 minutico cómo funciona?")
    MensajeWhatsApp.objects.using('leads_db').create(
        chat=chat, message_key=f'out_{remote_jid}_{uuid.uuid4().hex[:12]}',
        message_text=respuesta + _AUTOREPLY_MARKER, from_me=True, timestamp=timezone.now())
    return respuesta

def procesar_mensaje_whatsapp(remote_jid: str, mensaje_cliente: str, phone: str = None) -> str:
    """Procesa un mensaje de WhatsApp para un número no registrado como lead.
    Guarda el historial de conversación en MensajeWhatsApp para mantener contexto."""
    from leads_admin.models import ChatWhatsApp, MensajeWhatsApp
    from django.utils import timezone

    # Obtener o crear chat
    chat, _ = ChatWhatsApp.objects.using('leads_db').get_or_create(
        chat_id=remote_jid,
        defaults={'phone': phone or '', 'contact_name': ''}
    )

    # Guardar mensaje entrante del lead
    import uuid
    MensajeWhatsApp.objects.using('leads_db').create(
        chat=chat,
        message_key=f'in_{remote_jid}_{uuid.uuid4().hex[:12]}',
        message_text=mensaje_cliente,
        from_me=False,
        timestamp=timezone.now()
    )

    agent = get_prospector_agent()

    # Recuperar historial (incluye el que acabamos de guardar)
    historial_mensajes = MensajeWhatsApp.objects.using('leads_db').filter(
        chat__chat_id=remote_jid
    ).order_by('timestamp')[:20]

    historial_conversacion = []
    for msg in historial_mensajes:
        role = "assistant" if msg.from_me else "user"
        historial_conversacion.append({
            "role": role,
            "content": msg.message_text or "",
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else ""
        })

    logger.info(f'[PROCESAR_WHATSAPP] Historial para {remote_jid}: {len(historial_conversacion)} mensajes')

    respuesta = agent.generar_respuesta(historial_conversacion, mensaje_cliente)

    if respuesta:
        logger.info(f'[PROCESAR_WHATSAPP] Respuesta generada para {remote_jid}: {respuesta[:100]}...')
        # Guardar respuesta saliente en el historial
        MensajeWhatsApp.objects.using('leads_db').create(
            chat=chat,
            message_key=f'out_{remote_jid}_{uuid.uuid4().hex[:12]}',
            message_text=respuesta,
            from_me=True,
            timestamp=timezone.now()
        )
        return respuesta
    else:
        # Lead inbound (suele venir de publicidad, viene caliente): engancha de una.
        fallback = ("¡Hola! 👋 Soy Juan, qué bueno que escribiste. Con Appo tus clientes "
                    "agendan solos 24/7 y les llega recordatorio antes de la cita. "
                    "¿Tienes barbería o peluquería?")
        logger.warning(f'[PROCESAR_WHATSAPP] Fallback usado para {remote_jid}')
        # Guardar fallback en el historial también
        MensajeWhatsApp.objects.using('leads_db').create(
            chat=chat,
            message_key=f'out_{remote_jid}_{uuid.uuid4().hex[:12]}',
            message_text=fallback,
            from_me=True,
            timestamp=timezone.now()
        )
        return fallback


# Instancia global (singleton)
_agent_instance = None

def get_prospector_agent() -> ProspectorAgent:
    """Obtener instancia única del agente."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ProspectorAgent()
    return _agent_instance
