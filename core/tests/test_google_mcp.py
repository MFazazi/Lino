import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from tools import google_docs

class GoogleMCP(unittest.TestCase):
    def test_local_mcp_tools_and_origin_guard(self):
        with patch('main.stripe_monitor.start'), patch('main.stripe_monitor.stop'), patch('main.approval_watcher.start'), patch('main.approval_watcher.stop'), patch('main.approval_notifications.start'), patch('main.approval_notifications.stop'), patch('main.mcp_connections.start'), patch('main.mcp_connections.stop'):
            with TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1',12345)) as client:
                headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
                response=client.post('/google-mcp/',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
                self.assertEqual(response.status_code,200,response.text)
                tools=client.post('/google-mcp/',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}).json()
                self.assertEqual({t['name'] for t in tools['result']['tools']},{'search_gmail','read_gmail','create_gmail_draft','send_gmail','search_google_docs','read_google_doc'})
                bad=client.post('/google-mcp/',headers={**headers,'Origin':'https://external.example'},json={})
                self.assertEqual(bad.status_code,403)

    def test_docs_reads_tab_paragraphs_and_table(self):
        service=MagicMock()
        service.documents.return_value.get.return_value.execute.return_value={'title':'Synthetic document','tabs':[{'documentTab':{'body':{'content':[{'paragraph':{'elements':[{'textRun':{'content':'Chapter 1\n'}}]}},{'table':{'tableRows':[{'tableCells':[{'content':[{'paragraph':{'elements':[{'textRun':{'content':'Total: 42'}}]}}]}]}]}}]}}}]}
        with patch.object(google_docs,'credentials'),patch.object(google_docs,'build',return_value=service):
            result=google_docs.read('https://docs.google.com/document/d/test_id/edit')
        self.assertEqual(result['text'],'Chapter 1\nTotal: 42')
        self.assertFalse(result['truncated'])

if __name__=='__main__': unittest.main()

