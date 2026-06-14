module.exports = {
  apps: [{
    name: 'whatsapp-crm',
    script: 'index.js',
    cwd: '/var/www/appo.com.co/whatsapp-service',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    env: {
      NODE_ENV: 'production'
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    error_file: 'logs/error.log',
    out_file: 'logs/out.log',
    combine_logs: true,
    time: true
  }]
};