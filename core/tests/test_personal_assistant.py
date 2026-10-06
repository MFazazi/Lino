import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from services.stripe_monitor import StripeMonitor
from tools.windows import search_file_paths
from tools import gmail
from services.mcp_connections import MCPConnections

def event(i,created=101):
    return {'id':f'evt_{i}','created':created,'type':'payment_intent.succeeded','livemode':False,
            'data':{'object':{'id':f'pi_{i}','amount_received':1234,'currency':'eur'}}}

class StripeTests(unittest.IsolatedAsyncioTestCase):
    def monitor(self):
        monitor=StripeMonitor(MagicMock())
        monitor.data={'key':'rk_test_fixture','since':100,'cursor':100,'seen':[],'notifications':[]}
        return monitor

    async def test_pagination_dedup_restart_and_ack(self):
        monitor=self.monitor()
        monitor.events=AsyncMock(side_effect=[{'data':[event(i) for i in range(100)],'has_more':True},{'data':[event(100)],'has_more':False}])
        with patch('services.stripe_monitor.runtime') as runtime:
            await monitor.poll()
            self.assertEqual(len(monitor.data['seen']),101)
            self.assertEqual(monitor.events.call_args.args[1]['starting_after'],'evt_99')
            runtime.request_ui.assert_called_once_with('show_payments')
        restored=self.monitor();restored.data=json.loads(json.dumps(monitor.data))
        restored.events=AsyncMock(return_value={'data':[event(100)],'has_more':False})
        with patch('services.stripe_monitor.runtime') as runtime:
            await restored.poll();runtime.request_ui.assert_not_called()
            await restored.acknowledge('evt_99')
        self.assertTrue(next(n for n in restored.data['notifications'] if n['id']=='evt_99')['read'])
        self.assertNotIn('key',restored.snapshot())

    async def test_failed_page_does_not_advance_cursor(self):
        monitor=self.monitor();monitor.events=AsyncMock(side_effect=[{'data':[event(1)],'has_more':True},ValueError('offline')])
        with self.assertRaises(ValueError):await monitor.poll()
        self.assertEqual(monitor.data['cursor'],100)
        self.assertEqual(monitor.data['notifications'],[])

    async def test_failed_key_never_persisted(self):
        monitor=self.monitor();monitor.events=AsyncMock(side_effect=ValueError('bad key'))
        with self.assertRaises(ValueError):await monitor.connect('rk_test_invalid')
        monitor.storage.save.assert_not_called()
        self.assertEqual(monitor.data['key'],'rk_test_fixture')

    async def test_failed_encryption_never_marks_connected(self):
        monitor=self.monitor();monitor.data={};monitor.events=AsyncMock(return_value={'data':[]})
        monitor.storage.save.side_effect=OSError('DPAPI unavailable')
        with self.assertRaises(OSError):await monitor.connect('rk_test_fixture')
        self.assertFalse(monitor.snapshot()['connected'])

class FilesTests(unittest.TestCase):
    def test_natural_query_accents_and_nested_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'2026').mkdir();target=root/'2026'/'Facture Électricité septembre.pdf';target.write_text('fixture')
            (root/'node_modules').mkdir();(root/'node_modules'/'facture.pdf').write_text('fixture')
            with patch('tools.windows._allowed_roots',return_value=[root]):
                self.assertEqual(search_file_paths('cherche moi une facture electricite sur mon pc'),[str(target)])
                self.assertEqual(search_file_paths(''),[])
                self.assertEqual(search_file_paths('facture'),[str(target)])

class GmailTests(unittest.TestCase):
    def test_draft_does_not_send_and_mime_roundtrip(self):
        service=MagicMock();service.users.return_value.drafts.return_value.create.return_value.execute.return_value={'id':'draft1'}
        with patch.object(gmail,'_compose_service',return_value=service):
            result=gmail.gmail_create_draft('client@example.com','Facture été','Bonjour, voici le récapitulatif.')
        self.assertFalse(result['sent']);service.users.return_value.messages.return_value.send.assert_not_called()
        raw=service.users.return_value.drafts.return_value.create.call_args.kwargs['body']['message']['raw']
        self.assertIn(b'client@example.com',base64.urlsafe_b64decode(raw))

    def test_existing_readonly_token_requires_reconnect_for_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token.json';token.write_text(json.dumps({'scopes':['https://www.googleapis.com/auth/gmail.readonly']}))
            with patch.object(gmail,'_token_path',return_value=token),patch.object(gmail,'_service') as service:
                with self.assertRaisesRegex(ValueError,'Reconnecte'):gmail.gmail_create_draft('a@example.com','Bonjour','Test')
                service.assert_not_called()

class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_email_never_enqueues_send(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=MCPConnections(directory)
            manager.servers={'google':{'name':'Google','url':'http://127.0.0.1:8765/google-mcp/'}}
            manager.catalogs={'google':[{'name':'send_gmail','inputSchema':{'type':'object'}}]}
            manager.queues={'google':asyncio.Queue()}
            with patch('services.voice.voice.notify_approval'),patch('services.mcp_connections.runtime'):
                task=asyncio.create_task(manager.call('google','send_gmail',{'to':'a@example.com','subject':'Test','body':'Fixture'}))
                await asyncio.sleep(0)
                self.assertEqual(len(manager.approvals),1)
                manager.decide(next(iter(manager.approvals)),'deny')
                result=await task
            self.assertTrue(result['isError']);self.assertTrue(manager.queues['google'].empty())

if __name__=='__main__':unittest.main()



class PersonalRouteTests(unittest.TestCase):
    def test_remote_origins_rejected_and_key_not_echoed(self):
        from fastapi.testclient import TestClient
        from main import app
        with patch('main.stripe_monitor.start'),patch('main.stripe_monitor.stop'),patch('main.approval_watcher.start'),patch('main.approval_watcher.stop'),patch('main.approval_notifications.start'),patch('main.approval_notifications.stop'),patch('main.mcp_connections.start'),patch('main.mcp_connections.stop'):
            client=TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',123))
            self.assertEqual(client.get('/personal/stripe',headers={'Origin':'https://external.example'}).status_code,403)
            self.assertEqual(client.post('/personal/files',json={'roots':['relative/path']}).status_code,400)
            with patch('personal_routes.stripe_monitor.connect',new_callable=AsyncMock,side_effect=ValueError('Clé refusée')):
                response=client.post('/personal/stripe/connect',json={'key':'rk_test_private_fixture'})
            self.assertEqual(response.status_code,400)
            self.assertNotIn('rk_test_private_fixture',response.text)

    def test_connect_requests_new_google_consent(self):
        service=MagicMock();service.users.return_value.getProfile.return_value.execute.return_value={}
        with patch.object(gmail,'_get_credentials') as credentials,patch.object(gmail,'build',return_value=service),patch.object(gmail,'gmail_status',return_value={}):
            gmail.gmail_connect()
        credentials.assert_called_once_with(force_consent=True)


class GmailHTMLTests(unittest.TestCase):
    def test_html_only_message_is_read_without_loading_remote_images(self):
        raw=base64.urlsafe_b64encode('<p>Facture : 120 €</p><img src="https://external.example/tracker">'.encode()).decode()
        with patch.object(gmail,'_service'),patch.object(gmail,'_get_full_message',return_value={'id':'msg1','payload':{'mimeType':'text/html','body':{'data':raw}},'snippet':'partial'}):
            result=gmail.gmail_read_message('msg1')
        self.assertEqual(result['text'],'Facture : 120 €')

