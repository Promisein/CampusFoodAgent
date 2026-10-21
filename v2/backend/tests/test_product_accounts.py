import sqlite3

import pytest


def test_account_registration_password_hash_session_and_logout(tmp_path):
    from app.product.accounts import AccountStore,AccountError
    store=AccountStore(tmp_path/'accounts.sqlite3')
    account=store.register('Guest_01','long-password-2026')
    assert account['handle']=='guest_01' and account['id'].startswith('acct_')
    with pytest.raises(AccountError) as duplicate:
        store.register('GUEST_01','another-password-2026')
    assert duplicate.value.status==409
    with sqlite3.connect(tmp_path/'accounts.sqlite3') as db:
        serialized=' '.join(str(part) for row in db.execute('SELECT * FROM accounts') for part in row)
    assert 'long-password-2026' not in serialized
    assert store.authenticate('guest_01','long-password-2026')['id']==account['id']
    token=store.issue_session(account['id'])
    assert store.resolve_session(token)['id']==account['id']
    with sqlite3.connect(tmp_path/'accounts.sqlite3') as db:
        assert token not in ' '.join(str(part) for row in db.execute('SELECT * FROM account_sessions') for part in row)
    assert len(store.csrf_token(token))==64
    store.logout(token)
    assert store.resolve_session(token) is None


def test_login_throttle_expiry_and_conversation_ownership(tmp_path):
    from app.product.accounts import AccountStore,AccountError
    now=[1000]
    store=AccountStore(tmp_path/'accounts.sqlite3',clock=lambda:now[0])
    alice=store.register('alice_1','long-password-2026')
    bob=store.register('bob_001','long-password-2026')
    for _ in range(5):
        with pytest.raises(AccountError):store.authenticate('alice_1','wrong-password')
    with pytest.raises(AccountError) as limited:store.authenticate('alice_1','long-password-2026')
    assert limited.value.status==429
    now[0]+=901
    assert store.authenticate('alice_1','long-password-2026')['id']==alice['id']
    token=store.issue_session(alice['id'])
    store.bind_conversation(alice['id'],'agent-session-1','咖啡')
    assert store.owns_conversation(alice['id'],'agent-session-1')
    assert not store.owns_conversation(bob['id'],'agent-session-1')
    assert store.list_conversations(bob['id'])==[]
    assert store.list_conversations(alice['id'])[0]['session_id']=='agent-session-1'
    now[0]+=7*86400+1
    assert store.resolve_session(token) is None
