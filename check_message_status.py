import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv('/var/www/appo.com.co/.env')

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
message_sid = 'MMed36fb86701e25f018b860cfe2c0e898'

client = Client(account_sid, auth_token)
message = client.messages(message_sid).fetch()
print(f"Estado: {message.status}")
print(f"Fecha creación: {message.date_created}")
print(f"Fecha actualizada: {message.date_updated}")
print(f"Destino: {message.to}")
print(f"Desde: {message.from_}")
print(f"Cuerpo: {message.body}")