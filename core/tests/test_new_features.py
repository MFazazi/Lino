import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from tools import documents
from services.mcp_connections import MCPConnections, SecureStorage, validate_url
from mcp.shared.auth import OAuthToken
from mcp_routes import local
from starlette.requests import Request
from fastapi import HTTPException


class PDFs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.allowed = patch.object(documents, '_allowed_roots', return_value=[self.root])
        self.allowed.start()

    def tearDown(self):
        self.allowed.stop()
        self.temp.cleanup()

    def pdf(self, texts):
        writer = PdfWriter()
        for text in texts:
            page = writer.add_blank_page(600, 800)
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
        target = self.root / 'fixture.pdf'
        writer.write(target)
        return target

    def test_page_citation_and_search(self):
        target = self.pdf(['Introduction', 'Montant facture 1250 euros', 'Conclusion'])
        result = json.loads(documents.read_pdf(str(target), 'montant facture'))
        self.assertEqual(result['pages'][0]['page'], 2)
        self.assertIn('1250', result['pages'][0]['text'])

    def test_image_only_is_not_claimed_read(self):
        result = json.loads(documents.read_pdf(str(self.pdf(['']))))
        self.assertIn('OCR', result['error'])

    def test_outside_roots_requires_explicit_user_path(self):
        target = self.pdf(['Autorise uniquement ce fichier'])
        with patch.object(documents, '_allowed_roots', return_value=[]):
            with self.assertRaises(ValueError): documents.read_pdf(str(target))
            token = documents.explicit_files.set((str(target),))
            try: self.assertIn('Autorise', documents.read_pdf(str(target)))
            finally: documents.explicit_files.reset(token)
            with self.assertRaises(ValueError): documents.read_pdf(str(target))

    def test_invalid_page_and_network_path(self):
        with self.assertRaises(ValueError): documents.read_pdf(str(self.pdf(['test'])), page=2)
        with self.assertRaises(ValueError): documents.read_pdf(r'\\host\private\file.pdf')


class MCP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = MCPConnections(self.temp.name)

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temp.cleanup()

    async def test_tokens_are_encrypted_and_roundtrip(self):
        storage = SecureStorage(Path(self.temp.name) / 'test.dpapi')
        await storage.set_tokens(OAuthToken(access_token='test-private-token', token_type='Bearer', expires_in=3600))
        self.assertNotIn(b'test-private-token', storage.path.read_bytes())
        self.assertEqual((await storage.get_tokens()).access_token, 'test-private-token')
        storage.clear_tokens()
        self.assertIsNone(await storage.get_tokens())

    async def test_no_remote_write_until_explicit_choice(self):
        m = self.manager
        m.servers['fixture'] = {'name':'Test', 'url':'https://example.com/mcp'}
        m.catalogs['fixture'] = [{'name':'write', 'inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]
        m.queues['fixture'] = asyncio.Queue()
        with patch('services.voice.voice.notify_approval'):
            for decision in ['deny','allow']:
                task = asyncio.create_task(m.call('fixture','write',{'text':'fixture'}))
                for _ in range(100):
                    if m.approvals: break
                    await asyncio.sleep(.01)
                self.assertTrue(m.queues['fixture'].empty())
                approval = next(iter(m.approvals))
                m.decide(approval, decision)
                with self.assertRaises(ValueError): m.decide(approval, decision)
                if decision == 'allow':
                    name, args, future = await asyncio.wait_for(m.queues['fixture'].get(), 1)
                    self.assertEqual(args, {'text':'fixture'})
                    future.set_result({'content':[], 'isError':False})
                result = await asyncio.wait_for(task, 1)
                self.assertEqual(result['isError'], decision == 'deny')
                self.assertFalse(m.approvals)

    async def test_bad_schema_never_prompts_or_sends(self):
        m = self.manager
        m.servers['x'] = {'name':'Test','url':'https://example.com/mcp'}
        m.catalogs['x'] = [{'name':'write','inputSchema':{'type':'object','required':['text']}}]
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError): await m.call('x','write',{})
        self.assertFalse(m.approvals)

    def test_connection_origin_and_url(self):
        for url in ['http://example.com/mcp','https://user:pass@example.com/mcp','file:///private']:
            with self.assertRaises(ValueError): validate_url(url)
        self.assertEqual(validate_url('https://mcp.notion.com/mcp'), 'https://mcp.notion.com/mcp')
        for host, origin in [('192.168.1.2','http://tauri.localhost'),('127.0.0.1','https://evil.example')]:
            request = Request({'type':'http','client':(host,1234),'headers':[(b'origin',origin.encode())]})
            with self.assertRaises(HTTPException): local(request)
        local(Request({'type':'http','client':('127.0.0.1',1234),'headers':[(b'origin',b'http://tauri.localhost')]}))

if __name__ == '__main__': unittest.main()
