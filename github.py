import os
import json
import base64
import urllib.request
from nacl import encoding, public

DEPLOY_KEY_PATH = '/root/tgbot/ssh_keys/deploy_id_ed25519'

def _token():
    return os.getenv('GITHUB_TOKEN', '')

def _deploy_key_path():
    return os.getenv('DEPLOY_KEY_PATH', DEPLOY_KEY_PATH)

def _api(url, data=None, method=None):
    req = urllib.request.Request(
        url, data=data,
        method=method or ('PUT' if data else 'GET'),
        headers={
            'Authorization': f'token {_token()}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return (json.loads(body) if body else {}), r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        return (json.loads(body) if body else {}), e.code

def _get_username() -> str:
    """Get authenticated GitHub username."""
    result, status = _api('https://api.github.com/user', method='GET')
    return result.get('login', '') if status == 200 else ''

def list_repos() -> list:
    result, _ = _api('https://api.github.com/user/repos?per_page=100&sort=updated&type=private', method='GET')
    username = _get_username()
    if isinstance(result, list) and username:
        return [r['full_name'] for r in result if r.get('owner', {}).get('login') == username]
    return []

def create_repo(name: str, description: str = '') -> dict:
    data = json.dumps({'name': name, 'private': True, 'description': description}).encode()
    result, status = _api('https://api.github.com/user/repos', data=data, method='POST')
    return result

def _encrypt_secret(pubkey_b64: str, secret: str) -> str:
    pk = public.PublicKey(pubkey_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    return base64.b64encode(box.encrypt(secret.encode())).decode()

def set_secret(repo: str, name: str, value: str) -> int:
    pk_data, _ = _api(f'https://api.github.com/repos/{repo}/actions/secrets/public-key')
    encrypted = _encrypt_secret(pk_data['key'], value)
    data = json.dumps({'encrypted_value': encrypted, 'key_id': pk_data['key_id']}).encode()
    _, status = _api(f'https://api.github.com/repos/{repo}/actions/secrets/{name}', data=data)
    return status

def delete_repo(repo: str) -> tuple:
    """Delete a repository. Returns (response_body, status_code). 204 = success."""
    return _api(f'https://api.github.com/repos/{repo}', method='DELETE')

def setup_repo_secrets(repo: str, deploy_host: str) -> bool:
    try:
        deploy_key = open(DEPLOY_KEY_PATH).read()
        r1 = set_secret(repo, 'DEPLOY_HOST', deploy_host)
        r2 = set_secret(repo, 'DEPLOY_KEY', deploy_key)
        return r1 in (201, 204) and r2 in (201, 204)
    except Exception:
        return False
