import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
import httpx
from services.mcp_connections import MCPConnections, CALLBACK

class MemoryStorage:
    tokens = None
    client = None
    async def get_tokens(self): return self.tokens
    async def set_tokens(self, value): self.tokens = value
    async def get_client_info(self): return self.client
    async def set_client_info(self, value): self.client = value

class OAuthIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_discovery_registration_pkce_callback_and_tools(self):
        temp = tempfile.TemporaryDirectory()
        manager = MCPConnections(temp.name)
        storage = MemoryStorage()
        base = 'https://fixture.example'
        seen = []
        browser_urls = []
        original_client = httpx.AsyncClient
        def handler(request):
            seen.append((request.method, request.url.path))
            path = request.url.path
            if path.startswith('/.well-known/oauth-protected-resource'):
                return httpx.Response(200,json={'resource':base+'/mcp','authorization_servers':[base]})
            if path.startswith('/.well-known/'):
                return httpx.Response(200,json={'issuer':base,'authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','registration_endpoint':base+'/register','response_types_supported':['code'],'grant_types_supported':['authorization_code','refresh_token'],'code_challenge_methods_supported':['S256'],'token_endpoint_auth_methods_supported':['none']})
            if path == '/register':
                metadata=json.loads(request.content)
                self.assertEqual(metadata['token_endpoint_auth_method'],'none')
                self.assertIn(CALLBACK,metadata['redirect_uris'])
                return httpx.Response(201,json={**metadata,'client_id':'fixture-client'})
            if path == '/token':
                params=parse_qs(request.content.decode())
                self.assertTrue(params['code_verifier'][0])
                self.assertEqual(params['code'],['fixture-code'])
                return httpx.Response(200,json={'access_token':'fixture-token','token_type':'Bearer','expires_in':3600})
            if request.headers.get('authorization') != 'Bearer fixture-token':
                return httpx.Response(401,headers={'WWW-Authenticate':f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'})
            if request.method in {'GET','DELETE'}: return httpx.Response(405)
            body=json.loads(request.content)
            if 'id' not in body: return httpx.Response(202)
            method=body['method']
            if method=='initialize': result={'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
            elif method=='tools/list': result={'tools':[{'name':'fixture-read','description':'Synthetic test','inputSchema':{'type':'object'}}]}
            else: result={'content':[{'type':'text','text':'synthetic result'}]}
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':result})
        def browser(url):
            browser_urls.append(url)
            return True
        def client_factory(**kwargs): return original_client(**kwargs,transport=httpx.MockTransport(handler))
        try:
            with patch.object(manager,'storage',return_value=storage), patch('services.mcp_connections.httpx.AsyncClient',side_effect=client_factory), patch('services.mcp_connections.webbrowser.open',side_effect=browser):
                key=await manager.add('Fixture',base+'/mcp')
                for _ in range(200):
                    if browser_urls or manager.statuses[key]['status']=='error': break
                    await asyncio.sleep(.01)
                self.assertTrue(browser_urls,manager.statuses)
                query=parse_qs(urlsplit(browser_urls[0]).query)
                self.assertEqual(query['code_challenge_method'],['S256'])
                self.assertTrue(query['code_challenge'][0])
                async with original_client() as client:
                    bad=await client.get(CALLBACK,params={'state':'wrong-state','code':'fixture-code'})
                    self.assertEqual(bad.status_code,400)
                    self.assertEqual(manager.statuses[key]['status'],'authorizing')
                    good=await client.get(CALLBACK,params={'state':query['state'][0],'code':'fixture-code'})
                    self.assertEqual(good.status_code,200)
                for _ in range(200):
                    if manager.statuses[key]['status'] in {'connected','error'}: break
                    await asyncio.sleep(.01)
                self.assertEqual(manager.statuses[key]['status'],'connected',manager.statuses)
                self.assertEqual(manager.list_tools()[0]['name'],'fixture-read')
                self.assertEqual(storage.tokens.access_token,'fixture-token')
        finally:
            await manager.stop()
            temp.cleanup()

if __name__=='__main__': unittest.main()
