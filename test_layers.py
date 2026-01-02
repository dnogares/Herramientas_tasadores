import requests

try:
    response = requests.get('http://127.0.0.1:8081/api/layers/info', timeout=30)
    print(f'Status: {response.status_code}')
    if response.status_code == 200:
        data = response.json()
        print(f'Total capas: {data.get("layers", {}).get("total_capas", 0)}')
        for nombre, info in data.get('layers', {}).get('capas', {}).items():
            print(f'  - {nombre}: {info["nombre"]}')
    else:
        print(f'Error: {response.text}')
except Exception as e:
    print(f'Error: {e}')
