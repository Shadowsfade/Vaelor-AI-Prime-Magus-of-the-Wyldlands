"""Provider-reported capabilities; model names are never capability evidence."""
from concurrent.futures import ThreadPoolExecutor
import requests


def inspect_ollama_model(endpoint, model, timeout=3):
    record={"provider":"ollama","model":model,"capabilities":[],"status":"unknown"}
    try:
        response=requests.post(endpoint.rstrip('/')+'/api/show',json={"model":model},timeout=timeout)
        response.raise_for_status()
        data=response.json()
        capabilities=data.get('capabilities')
        if not isinstance(capabilities,list) or not all(isinstance(value,str) for value in capabilities):
            raise ValueError('Provider did not report capabilities')
        record.update(capabilities=capabilities,status='verified',source='ollama/api/show')
    except (requests.RequestException,ValueError,TypeError,AttributeError) as exc:
        record['error']=str(exc)
    return record


def require_capability(route,settings,capability):
    if route['provider']!='ollama':
        raise ValueError('Capability verification is currently available for Ollama only')
    record=inspect_ollama_model(settings['ollama_url'],route['model'])
    if record['status']!='verified' or capability not in record['capabilities']:
        raise ValueError(f"Model {route['model']} has no verified {capability} capability")
    return record


def ollama_catalog(endpoint):
    response=requests.get(endpoint.rstrip('/')+'/api/tags',timeout=3)
    response.raise_for_status()
    data=response.json()
    models=data.get('models',[])
    if not isinstance(models,list):
        raise ValueError('Invalid model inventory')
    selected=[item for item in models if isinstance(item,dict) and isinstance(item.get('name'),str)][:20]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(lambda item: inspect_ollama_model(endpoint,item['name']),selected))
    for record,item in zip(records,selected):
        size=item.get('size')
        record['size_bytes']=size if isinstance(size,int) and size>0 else None
    records.sort(key=lambda item:(item['size_bytes'] is None,item['size_bytes'] or 0,item['model']))
    vision=[item for item in records if item['status']=='verified' and 'vision' in item['capabilities']]
    return {'models':records,'recommended_vision_model':vision[0]['model'] if vision else None,
            'truncated':len(models)>20,'selection_basis':'smallest installed download size with verified vision capability'}
