import unittest
from unittest.mock import AsyncMock, patch
from ollama import ChatResponse
from services.notion_agent import choose_tools, run_notion
from services.mcp_connections import NOTION_URL
from main import _spoken_answer

CATALOG=[{'server':'n','name':n,'description':'Tool description','parameters':{'type':'object','properties':{'pages':{'type':'array','items':{'type':'object','properties':{'properties':{'type':'object'},'content':{'type':'string'}}}}},'required':['pages']}} for n in ['notion-create-pages','notion-search','notion-fetch','notion-convert-page-to-skill']]

def response(text='',call=None):
    return ChatResponse(message={'role':'assistant','content':text,'tool_calls':[{'function':{'name':call,'arguments':{'pages':[{'properties':{'title':'Lino'},'content':'Présentation'}]}}}] if call else []})

class NotionAgent(unittest.IsolatedAsyncioTestCase):
    def test_selection_and_voice(self):
        selected,create=choose_tools('Fais une page de présentation de Lino dans Notion',CATALOG)
        self.assertTrue(create)
        self.assertNotIn('notion-convert-page-to-skill',[t['name'] for t in selected])
        self.assertEqual(_spoken_answer('La page est créée.\nhttps://www.notion.so/abc'),'La page est créée.')

    async def test_creates_then_returns_actual_link(self):
        client=AsyncMock();client.chat.return_value=response('{"title":"Lino","content":"Une présentation française de Lino, assistant personnel sur Windows."}')
        with patch('services.notion_agent.mcp_connections.list_tools',return_value=CATALOG),patch('services.notion_agent.mcp_connections.servers',{'n':{'url':NOTION_URL}}),patch('services.notion_agent.mcp_connections.call',new_callable=AsyncMock) as call:
            call.return_value={'content':[{'type':'text','text':'{"pages":[{"url":"https://www.notion.so/verified-page"}]}'}]}
            answer=await run_notion(client,'Fais une page de présentation de Lino dans Notion')
        self.assertEqual(call.await_args.args[1],'notion-create-pages')
        self.assertIn('https://www.notion.so/verified-page',answer)
        self.assertEqual(call.await_count,1)

    async def test_prose_is_not_reported_as_creation(self):
        client=AsyncMock();client.chat.return_value=response('The tool is designed to create pages.')
        with patch('services.notion_agent.mcp_connections.list_tools',return_value=CATALOG),patch('services.notion_agent.mcp_connections.servers',{'n':{'url':NOTION_URL}}),patch('services.notion_agent.mcp_connections.call',new_callable=AsyncMock) as call:
            answer=await run_notion(client,'Fais une page dans Notion')
        self.assertIn('Aucune création',answer)
        self.assertNotIn('The tool',answer)
        call.assert_not_awaited()

    async def test_refused_creation_never_claims_success(self):
        client=AsyncMock();client.chat.return_value=response('{"title":"Lino","content":"Une présentation française de Lino, assistant personnel sur Windows."}')
        with patch('services.notion_agent.mcp_connections.list_tools',return_value=CATALOG),patch('services.notion_agent.mcp_connections.servers',{'n':{'url':NOTION_URL}}),patch('services.notion_agent.mcp_connections.call',new_callable=AsyncMock,return_value={'isError':True,'content':[]}):
            answer=await run_notion(client,'Fais une page dans Notion')
        self.assertIn('refusée',answer)
        self.assertNotIn('La page est créée',answer)

if __name__=='__main__': unittest.main()
