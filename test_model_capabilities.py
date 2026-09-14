from unittest.mock import Mock,patch
import pytest
from core.model_capabilities import inspect_ollama_model,require_capability,ollama_catalog
from spellbook import llm_client


def response(data):
    result=Mock()
    result.json.return_value=data
    return result


def test_name_is_not_vision_evidence():
    with patch('core.model_capabilities.requests.post',return_value=response({'capabilities':['completion']})):
        with pytest.raises(ValueError,match='no verified vision'):
            require_capability({'provider':'ollama','model':'vision-super-model'},{'ollama_url':'unused'},'vision')


def test_missing_metadata_is_unknown():
    with patch('core.model_capabilities.requests.post',return_value=response({})):
        assert inspect_ollama_model('unused','model')['status']=='unknown'


def test_catalog_recommends_smallest_verified_vision_model():
    models=[{'name':'large','size':100},{'name':'small','size':10},{'name':'text','size':1}]
    def inspect(endpoint,model):
        return {'model':model,'capabilities':['vision'] if model!='text' else ['completion'],'status':'verified'}
    with patch('core.model_capabilities.requests.get',return_value=response({'models':models})),patch('core.model_capabilities.inspect_ollama_model',side_effect=inspect):
        assert ollama_catalog('unused')['recommended_vision_model']=='small'


def test_incapable_fallback_never_receives_image():
    settings={'timeout':1,'ollama_url':'unused','lmstudio_url':'other'}
    route={'provider':'ollama','model':'vision','fallback':{'provider':'lmstudio','model':'text'}}
    with patch.object(llm_client,'get_backend_settings',return_value=settings),patch.object(llm_client,'resolve_route',return_value=route),patch('core.model_capabilities.inspect_ollama_model',return_value={'status':'verified','capabilities':['vision']}),patch.object(llm_client,'_ollama_chat',side_effect=RuntimeError('offline')),patch.object(llm_client,'_openai_chat') as fallback:
        with pytest.raises(llm_client.ModelConnectionError):
            llm_client.chat('describe',images=['synthetic'],required_capability='vision')
    fallback.assert_not_called()
