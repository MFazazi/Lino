import type { ChatResponse, ConnectionSnapshot, HealthResponse, LinoState, SourceItem } from '../types';

const CORE_URL = import.meta.env.VITE_LINO_CORE_URL || 'http://127.0.0.1:8765';

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${CORE_URL}${url}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(url === '/chat' || url.includes('/connect') ? 300000 : 15000),
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    if (response.status === 404 && url.startsWith('/mcp/')) throw new Error('Le moteur Lino lancé est une ancienne version. Ferme Lino et son Core, puis relance Lino pour activer Notion.');
    let message = await response.text();
    try {
      const parsed = JSON.parse(message) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch { /* keep text */ }
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function upload<T>(url:string,blob:Blob,filename:string):Promise<T>{
  const data=new FormData();data.append('file',blob,filename);
  const response=await fetch(`${CORE_URL}${url}`,{method:'POST',body:data,signal:AbortSignal.timeout(180000)});
  const result=await response.json();if(!response.ok)throw new Error(result.detail||'Chargement impossible.');return result;
}

export const linoApi = {
  uploadDocument: (file:File) => upload<{path:string}>('/personal/document',file,file.name),
  dictate: (blob:Blob) => upload<{transcript:string}>('/personal/dictate',blob,'dictation.webm'),
  stripeStatus: () => json<{connected:boolean;error:string;mode:string;last_checked:number|null;notifications:import('../types').PaymentNotification[]}>('/personal/stripe'),
  stripeConnect: (key:string) => json('/personal/stripe/connect',{method:'POST',body:JSON.stringify({key})}),
  stripeDisconnect: () => json('/personal/stripe/disconnect',{method:'POST'}),
  paymentRead: (id:string) => json(`/personal/stripe/notifications/${encodeURIComponent(id)}/read`,{method:'POST'}),
  fileRoots: () => json<{roots:string[];custom_roots:string[]}>('/personal/files'),
  saveFileRoots: (roots:string[]) => json('/personal/files',{method:'POST',body:JSON.stringify({roots})}),
  googleStatus: () => json<{connected:boolean}>('/mcp/google/status'),
  connectDocs: () => json('/mcp/google/docs/connect', {method:'POST'}),
  mcpServers: () => json<{servers: {id:string;name:string;url:string;status:string;message?:string;tool_count:number}[]}>('/mcp/servers'),
  mcpNotion: () => json('/mcp/notion/connect', {method:'POST'}),
  mcpAdd: (name:string,url:string) => json('/mcp/servers', {method:'POST',body:JSON.stringify({name,url})}),
  mcpConnect: (id:string) => json(`/mcp/servers/${encodeURIComponent(id)}/connect`, {method:'POST'}),
  mcpDisconnect: (id:string) => json(`/mcp/servers/${encodeURIComponent(id)}/disconnect`, {method:'POST'}),
  mcpDecision: (id:string,decision:string) => json<{message:string}>('/mcp/decision', {method:'POST',body:JSON.stringify({id,decision})}),
  getState: () => json<LinoState>('/state'),
  health: () => json<HealthResponse>('/health'),
  connections: () => json<ConnectionSnapshot>('/connections'),
  chat: (message: string) => json<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, speak: true }),
  }),
  sleep: () => json<LinoState & { ok: boolean }>('/ui/sleep', { method: 'POST' }),
  show: () => json<LinoState & { ok: boolean }>('/ui/show', { method: 'POST' }),
  muteVoice: (muted: boolean) => json('/voice/mute', { method: 'POST', body: JSON.stringify({ muted }) }),
  testApproval: () => json('/agents/test-alert', { method: 'POST' }),
  stopSpeaking: () => json<{ ok: boolean }>('/voice/stop', { method: 'POST' }),
  testVoice: (text = 'Bonjour boss, Lino est prêt.') => json<{ ok: boolean }>('/voice/test', {
    method: 'POST',
    body: JSON.stringify({ text }),
  }),
  searchFiles: (query: string) => json<{ results: string[] }>('/tools/files/search', {
    method: 'POST',
    body: JSON.stringify({ query }),
  }),
  openPath: (path: string) => json<{ ok: boolean; message: string }>('/tools/open-path', {
    method: 'POST',
    body: JSON.stringify({ path }),
  }),
  openUrl: (url: string) => json<{ ok: boolean; message: string }>('/tools/open-url', {
    method: 'POST',
    body: JSON.stringify({ url }),
  }),
  openApp: (app: string) => json<{ ok: boolean; message: string }>('/tools/open-app', {
    method: 'POST',
    body: JSON.stringify({ app }),
  }),
  webSearch: (query: string) => json<{ results: SourceItem[] }>('/tools/web/search', {
    method: 'POST',
    body: JSON.stringify({ query }),
  }),
  configureGmail: (clientId: string, clientSecret: string) => json('/connections/gmail/configure', {
    method: 'POST',
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  }),
  connectGmail: () => json<{ ok: boolean; email?: string }>('/mcp/google/gmail/connect', { method: 'POST' }),
  disconnectGmail: () => json('/connections/gmail/disconnect', { method: 'POST' }),
  configureN8n: (url: string) => json<ConnectionSnapshot>('/connections/n8n', {
    method: 'POST',
    body: JSON.stringify({ url }),
  }),
  configureWeb: (braveApiKey: string) => json<ConnectionSnapshot>('/connections/web', {
    method: 'POST',
    body: JSON.stringify({ brave_api_key: braveApiKey }),
  }),
};
