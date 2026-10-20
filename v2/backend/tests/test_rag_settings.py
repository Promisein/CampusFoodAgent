import pytest


def test_local_key_env_priority_and_secret_redaction(tmp_path):
    from app.rag.settings import load_settings
    path=tmp_path/'.env'
    path.write_text('DEEPSEEK_API_KEY="local-private-key"\nDEEPSEEK_MODEL=deepseek-flash\n',encoding='utf-8')
    settings=load_settings(path,environ={})
    assert settings.api_key=='local-private-key'
    assert 'local-private-key' not in repr(settings)
    assert 'local-private-key' not in str(settings.public_status())
    assert settings.public_status()['configured']
    assert load_settings(path,environ={'DEEPSEEK_API_KEY':''}).api_key==''
    assert load_settings(path,environ={'DEEPSEEK_API_KEY':'override'}).api_key=='override'


@pytest.mark.parametrize('line',['RAG_TIMEOUT_SECONDS=nan','RAG_TIMEOUT_SECONDS=0','DEEPSEEK_BASE_URL=http://api.deepseek.com','DEEPSEEK_BASE_URL=https://foreign.example','RAG_ENABLED=maybe','RAG_MAX_CONTEXT_CHARS=1'])
def test_invalid_settings_fail_without_echoing_values(tmp_path,line):
    from app.rag.settings import load_settings
    path=tmp_path/'.env';path.write_text(line+'\nDEEPSEEK_API_KEY=sensitive')
    with pytest.raises(ValueError) as error:load_settings(path,environ={})
    assert 'sensitive' not in str(error.value)
