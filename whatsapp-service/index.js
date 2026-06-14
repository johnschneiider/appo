const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const qrcodeLib = require('qrcode');
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const winston = require('winston');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

// Configuración
const PORT = process.env.PORT || 8081;
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'https://appo.com.co/leads/webhook/';
const INSTANCE_NAME = process.env.INSTANCE_NAME || 'APPO_CRM';
const API_KEY = process.env.API_KEY || 'OWEN_STRATEGIC_KEY_2026_COL';

// Función para limpiar procesos de navegador colgados
function cleanupBrowserProcesses() {
  const sessionPath = path.resolve('./.wwebjs_auth/whatsapp/session-' + INSTANCE_NAME);
  logger.info(`Limpiando procesos de navegador para sesión: ${sessionPath}`);
  
  try {
    // Buscar procesos Chrome/Chromium con este userDataDir
    const { execSync } = require('child_process');
    execSync(`pkill -f "${sessionPath}" 2>/dev/null || true`, { stdio: 'inherit' });
    execSync('pkill -f "chrome.*--remote-debugging-port" 2>/dev/null || true', { stdio: 'inherit' });
    execSync('pkill -f "chromium.*--remote-debugging-port" 2>/dev/null || true', { stdio: 'inherit' });
    logger.info('Procesos de navegador limpiados');
  } catch (error) {
    logger.warn(`Error al limpiar procesos: ${error.message}`);
  }
}

// Logger
const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.printf(({ timestamp, level, message }) => {
      return `${timestamp} [${level.toUpperCase()}] ${message}`;
    })
  ),
  transports: [
    new winston.transports.Console(),
    new winston.transports.File({ filename: 'whatsapp-service.log' })
  ]
});

// Express app
const app = express();
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// Estado de la instancia
let client = null;
let qrCode = null;
let connectionState = 'disconnected';
let userInfo = null;
let initializing = false;
let initializationAttempts = 0;
let allowReconnect = true;
let reconnectTimeout = null;

// Protección anti-bloqueo WhatsApp
let connectionTimestamp = null; // Timestamp cuando se conectó
let lastMessageSentAt = 0;     // Timestamp del último mensaje enviado
const RATE_LIMIT_MS = 5000;    // 1 mensaje cada 5 segundos
const SAFE_START_MS = 0; // Desactivado para pruebas (original: 30 * 60 * 1000)
let safeStartActive = false;    // Safe‑start desactivado

// Función para reconexión con delay y limpieza
function reconnectWithDelay(delayMs = 10000, reason = 'unknown') {
  // Cancelar reconexión previa
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
  }
  
  // Si no se permite reconexión, salir
  if (!allowReconnect) {
    logger.info(`Reconexión bloqueada (allowReconnect=false) por razón: ${reason}`);
    return;
  }
  
  logger.info(`Programando reconexión en ${delayMs}ms (${reason})`);
  
  // Limpiar procesos colgados antes de reintentar
  cleanupBrowserProcesses();
  
  reconnectTimeout = setTimeout(() => {
    reconnectTimeout = null;
    if (connectionState !== 'open' && !initializing && allowReconnect) {
      logger.info('Iniciando reconexión programada...');
      initializing = false;
      initializeClient();
    } else {
      logger.info('Estado ya conectado o inicializando, omitiendo reconexión');
    }
  }, delayMs);
}

// Cancelar cualquier reconexión programada
function cancelReconnect() {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
    logger.info('Reconexión programada cancelada');
  }
}

// Limpiar sesión tras LOGOUT
async function cleanupOnLogout() {
  logger.info('LOGOUT detectado, limpiando sesión...');
  
  // Cancelar reconexiones
  cancelReconnect();
  allowReconnect = false;
  
  // Destruir cliente si existe
  if (client) {
    try {
      await client.destroy();
      logger.info('Cliente WhatsApp destruido');
    } catch (err) {
      logger.warn(`Error destruyendo cliente: ${err.message}`);
    }
    client = null;
  }
  
  // Eliminar carpeta de sesión
  const sessionPath = './.wwebjs_auth/whatsapp/session-' + INSTANCE_NAME;
  try {
    if (fs.existsSync(sessionPath)) {
      fs.rmSync(sessionPath, { recursive: true, force: true });
      logger.info(`Sesión eliminada: ${sessionPath}`);
    }
  } catch (err) {
    logger.warn(`Error eliminando sesión: ${err.message}`);
  }
  
  // Resetear estado
  qrCode = null;
  connectionState = 'disconnected';
  userInfo = null;
  initializing = false;
  initializationAttempts = 0;
  safeStartActive = false;
  connectionTimestamp = null;
  
  // Permitir que el usuario vuelva a vincular (generar nuevo QR)
  // No reintentar reconexión automática
  logger.info('Sesión limpiada. Esperando nuevo escaneo de QR.');
}

// Inicializar cliente WhatsApp
function initializeClient() {
  if (initializing) {
    logger.warn('Inicialización ya en curso, ignorando llamada duplicada');
    return;
  }
  
  initializing = true;
  initializationAttempts++;
  logger.info(`Inicializando cliente WhatsApp para instancia: ${INSTANCE_NAME} (intento ${initializationAttempts})`);
  
  // Limpiar procesos de navegador colgados
  cleanupBrowserProcesses();
  
  // Opciones de Puppeteer mejoradas
  const puppeteerOptions = {
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-accelerated-2d-canvas',
      '--no-first-run',
      '--no-zygote',
      '--disable-gpu',
      '--disable-extensions',
      '--disable-background-networking',
      '--disable-sync',
      '--disable-default-apps',
      '--disable-background-timer-throttling',
      '--disable-renderer-backgrounding',
      '--disable-backgrounding-occluded-windows',
      '--disable-breakpad',
      '--disable-client-side-phishing-detection',
      '--disable-component-update',
      '--disable-domain-reliability',
      '--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process',
      '--disable-hang-monitor',
      '--disable-ipc-flooding-protection',
      '--disable-notifications',
      '--disable-popup-blocking',
      '--disable-prompt-on-repost',
      '--disable-web-security',
      '--metrics-recording-only',
      '--mute-audio',
      '--no-default-browser-check',
      '--safebrowsing-disable-auto-update',
      '--use-mock-keychain',
      '--window-size=1280,720'
    ],
    executablePath: '/usr/bin/google-chrome-stable',
    ignoreDefaultArgs: ['--enable-automation'],
    handleSIGINT: true,
    handleSIGTERM: true,
    handleSIGHUP: true
  };
  
  client = new Client({
    authStrategy: new LocalAuth({ clientId: INSTANCE_NAME, dataPath: './.wwebjs_auth/whatsapp' }),
    puppeteer: puppeteerOptions,
    webVersionCache: {
      type: 'remote',
      remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.2412.54.html'
    }
  });

  // Evento QR
  client.on('qr', async (qr) => {
    qrCode = qr;
    logger.info('QR recibido, escanea con WhatsApp');
    qrcode.generate(qr, { small: true });
    
    // Generar base64 real de la imagen QR
    let qrBase64 = '';
    try {
      qrBase64 = await qrcodeLib.toDataURL(qr);
    } catch (err) {
      logger.error(`Error generando QR base64: ${err.message}`);
      qrBase64 = `data:image/png;base64,${Buffer.from(qr).toString('base64')}`;
    }
    
    // Opcional: enviar webhook de QR (similar a Evolution)
    sendWebhook({
      event: 'qr',
      instance: INSTANCE_NAME,
      qr: qr,
      base64: qrBase64
    });
  });

  // Evento ready
  client.on('ready', () => {
    initializing = false;
    initializationAttempts = 0;
    allowReconnect = true;
    connectionState = 'open';
    connectionTimestamp = Date.now();
    safeStartActive = SAFE_START_MS > 0; // Solo activar si hay periodo de gracia
    logger.info('Cliente WhatsApp listo');
    if (safeStartActive) {
      logger.warn('MODO SEGURO ACTIVADO: No se enviarán respuestas automáticas durante los primeros 30 minutos');
    } else {
      logger.info('Safe‑start desactivado (SAFE_START_MS = 0)');
    }
    
    // Obtener información del usuario
    userInfo = client.info;
    logger.info(`Conectado como: ${userInfo.pushname || userInfo.wid.user}`);
    
    sendWebhook({
      event: 'CONNECTION_UPDATE',
      instance: INSTANCE_NAME,
      state: 'open',
      status: 'connected',
      user: userInfo,
      safeStartActive: safeStartActive
    });
  });

  // Evento de mensaje
  client.on('message', async (msg) => {
    // IGNORAR mensajes propios (fromMe) — no deben disparar el webhook
    // EXCEPCIÓN: permitir mensajes del propio número para pruebas del admin
    const OWN_NUMBER = userInfo?.wid?.user || '';
    const isOwnNumber = msg.from.includes(OWN_NUMBER) && OWN_NUMBER !== '';
    if (msg.fromMe && !isOwnNumber) {
      logger.info(`Mensaje propio ignorado (fromMe=true): ${msg.from.substring(0, 20)}...`);
      return;
    }
    if (msg.fromMe && isOwnNumber) {
      logger.info(`Mensaje del admin desde su propio número — permitido para testing`);
    }
    
    logger.info(`Mensaje recibido de ${msg.from}: ${msg.body?.substring(0, 50) || '[sin texto]'}...`);
    
    // Detectar tipo de mensaje para media (audio, imagen, video, sticker, documento)
    let mediaType = null;
    let mediaCaption = '';
    if (msg.hasMedia) {
      mediaType = msg.type;  // 'ptt'=nota de voz, 'audio', 'image', 'video', 'sticker', 'document'
      mediaCaption = msg.body || '';
      logger.info(`Media detectado: tipo=${mediaType}, caption="${mediaCaption?.substring(0, 50)}", from=${msg.from}`);
      
      // Para notas de voz: loggear duración si está disponible
      if (mediaType === 'ptt' || mediaType === 'audio') {
        const duration = msg._data?.duration || 'desconocida';
        logger.info(`Audio/nota de voz recibida. Duración: ${duration}s`);
      }
    }
    
    // Determinar sender real (para grupos)
    const senderJid = msg.author || msg.from;
    const isGroup = msg.from.endsWith('@g.us');
    
    // Resolver @lid → número real usando el contacto de WhatsApp
    let resolvedPhone = null;
    let resolvedJid = senderJid;
    if (senderJid.endsWith('@lid')) {
      try {
        const contact = await msg.getContact();
        if (contact) {
          // El contacto puede tener number o id._serialized con formato @c.us
          const contactNumber = contact.number || (contact.id?._serialized || '').replace('@c.us', '');
          if (contactNumber && /^\d+$/.test(contactNumber)) {
            resolvedPhone = contactNumber;
            resolvedJid = contact.id?._serialized || senderJid;
            logger.info(`LID resuelto: ${senderJid} → tel=${resolvedPhone}, jid=${resolvedJid}`);
          }
        }
      } catch (err) {
        logger.warn(`No se pudo resolver LID ${senderJid}: ${err.message}`);
      }
    }
    
    // Enviar webhook compatible con Evolution API MESSAGES_UPSERT
    const webhookPayload = {
      event: 'MESSAGES_UPSERT',
      instance: INSTANCE_NAME,
      sender: senderJid,  // JID real del remitente
      resolvedPhone: resolvedPhone,  // Número real si se pudo resolver @lid
      resolvedJid: resolvedJid,      // JID resuelto (@c.us o @lid)
      hasMedia: !!mediaType,         // Flag para detectar media en el webhook
      mediaType: mediaType,          // 'ptt', 'audio', 'image', 'video', 'sticker', 'document' o null
      mediaCaption: mediaCaption,    // Texto que acompaña al media (si hay)
      data: {
        key: {
          remoteJid: msg.from,
          fromMe: msg.fromMe,
          id: msg.id.id
        },
        message: {
          conversation: msg.body || (mediaType ? `[${mediaType}]` : ''),
          extendedTextMessage: msg.body ? { text: msg.body } : undefined
        },
        messageTimestamp: msg.timestamp,
        pushName: msg._data?.pushName || msg.notify || 'Unknown',
        broadcast: msg.isBroadcast || false,
        status: 'received'
      }
    };
    
    sendWebhook(webhookPayload);
  });

  // Evento de cambio de conexión
  client.on('auth_failure', (error) => {
    initializing = false;
    connectionState = 'failed';
    logger.error(`Error de autenticación: ${error}`);
    sendWebhook({
      event: 'CONNECTION_UPDATE',
      instance: INSTANCE_NAME,
      state: 'failed',
      status: 'disconnected',
      error: error.message
    });
    
    // Reconectar después de delay progresivo
    const delay = Math.min(initializationAttempts * 10000, 60000); // Máximo 1 minuto
    reconnectWithDelay(delay, 'auth_failure');
  });

  client.on('disconnected', (reason) => {
    initializing = false;
    connectionState = 'disconnected';
    logger.warn(`Desconectado: ${reason}`);
    sendWebhook({
      event: 'CONNECTION_UPDATE',
      instance: INSTANCE_NAME,
      state: 'disconnected',
      status: 'disconnected',
      reason: reason
    });
    
    // Manejar LOGOUT: limpiar sesión y no reconectar automáticamente
    if (reason === 'LOGOUT') {
      logger.info('LOGOUT detectado. Limpiando sesión y deteniendo reconexión automática.');
      cleanupOnLogout();
      // Inicializar cliente para generar nuevo QR después de limpieza
      setTimeout(() => {
        if (!client) {
          allowReconnect = false; // Asegurar que no se reconecte automáticamente
          initializeClient();
        }
      }, 2000);
    } else {
      // Otras desconexiones (red, error): reconectar después de delay
      allowReconnect = true;
      reconnectWithDelay(10000, 'disconnected');
    }
  });

  // Inicializar cliente con manejo de errores
  try {
    client.initialize();
  } catch (error) {
    initializing = false;
    logger.error(`Error al inicializar cliente: ${error.message}`);
    
    // Si es error de navegador ya corriendo, limpiar y reintentar
    if (error.message.includes('already running') || error.message.includes('userDataDir')) {
      logger.warn('Navegador ya corriendo, limpiando y reintentando...');
      cleanupBrowserProcesses();
      reconnectWithDelay(5000, 'browser_already_running');
    } else {
      // Error genérico, reintentar con delay progresivo
      const delay = Math.min(initializationAttempts * 5000, 30000);
      reconnectWithDelay(delay, 'initialization_error');
    }
  }
}

// Función para enviar webhook
async function sendWebhook(payload) {
  if (!WEBHOOK_URL || WEBHOOK_URL === '') {
    return;
  }
  
  try {
    const headers = {
      'Content-Type': 'application/json',
      'apikey': API_KEY,
      'X-Webhook-Event': payload.event || '',
      'X-Instance-Id': INSTANCE_NAME,
      'X-Timestamp': new Date().toISOString()
    };
    
    const response = await fetch(WEBHOOK_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      logger.warn(`Webhook falló: ${response.status} ${response.statusText}`);
    } else {
      logger.debug('Webhook enviado exitosamente');
    }
  } catch (error) {
    logger.error(`Error enviando webhook: ${error.message}`);
  }
}

// Endpoints de API REST

// 1. Estado de conexión
app.get('/instance/connectionState/:instanceName', (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({
      status: 404,
      error: 'Instance not found',
      response: { message: 'Instance not found' }
    });
  }
  
  res.json({
    instance: {
      instanceName: INSTANCE_NAME,
      state: connectionState
    }
  });
});

// 2. Enviar mensaje de texto
app.post('/message/sendText/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const { number, textMessage } = req.body;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({
      status: 404,
      error: 'Instance not found',
      response: { message: 'Instance not found' }
    });
  }
  
  if (!number || !textMessage?.text) {
    return res.status(400).json({
      status: 400,
      error: 'Bad Request',
      response: { message: 'Missing number or textMessage.text' }
    });
  }
  
  if (connectionState !== 'open' || !client) {
    return res.status(500).json({
      status: 500,
      error: 'Service Unavailable',
      response: { message: 'WhatsApp client not ready' }
    });
  }
  
  // Protección anti-bloqueo: verificar safe start
  const now = Date.now();
  
  // 1. Verificar si estamos en periodo de gracia (primeros 30 minutos)
  if (connectionTimestamp && safeStartActive) {
    const timeConnected = now - connectionTimestamp;
    if (timeConnected < SAFE_START_MS) {
      logger.warn(`Intento de envío bloqueado: número nuevo está en periodo de gracia (${Math.round(timeConnected/1000)}s < 30m)`);
      return res.status(429).json({
        status: 429,
        error: 'Too Early',
        response: { message: 'Number is in safe-start period (first 30 minutes). No automated messages allowed.' }
      });
    } else {
      // Desactivar safe start después de 30 minutos
      safeStartActive = false;
      logger.info('Periodo de gracia finalizado, envíos automáticos habilitados');
    }
  }
  
  // 2. Rate limiting: mínimo 5 segundos entre mensajes
  const timeSinceLastMessage = now - lastMessageSentAt;
  if (timeSinceLastMessage < RATE_LIMIT_MS) {
    const waitMs = RATE_LIMIT_MS - timeSinceLastMessage;
    logger.warn(`Rate limiting activado: esperar ${Math.ceil(waitMs/1000)}s antes de enviar`);
    return res.status(429).json({
      status: 429,
      error: 'Too Many Requests',
      response: { message: `Rate limit exceeded. Wait ${Math.ceil(waitMs/1000)} seconds.` }
    });
  }
  
  // 3. Validar que no sea un mensaje automático (detectar patrones)
  const messageText = textMessage.text || '';
  const isAutoReply = messageText.includes('👋') || 
                     messageText.includes('Hola, soy') || 
                     messageText.toLowerCase().includes('gracias por contactar') ||
                     messageText.toLowerCase().includes('buenos días') ||
                     messageText.toLowerCase().includes('buenas tardes') ||
                     messageText.toLowerCase().includes('buenas noches');
  
  if (isAutoReply && safeStartActive) {
    logger.warn('Mensaje automático bloqueado durante periodo de gracia');
    return res.status(429).json({
      status: 429,
      error: 'Auto-reply Blocked',
      response: { message: 'Auto-replies are blocked during safe-start period' }
    });
  }
  
  try {
    // Normalizar número: quitar prefijos/sufijos, limpiar caracteres
    let rawNumber = number.replace(/@.*$/, '').replace(/[+\s-]/g, '');
    // Asegurar código de país Colombia
    if (rawNumber.length === 10) rawNumber = '57' + rawNumber;
    if (!rawNumber.startsWith('57')) rawNumber = '57' + rawNumber;
    
    logger.info(`Enviando mensaje a ${rawNumber}: ${textMessage.text.substring(0, 50)}...`);
    
    // Estrategia multi-formato para números fríos:
    // 1. Intentar getNumberId con @c.us (el más común)
    // 2. Si falla, intentar @s.whatsapp.net (más universal)
    // 3. Si falla, intentar @lid (para números nunca contactados)
    
    const formats = [
      `${rawNumber}@c.us`,
      `${rawNumber}@s.whatsapp.net`,
      `${rawNumber}@lid`,
    ];
    
    let sent = false;
    let response = null;
    let lastError = null;
    
    for (const formatNumber of formats) {
      try {
        // Verificar si el número existe en WhatsApp
        let numberId = null;
        try {
          numberId = await client.getNumberId(formatNumber);
        } catch (err) {
          logger.debug(`getNumberId falló para ${formatNumber}: ${err.message}`);
        }
        
        const targetNumber = numberId ? numberId._serialized : formatNumber;
        logger.info(`  Intentando formato ${targetNumber}...`);
        
        response = await client.sendMessage(targetNumber, textMessage.text);
        sent = true;
        logger.info(`  ✅ Enviado exitosamente con formato ${targetNumber}`);
        break;
      } catch (err) {
        lastError = err;
        logger.warn(`  ⚠️ Formato ${formatNumber} falló: ${err.message}`);
        // Si no es error LID, no seguir intentando
        if (!err.message.includes('LID') && !err.message.includes('not found')) {
          break;
        }
      }
    }
    
    if (!sent) {
      throw lastError || new Error('Todos los formatos fallaron');
    }
    
    // Respuesta similar a Evolution API
    const evolutionResponse = {
      key: {
        remoteJid: response?.key?.remoteJid || rawNumber,
        fromMe: true,
        id: response?.key?.id || Date.now().toString(16)
      },
      message: {
        extendedTextMessage: {
          text: textMessage.text
        }
      },
      messageTimestamp: Math.floor(Date.now() / 1000),
      status: 'PENDING'
    };
    
    // Actualizar timestamp del último mensaje enviado
    lastMessageSentAt = Date.now();
    logger.info(`Mensaje enviado con ID: ${evolutionResponse.key.id} (rate limit reset)`);
    
    res.json(evolutionResponse);
  } catch (error) {
    logger.error(`Error enviando mensaje: ${error.message}`);
    res.status(500).json({
      status: 500,
      error: 'Internal Server Error',
      response: { message: error.message }
    });
  }
});

// 2b. Enviar media (imagen, video, audio, documento)
app.post('/message/sendMedia/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const { number, mediaMessage } = req.body;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({
      status: 404, error: 'Instance not found',
      response: { message: 'Instance not found' }
    });
  }
  
  if (!number || !mediaMessage?.media || !mediaMessage?.mediatype) {
    return res.status(400).json({
      status: 400, error: 'Bad Request',
      response: { message: 'Missing number, mediaMessage.media or mediaMessage.mediatype' }
    });
  }
  
  if (connectionState !== 'open' || !client) {
    return res.status(500).json({
      status: 500, error: 'Service Unavailable',
      response: { message: 'WhatsApp client not ready' }
    });
  }
  
  // Rate limiting
  const now = Date.now();
  const timeSinceLastMessage = now - lastMessageSentAt;
  if (timeSinceLastMessage < RATE_LIMIT_MS) {
    const waitMs = RATE_LIMIT_MS - timeSinceLastMessage;
    return res.status(429).json({
      status: 429, error: 'Too Many Requests',
      response: { message: `Rate limit exceeded. Wait ${Math.ceil(waitMs/1000)} seconds.` }
    });
  }
  
  try {
    // Normalizar número
    let rawNumber = number.replace(/@.*$/, '').replace(/[+\s-]/g, '');
    if (rawNumber.length === 10) rawNumber = '57' + rawNumber;
    if (!rawNumber.startsWith('57')) rawNumber = '57' + rawNumber;
    
    // Crear objeto MessageMedia desde URL (o base64)
    const mediaUrl = mediaMessage.media;
    let media;
    try {
      if (mediaUrl.startsWith('data:')) {
        // Base64 inline: extraer MIME type y datos
        const matches = mediaUrl.match(/^data:([^;]+);base64,(.+)$/);
        if (matches) {
          media = new MessageMedia(matches[1], matches[2]);
        } else {
          throw new Error('Formato base64 inválido');
        }
      } else {
        // URL: descargar
        logger.info(`Descargando media desde URL: ${mediaUrl.substring(0, 80)}...`);
        media = await MessageMedia.fromUrl(mediaUrl, { unsafeMime: true });
      }
    } catch (mediaErr) {
      logger.error(`Error creando MessageMedia: ${mediaErr.message}`);
      throw new Error(`No se pudo cargar el media: ${mediaErr.message}`);
    }
    
    // Estrategia multi-formato (misma que sendText)
    const formats = [`${rawNumber}@c.us`, `${rawNumber}@s.whatsapp.net`, `${rawNumber}@lid`];
    let sent = false, response = null, lastError = null;
    const caption = mediaMessage.caption || '';
    
    for (const formatNumber of formats) {
      try {
        let numberId = null;
        try { numberId = await client.getNumberId(formatNumber); } catch (err) {}
        const targetNumber = numberId ? numberId._serialized : formatNumber;
        response = await client.sendMessage(targetNumber, media, { caption });
        sent = true;
        break;
      } catch (err) {
        lastError = err;
        if (!err.message.includes('LID') && !err.message.includes('not found')) break;
      }
    }
    if (!sent) throw lastError || new Error('Todos los formatos fallaron');
    
    lastMessageSentAt = Date.now();
    logger.info(`Media enviado a ${rawNumber}: ${mediaMessage.mediatype}`);
    
    res.json({
      key: {
        remoteJid: response?.key?.remoteJid || rawNumber,
        fromMe: true,
        id: response?.key?.id || Date.now().toString(16)
      },
      message: { imageMessage: { url: mediaMessage.media, caption: caption } },
      messageTimestamp: Math.floor(Date.now() / 1000),
      status: 'PENDING'
    });
  } catch (error) {
    logger.error(`Error enviando media: ${error.message}`);
    res.status(500).json({
      status: 500, error: 'Internal Server Error',
      response: { message: error.message }
    });
  }
});

// 3. Obtener QR code (base64 o terminal)
app.get('/instance/qr/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({ error: 'Instance not found' });
  }
  
  if (!qrCode) {
    return res.status(404).json({ error: 'QR not available yet' });
  }
  
  // Generar imagen base64 real del QR
  try {
    const qrBase64 = await qrcodeLib.toDataURL(qrCode);
    res.json({
      qr: qrCode,
      qrBase64: qrBase64,
      instance: INSTANCE_NAME,
      status: 'waiting'
    });
  } catch (error) {
    logger.error(`Error generando QR base64: ${error.message}`);
    // Fallback al raw QR
    res.json({
      qr: qrCode,
      instance: INSTANCE_NAME,
      status: 'waiting',
      warning: 'base64 generation failed'
    });
  }
});

// 3b. Obtener QR como imagen PNG (igual que Evolution API)
app.get('/instance/qrBase64/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({ error: 'Instance not found' });
  }
  
  if (!qrCode) {
    return res.status(404).json({ error: 'QR not available yet' });
  }
  
  try {
    const qrBase64 = await qrcodeLib.toDataURL(qrCode);
    // Devolver solo la parte base64 (sin data:image/png;base64,)
    const base64Data = qrBase64.replace('data:image/png;base64,', '');
    
    res.json({
      instance: INSTANCE_NAME,
      status: 'waiting',
      qr: base64Data,
      count: 1,
      pairingCode: null
    });
  } catch (error) {
    logger.error(`Error generando QR base64: ${error.message}`);
    res.status(500).json({ error: 'QR generation failed' });
  }
});

// 3c. Obtener QR como imagen PNG binaria (para <img src="...">)
app.get('/instance/qrImage/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).send('Instance not found');
  }
  
  if (!qrCode) {
    return res.status(404).send('QR not available yet');
  }
  
  try {
    const qrBuffer = await qrcodeLib.toBuffer(qrCode, {
      type: 'png',
      width: 300,
      margin: 1
    });
    
    res.set('Content-Type', 'image/png');
    res.set('Cache-Control', 'no-cache');
    res.send(qrBuffer);
  } catch (error) {
    logger.error(`Error generando QR image: ${error.message}`);
    res.status(500).send('QR generation failed');
  }
});

// 4. Health check
app.get('/health', (req, res) => {
  // Calcular tiempo restante de safe start
  let safeStartRemaining = null;
  if (connectionTimestamp && safeStartActive) {
    const timeConnected = Date.now() - connectionTimestamp;
    if (timeConnected < SAFE_START_MS) {
      safeStartRemaining = Math.max(0, SAFE_START_MS - timeConnected);
    }
  }
  
  res.json({
    status: 'ok',
    instance: INSTANCE_NAME,
    connectionState: connectionState,
    safeStartActive: safeStartActive,
    safeStartRemainingMs: safeStartRemaining,
    safeStartRemainingMinutes: safeStartRemaining ? Math.ceil(safeStartRemaining / (60 * 1000)) : 0,
    rateLimitMs: RATE_LIMIT_MS,
    timestamp: new Date().toISOString()
  });
});

// 4.5 Validar número WhatsApp (check if registered)
app.post('/number/check/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const { number } = req.body || {};
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({ error: 'Instance not found' });
  }
  
  if (!number) {
    return res.status(400).json({ error: 'Missing number' });
  }
  
  if (!client || connectionState !== 'open') {
    return res.status(503).json({ error: 'WhatsApp client not ready', connectionState });
  }
  
  try {
    // Limpiar formato: siempre @c.us para validar
    let cleanNumber = number.replace(/[@+\s]/g, '');
    if (cleanNumber.startsWith('57')) {
      cleanNumber = cleanNumber + '@c.us';
    } else {
      cleanNumber = '57' + cleanNumber + '@c.us';
    }
    
    const numberId = await client.getNumberId(cleanNumber);
    if (numberId) {
      logger.info(`Validación: ${cleanNumber} → registrado (${numberId._serialized})`);
      res.json({
        success: true,
        registered: true,
        number: cleanNumber,
        serialized: numberId._serialized
      });
    } else {
      logger.info(`Validación: ${cleanNumber} → NO registrado`);
      res.json({
        success: true,
        registered: false,
        number: cleanNumber
      });
    }
  } catch (err) {
    logger.warn(`Error validando ${number}: ${err.message}`);
    res.json({
      success: true,
      registered: false,
      number: number,
      error: err.message
    });
  }
});

// 5. Reiniciar instancia
app.post('/instance/restart/:instanceName', (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({ error: 'Instance not found' });
  }
  
  if (client) {
    client.destroy();
    connectionState = 'disconnected';
    setTimeout(() => {
      initializeClient();
    }, 2000);
  }
  
  res.json({ success: true, message: 'Restarting WhatsApp client' });
});

// 6. Cerrar sesión
app.delete('/instance/logout/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  
  if (instanceName !== INSTANCE_NAME) {
    return res.status(404).json({ error: 'Instance not found' });
  }
  
  if (client) {
    await client.destroy();
    connectionState = 'disconnected';
    qrCode = null;
    userInfo = null;
  }
  
  res.json({ success: true, message: 'Logged out' });
});

// Iniciar servidor
// 7. Resolver LIDs pendientes (debug/recovery)
app.post('/debug/resolve-lids', async (req, res) => {
  const { lids } = req.body || {};
  if (!lids || !Array.isArray(lids)) {
    return res.status(400).json({ error: 'Missing lids array' });
  }
  if (!client || connectionState !== 'open') {
    return res.status(503).json({ error: 'WhatsApp client not ready' });
  }
  
  const results = {};
  for (const lid of lids) {
    try {
      const jid = lid.includes('@') ? lid : `${lid}@lid`;
      const contact = await client.getContactById(jid);
      if (contact) {
        const number = contact.number || (contact.id?._serialized || '').replace('@c.us', '');
        results[lid] = {
          phone: number || null,
          jid: contact.id?._serialized || null,
          name: contact.name || contact.pushname || null
        };
        logger.info(`LID resuelto: ${lid} → ${number || 'sin número'}`);
      } else {
        results[lid] = { phone: null, error: 'not found' };
      }
    } catch (err) {
      results[lid] = { phone: null, error: err.message };
    }
  }
  res.json({ success: true, results });
});

app.listen(PORT, () => {
  logger.info(`WhatsApp CRM Service escuchando en puerto ${PORT}`);
  logger.info(`Instance name: ${INSTANCE_NAME}`);
  logger.info(`Webhook URL: ${WEBHOOK_URL || 'None'}`);
  
  // Inicializar cliente WhatsApp después de que el servidor esté listo
  setTimeout(() => {
    initializeClient();
  }, 1000);
});

// Manejo de señales para shutdown limpio
process.on('SIGINT', async () => {
  logger.info('Recibido SIGINT, cerrando...');
  if (client) {
    await client.destroy();
  }
  process.exit(0);
});

process.on('SIGTERM', async () => {
  logger.info('Recibido SIGTERM, cerrando...');
  if (client) {
    await client.destroy();
  }
  process.exit(0);
});

module.exports = app;