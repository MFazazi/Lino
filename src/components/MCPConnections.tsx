import { ReactNode, useEffect, useState } from 'react';
import { ArrowUpRight, Check, Link2, LoaderCircle, Plus, Unplug } from 'lucide-react';
import { linoApi } from '../lib/api';
import { ServiceIcon } from './ServiceIcon';

type Server = { id: string; name: string; url: string; status: string; message?: string; tool_count: number };

export function MCPConnections({ children }: { children?: ReactNode }) {
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState('');
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState('');
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const refresh = async () => {
    try { const data = await linoApi.mcpServers(); setServers(data.servers); setAvailable(true); setError(''); }
    catch (e) { setAvailable(false); setError(e instanceof Error ? e.message : 'Connexions indisponibles.'); }
  };
  useEffect(() => { let mounted = true; let timer = 0;
    const tick = async () => { if (!mounted) return; await refresh(); if(mounted) timer=window.setTimeout(tick,1500); };
    void tick(); return () => { mounted=false; window.clearTimeout(timer); };
  }, []);
  const act = async (key: string, operation: () => Promise<unknown>) => {
    setBusy(key); setError('');
    try { await operation(); await refresh(); }
    catch(e) { setError(e instanceof Error ? e.message : 'Connexion impossible.'); }
    finally { setBusy(''); }
  };
  const visible = servers.filter(s=>s.url !== 'http://127.0.0.1:8765/google-mcp/');
  const notion = visible.find(s=>s.url==='https://mcp.notion.com/mcp');
  const items = notion ? visible : [{id:'notion',name:'Notion',url:'https://mcp.notion.com/mcp',status:'disconnected',tool_count:0},...visible];
  return <section className="mcp-connections">
    {error&&<p className="approval-error connection-error" role="alert">{error}</p>}
    <div className="connections-heading"><div><span className="eyebrow">CONNEXIONS</span><h2>Tout au même endroit.</h2><p>Tes comptes, tes automatisations et ton microphone.</p></div><button className="button button--ghost" onClick={()=>setAdding(!adding)}><Plus size={15}/> Ajouter un service</button></div>
    <div className="mcp-grid">{items.map(server=>{
      const connected=server.status==='connected';
      const pending=['connecting','authorizing'].includes(server.status);
      const builtin=server.id==='notion';
      return <article className={`mcp-tile ${connected?'mcp-tile--connected':''}`} key={server.id}>
        <div className="mcp-tile__top"><ServiceIcon name={server.name}/><span className={`connection-state ${connected?'connected':''}`}>{connected?<><Check size={12}/> Connecté</>:pending?<><LoaderCircle size={12} className="spin"/> Connexion…</>:server.status==='error'?'À reconnecter':'Non connecté'}</span></div>
        <h3>{server.name}</h3><p>{connected?`${server.tool_count} outils disponibles pour tes demandes.`:server.message||'Recherche, lecture et actions depuis Lino.'}</p>
        <button className={`button ${connected?'button--ghost':'button--light'}`} disabled={!!busy||pending||!available} onClick={()=>void act(server.id,()=>connected?linoApi.mcpDisconnect(server.id):builtin?linoApi.mcpNotion():linoApi.mcpConnect(server.id))}>{connected?<><Unplug size={14}/> Déconnecter</>:<>{!available?'Moteur indisponible':busy===server.id?'Ouverture…':'Connecter'}<ArrowUpRight size={15}/></>}</button>
        {pending&&<button className="mcp-cancel" onClick={()=>void act(server.id,()=>linoApi.mcpDisconnect(server.id))}>Annuler</button>}
      </article>;
    })}</div>
    {!visible.some(s=>s.name==='n8n')&&<div className="setting-row n8n-connection"><ServiceIcon name="n8n"/><div><strong>n8n</strong><span>Connecte ton instance et ses workflows</span></div><button className="button button--ghost" onClick={()=>{setAdding(true);setName('n8n');setUrl('');}}>Connecter</button></div>}
    {children}
    {adding&&<form className="mcp-add" onSubmit={event=>{event.preventDefault();void act('add',async()=>{await linoApi.mcpAdd(name.trim(),name.trim().toLowerCase()==='n8n'&&!url.includes('/mcp-server/') ? url.trim().replace(/\/$/,'')+'/mcp-server/http' : url.trim());setAdding(false);setName('');setUrl('');});}}>
      <label>Nom du service<input required value={name} onChange={e=>setName(e.target.value)} placeholder="Mon service"/></label>
      <label>{name==='n8n'?'Adresse de ton instance n8n':'Adresse du serveur MCP'}<input required type="url" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://service.example/mcp"/></label>
      <button className="button button--light" disabled={!!busy}>Connecter</button><p>{name==='n8n'?'Active l’accès MCP dans les réglages de n8n. La connexion ouvrira ton navigateur.':'Serveurs MCP HTTP compatibles.'}</p>
    </form>}

  </section>;
}
