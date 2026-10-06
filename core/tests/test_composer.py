import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

class ComposerRoutes(unittest.TestCase):
    def client(self,origin=None):
        return TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',123),headers={'Origin':origin or 'http://127.0.0.1:1420'})

    def test_pdf_upload_and_reject_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory,patch('config.settings.download_dir',directory):
            client=self.client()
            result=client.post('/personal/document',files={'file':('../../fixture.pdf',b'%PDF-1.7\nfixture','application/pdf')})
            self.assertEqual(result.status_code,200,result.text)
            target=Path(result.json()['path'])
            self.assertTrue(target.is_relative_to(Path(directory)))
            self.assertEqual(target.read_bytes(),b'%PDF-1.7\nfixture')
            self.assertEqual(client.post('/personal/document',files={'file':('bad.pdf',b'not pdf','application/pdf')}).status_code,400)

    def test_external_site_cannot_upload(self):
        result=self.client('https://external.example').post('/personal/document',files={'file':('x.pdf',b'%PDF-1.7','application/pdf')})
        self.assertEqual(result.status_code,403)

    def test_dictation_only_transcribes_and_cleans_temporary_file(self):
        paths=[]
        def transcript(path):
            paths.append(Path(path));self.assertTrue(Path(path).exists());return 'Bonjour Lino'
        with patch('services.transcription.transcribe_file',side_effect=transcript),patch('main.agent.run') as agent:
            result=self.client().post('/personal/dictate',files={'file':('sound.webm',b'fixture','audio/webm')})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['transcript'],'Bonjour Lino')
        self.assertFalse(paths[0].exists());agent.assert_not_called()

    def test_empty_audio_is_rejected(self):
        self.assertEqual(self.client().post('/personal/dictate',files={'file':('empty.webm',b'','audio/webm')}).status_code,400)

    def test_transcription_failure_is_recoverable(self):
        with patch('services.transcription.transcribe_file',side_effect=RuntimeError('fixture unavailable')):
            response=self.client().post('/personal/dictate',files={'file':('sound.webm',b'fixture','audio/webm')})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('fixture unavailable',response.text)
