import os
import requests
from dotenv import load_dotenv

load_dotenv('/var/www/appo.com.co/.env')
api_key = os.getenv('OPENROUTER_API_KEY')
if not api_key:
    print("OPENROUTER_API_KEY no encontrada")
    exit(1)

url = "https://openrouter.ai/api/v1/models"
headers = {
    "Authorization": f"Bearer {api_key}"
}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        models = response.json().get('data', [])
        print(f"Total modelos: {len(models)}")
        # Filtrar gratuitos
        free_models = [m for m in models if m.get('pricing', {}).get('prompt') == '0']
        print(f"Modelos gratuitos: {len(free_models)}")
        for m in free_models[:10]:
            print(f"  - {m['id']} (contexto: {m.get('context_length', 'N/A')})")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"Excepción: {e}")