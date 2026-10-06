import {
  Bot,
  Bell,
  Link2,
  Search,
  CirclePlus,
  ExternalLink,
  Globe2,
  Home,
  Mail,
  MessageSquare,
  Mic,
  PlugZap,
  Send,
  Settings,
  ShieldCheck,
  Smartphone,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import { FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { linoApi } from '../lib/api';
import type { ConnectionSnapshot, IslandView, LinoState } from '../types';
import { ApprovalActions } from './ApprovalActions';
import { MCPConnections } from './MCPConnections';
import { Mascot } from './Mascot';
import { ServiceIcon } from './ServiceIcon';
import { Welcome } from './Welcome';
import { Composer } from './Composer';
import { PersonalSettings, paymentLabel } from './PersonalSettings';

const emptyConnections: ConnectionSnapshot = {
  ok: true,
  gmail: { connected: false, ready_to_connect: false, needs_setup: true },
  web: { connected: true, mode: 'automatic', detail: 'Automatique' },
  n8n: { connected: false, url: '' },
  phone: { connected: false, detail: 'Non connecté' },
  voice: { connected: true, backend: 'Windows' },
};

function statusText(state: LinoState) {
  const running = [...state.actions].reverse().find((item) => item.state === 'running');
  if (state.external_approvals?.[0]) return `${state.external_approvals[0].app} attend ta validation`;
  if (running) return running.detail || running.label;
  if (state.status === 'listening') return "Je t'écoute…";
  if (state.status === 'thinking') return 'Je réfléchis…';
  if (state.status === 'acting') return 'Je m’en occupe…';
  if (state.status === 'speaking') return 'Je te réponds…';
  if (state.status === 'error') return state.answer || 'Une erreur est survenue.';
  if (state.payment_notifications?.[0]) return paymentLabel(state.payment_notifications[0]);
  return state.answer || state.transcript || 'Prêt';
}

function StatusPill({ state }: { state: LinoState }) {
  const cls = state.status === 'error' ? 'error' : state.external_approvals?.length ? 'approval' : state.status;
  const label = state.external_approvals?.length ? 'Validation' : state.status_label;
  return <span className={`status-pill status-pill--${cls}`}>{label}</span>;
}

function CompactIsland({ state, onOpen }: { state: LinoState; onOpen: () => void }) {
  const approval = state.external_approvals?.[0];
  return (
    <button className={`petit petit--${approval ? 'approval' : state.status}`} onClick={onOpen} aria-label="Ouvrir Lino">
      <Mascot status={approval ? 'listening' : state.status} compact />
      <span className="petit__content">
        <span className="petit__title"><strong>Lino</strong><StatusPill state={state} /></span>
        {(state.status !== 'ready' || state.external_approvals.length > 0 || !!state.payment_notifications?.length) && <span className="petit__line">{statusText(state)}</span>}
      </span>
      <span className={`petit__signal petit__signal--${state.status}`} aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /></span>
    </button>
  );
}

function Header({ view, onView, muted, onMute, onClose }: {
  view: IslandView;
  onView: (view: IslandView) => void;
  muted: boolean;
  onMute: () => void;
  onClose: () => void;
}) {
  return (
    <header className="island-header"><button className="lino-wordmark" onClick={()=>onView('home')} aria-label="Accueil Lino">Lino</button>
      <div className="island-header__left">
        <button className={view === 'home' ? 'active' : ''} onClick={() => onView('home')} title="Accueil"><Home size={17} /><span>Accueil</span></button>
        <button className={view === 'chat' ? 'active' : ''} onClick={() => onView('chat')} title="Conversation"><MessageSquare size={17} /><span>Discussion</span></button>
        <button className={view === 'agents' ? 'active' : ''} onClick={() => onView('agents')} title="Agents"><Bell size={17} /><span>Alertes</span></button>
        <button className={view === 'apps' ? 'active' : ''} onClick={() => onView('apps')} title="Connexions"><Link2 size={17} /><span>Connexions</span></button>
      </div>
      
      <div className="island-header__right"><button onClick={()=>onView('chat')} title="Rechercher ou poser une question" aria-label="Rechercher ou poser une question"><Search size={18}/></button>
        <button className={view === 'settings' ? 'active' : ''} onClick={() => onView('settings')} title="Réglages"><Settings size={18} /></button>
        <button onClick={onMute} title={muted ? 'Activer le son' : 'Couper le son'}>{muted ? <VolumeX size={18} /> : <Volume2 size={18} />}</button>
        <button onClick={onClose} title="Réduire"><X size={18} /></button>
      </div>
    </header>
  );
}

function ErrorCard({ state, onRetry, onSettings }: { state: LinoState; onRetry: () => void; onSettings: () => void }) {
  return (
    <section className="hero-card hero-card--error">
      <div className="hero-card__mascot"><Mascot status="error" /></div>
      <div className="hero-card__body">
        <div className="eyebrow"><span className="dot dot--error" />Lino</div>
        <h2>Ça a coincé.</h2>
        <p>{state.answer || 'Une erreur est survenue.'}</p>
        <div className="hero-card__actions">
          <button className="button button--light" onClick={onRetry}>Réessayer</button>
          <button className="button button--ghost" onClick={onSettings}>Diagnostic</button>
        </div>
      </div>
    </section>
  );
}

function ApprovalCard({ state, onAnswered }: { state: LinoState; onAnswered: (id: string) => void }) {
  const approval = state.external_approvals[0];
  return (
    <section className="hero-card hero-card--approval">
      <div className="hero-card__mascot"><Mascot status="listening" /></div>
      <div className="hero-card__body">
        <div className="eyebrow"><span className="dot dot--approval" />{approval.app}</div>
        <h2>Ton attention est requise.</h2>
        <p style={{ whiteSpace: 'pre-wrap', maxHeight: 100, overflow: 'auto' }}>{approval.message}</p>
        <ApprovalActions key={approval.id} approval={approval} onAnswered={onAnswered} />
        <div className="hero-card__actions">
          <button className="button button--light" onClick={() => linoApi.openApp(approval.app).catch(() => undefined)}>Ouvrir {approval.app}</button>
          <span className="approval-time">détecté à {approval.detected_at}</span>
        </div>
      </div>
    </section>
  );
}

function ActivityCard({ state }: { state: LinoState }) {
  if (!state.actions.length && !state.transcript && !state.answer) return (
    <section className="idle-card">
      <Mascot status="ready" />
      <div><span className="eyebrow"><span className="dot dot--online" />Lino est prêt</span>
      <h2>À ton écoute.</h2><p>Écris-moi dans Discussion ou parle avec ton micro connecté.</p>
      <span className="idle-card__note">Tes demandes de validation apparaîtront ici.</span></div>
    </section>
  );
  const actions = state.actions.slice(-4);
  const current = [...actions].reverse().find((item) => item.state === 'running') || actions.at(-1);
  return (
    <section className="session-card">
      <aside className="session-card__aside">
        <Mascot status={state.status} />
        <strong>Lino</strong>
        <span>{state.status === 'acting' ? 'En action' : state.status_label}</span>
        <div className="steps">
          {actions.length ? actions.map((action) => (
            <div key={action.id} className={`step step--${action.state}`}><i />{action.label}</div>
          )) : <><div className="step step--done"><i />Comprend</div><div className="step step--running"><i />Prêt</div></>}
        </div>
      </aside>
      <div className="session-card__detail">
        <div className="session-card__tab"><Bot size={14} />{current?.tool || 'Assistant'}<span>{current?.state === 'done' ? 'Terminé' : current?.state === 'error' ? 'Erreur' : 'En cours'}</span></div>
        <div className="session-card__content">
          <div className="session-card__summary">{current?.detail || state.answer || state.transcript || 'Dis-moi ce que tu veux faire.'}</div>
          {state.sources.length > 0 && <div className="source-row">{state.sources.slice(0, 3).map((source) => <button key={source.id} onClick={() => linoApi.openUrl(source.url)}><Globe2 size={13} />{source.domain}<ExternalLink size={11} /></button>)}</div>}
        </div>
      </div>
    </section>
  );
}

function ChatView({ state, onSend, text, onText, busy }: { state: LinoState; onSend: (message: string) => Promise<void>;text:string;onText:(text:string)=>void;busy:boolean }) {
  return <section className="chat-card">
    <div className="chat-card__model"><span className="dot dot--online" />Lino · {state.status_label}</div>
    <div className="chat-card__messages" role="log" aria-live="polite">
      {state.transcript && <div className="bubble bubble--user">{state.transcript}</div>}
      <div className="chat-card__assistant"><Mascot status={state.status} compact/><div>{state.answer || (busy?'Je m’en occupe…':'Je suis là. Que souhaitez-vous faire ?')}</div></div>
    </div>
    <Composer text={text} onText={onText} onSend={onSend} busy={busy}/>
  </section>;
}

function AppsView({ connections, refresh }: { connections: ConnectionSnapshot; refresh: () => Promise<void> }) {
  return <div className="connections-view"><MCPConnections><SettingsView connections={connections} refresh={refresh} embedded /><PersonalSettings /></MCPConnections></div>;
}

function AgentsView({ state, onAnswered }: { state: LinoState; onAnswered: (id: string) => void }) {
  const [testMessage, setTestMessage] = useState('');
  const testAlert = async () => {
    try { if (!state.voice_muted) await invoke('play_notification_sound'); setTestMessage(state.voice_muted ? 'Le son est coupé.' : 'Son de notification joué.'); }
    catch { setTestMessage('Le son de notification est indisponible.'); }
  };
  return (
    <section className="agents-card">
      <div className="agents-card__title"><ShieldCheck size={18} /><div><strong>Agents</strong><span>{state.approval_monitor?.message || 'Surveillance en attente'}</span></div><button className="button button--ghost" onClick={testAlert}>Tester le son</button></div>
      {testMessage && <div role="status" className="settings-message">{testMessage}</div>}
      {state.external_approvals.length ? state.external_approvals.map((approval) => (
        <div className="agent-row agent-row--waiting" key={approval.id}>
          <div className="agent-icon">{approval.app.slice(0, 1)}</div>
          <div className="agent-row__content"><strong>{approval.app}{approval.source === 'test' ? ' · Test' : approval.can_respond ? ' · À valider' : ' · Notification'}</strong><span className="approval-description">{approval.message}</span><ApprovalActions key={approval.id} approval={approval} onAnswered={onAnswered} /></div>
          <time>{approval.detected_at}</time>
        </div>
      )) : <div className="agent-empty"><Mascot status="ready" compact /><div><strong>Aucune validation en attente.</strong><span>Les demandes détectées apparaissent ici. Autoriser / Refuser est proposé lorsque Lino peut accéder aux boutons de la demande.</span></div></div>}
    </section>
  );
}

function SettingsView({ connections, refresh, embedded = false }: { connections: ConnectionSnapshot; refresh: () => Promise<void>; embedded?: boolean }) {
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState(false);
  useEffect(() => { void linoApi.googleStatus().then(s=>setDocs(s.connected)).catch(()=>{}); }, []);
  const connectDocs = async () => {
    setBusy(true); setMessage('Ouverture de Google… Termine la connexion dans ton navigateur.');
    try { await linoApi.connectDocs(); setDocs(true); setMessage('Google Docs connecté.'); }
    catch(e) { setMessage(e instanceof Error ? e.message : 'Connexion non terminée.'); }
    finally { setBusy(false); }
  };
  const connectGmail = async () => {
    setBusy(true);
    try { setMessage('Ouverture de Google… Termine la connexion dans ton navigateur.'); await linoApi.connectGmail(); setMessage('Gmail connecté.'); await refresh(); }
    catch (e) { setMessage(e instanceof Error ? e.message : 'Connexion Gmail impossible.'); }
    finally { setBusy(false); }
  };
  return (
    <section className={embedded ? "settings-card settings-card--embedded" : "settings-card"}>
      {!embedded && <div className="settings-card__header"><div><span className="eyebrow">Réglages</span><h2>Connexions</h2></div><Settings size={24} /></div>}
      <div className="settings-list">
        <div className="setting-row"><ServiceIcon name="Gmail"/><div><strong>Gmail</strong><span>{connections.gmail.connected ? 'Connecté à ton compte' : 'Recherche, lecture, brouillons et envoi sur demande'}</span></div><button className="button button--ghost" disabled={busy} onClick={connectGmail}>{connections.gmail.connected ? 'Reconnecter' : 'Connecter'}</button></div>
        <div className="setting-row"><ServiceIcon name="Google Docs"/><div><strong>Google Docs</strong><span>{docs ? 'Connecté à ton compte' : 'Recherche et lecture des documents'}</span></div><button className="button button--ghost" disabled={busy} onClick={connectDocs}>{docs ? 'Reconnecter' : 'Connecter'}</button></div>
        <div className="setting-row"><ServiceIcon name="Web"/><div><strong>Web</strong><span>{connections.web.detail || 'Actif automatiquement'}</span></div><span className="connected-chip">Actif</span></div>
        <div className="setting-row"><ServiceIcon name="Téléphone"/><div><strong>Téléphone</strong><span>{connections.phone.detail}</span></div><span className={connections.phone.connected ? 'connected-chip' : 'muted-chip'}>{connections.phone.connected ? 'Connecté' : 'En attente'}</span></div>
      </div>
      {message && <div className="settings-message">{message}</div>}
    </section>
  );
}

export function Island({ state, onSend, onApprovalAnswered }: { state: LinoState; onSend: (message: string) => Promise<void>; onApprovalAnswered: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [phase, setPhase] = useState<'compact' | 'open' | 'closing'>('compact');
  const resizeQueue = useRef(Promise.resolve());
  const shellRef = useRef<HTMLDivElement>(null);
  const expandedRef = useRef(expanded);
  expandedRef.current = expanded;
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const busy = sending || ['thinking','acting','listening'].includes(state.status);
  const send = async (text:string) => {
    if (sending) return;
    setSending(true);setView('chat');
    try { await onSend(text); } finally { setSending(false); }
  };
  const [view, setView] = useState<IslandView>('home');
  const muted = state.voice_muted ?? false;
  const [connections, setConnections] = useState<ConnectionSnapshot>(emptyConnections);
  const lastUiEvent = useRef<number>(-1);
  const openedApprovals = useRef(new Set<string>());

  const resize = async (mode: 'petit' | 'home') => {
    if (!isTauri()) return;
    try { await invoke('set_island_mode', { mode }); }
    catch (error) { console.error('Lino: impossible de redimensionner l’island', error); }
  };
  const expand = async (nextView: IslandView = 'home') => {
    setView(nextView);
    setExpanded(true);
  };
  const collapse = async () => {
    setExpanded(false);
  };

  // Serialize native resizes so a quick close/reopen cannot leave the wrong window size.
  const applyMode = (mode: 'petit' | 'home') => {
    resizeQueue.current = resizeQueue.current.then(() => resize(mode));
    return resizeQueue.current;
  };

  useEffect(() => {
    let cancelled = false;
    if (expanded) {
      void applyMode('home').then(() => { if (!cancelled) setPhase('open'); });
    } else if (phase !== 'compact') {
      setPhase('closing');
    } else {
      // Also handles a blur while the opening native resize is still pending.
      void applyMode('petit');
    }
    return () => { cancelled = true; };
  }, [expanded]);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!shell || phase === 'compact') return;
    let cancelled = false;
    const closing = phase === 'closing';
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const side = Math.max(0, (shell.clientWidth - 320) / 2);
    const compactShape = `inset(0px ${side}px ${Math.max(0, shell.clientHeight - 38)}px round 0px 0px 19px 19px)`;
    const fullShape = 'inset(0px 0px 0px 0px round 0px 0px 0px 0px)';
    const currentShape = getComputedStyle(shell).clipPath;
    const from = currentShape === 'none' ? compactShape : currentShape;
    const to = closing ? compactShape : fullShape;
    const duration = reduced ? 0 : closing ? 320 : 440;
    const motion = shell.animate([{ clipPath: from }, { clipPath: to }], {
      duration, easing: closing ? 'cubic-bezier(.55,0,.25,1)' : 'cubic-bezier(.16,1,.3,1)', fill: 'forwards',
    });
    const content = shell.querySelectorAll<HTMLElement>('.island-header, .island-body');
    const fades = Array.from(content, element => element.animate([
      { opacity: getComputedStyle(element).opacity, transform: getComputedStyle(element).transform },
      { opacity: closing ? 0 : 1, transform: closing ? 'translateY(-8px)' : 'translateY(0px)' },
    ], { duration: reduced ? 0 : closing ? 130 : 260, delay: reduced || closing ? 0 : 80, easing: 'ease-out', fill: 'forwards' }));
    void motion.finished.then(async () => {
      if (!closing || cancelled || expandedRef.current) return;
      await applyMode('petit');
      if (!cancelled && !expandedRef.current) setPhase('compact');
    }).catch(() => { /* A reversed animation was cancelled. */ });
    return () => {
      cancelled = true;
      // Preserve the current frame when reversing direction, avoiding a visual jump.
      shell.style.clipPath = getComputedStyle(shell).clipPath;
      Array.from(content).forEach(element => {
        element.style.opacity = getComputedStyle(element).opacity;
        element.style.transform = getComputedStyle(element).transform;
      });
      motion.cancel();
      fades.forEach(animation => animation.cancel());
    };
  }, [phase]);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    const onBlur = () => setExpanded(false);
    if (isTauri()) {
      void getCurrentWindow().onFocusChanged(({ payload: focused }) => {
        if (!focused) onBlur();
      }).then(stop => { if (disposed) stop(); else unlisten = stop; })
        .catch(error => console.error('Lino: écoute du focus indisponible', error));
    } else {
      window.addEventListener('blur', onBlur);
    }
    return () => {
      disposed = true;
      unlisten?.();
      window.removeEventListener('blur', onBlur);
    };
  }, []);

  const answered = (id: string) => {
    onApprovalAnswered(id);
    void collapse();
  };

  const refreshConnections = async () => {
    try { setConnections(await linoApi.connections()); } catch { /* Core may be starting */ }
  };

  useEffect(() => { refreshConnections(); }, [state.android_connected]);

  useEffect(() => {
    if (state.ui_event_id === lastUiEvent.current) return;
    lastUiEvent.current = state.ui_event_id;
    const event = state.ui_event;
    if (event === 'expand_island' || event === 'show_main') {
      setExpanded(true);
      setView(state.external_approvals.length ? 'agents' : 'home');

    } else if (event === 'show_payments') {
      void expand('home');
      if (!muted && isTauri()) void invoke('play_notification_sound').catch(() => undefined);
    } else if (event === 'show_connections') {
      void expand('apps');
    } else if (event === 'compact_island' || event === 'show_bar' || event === 'hide_island' || event === 'hide_all') {
      setExpanded(false);

    } else if (event === 'show_island') {
      invoke('show_island').catch(() => undefined);

    }
  }, [state.ui_event_id, state.ui_event]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape' && expanded) collapse(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [expanded]);

  useEffect(() => {
    const fresh = state.external_approvals.some(item => !openedApprovals.current.has(item.id));
    state.external_approvals.forEach(item => openedApprovals.current.add(item.id));
    if (fresh) void expand('agents');
  }, [state.external_approvals]);

  const retry = async () => {
    if (state.transcript) await send(state.transcript);
    else { try { await linoApi.health(); await linoApi.show(); } catch (e) { console.error(e); } }
  };

  const body = useMemo(() => {
    if (view === 'chat') return <ChatView state={state} onSend={send} text={draft} onText={setDraft} busy={busy}/>;
    if (view === 'apps') return <AppsView connections={connections} refresh={refreshConnections} />;
    if (view === 'agents') return <AgentsView state={state} onAnswered={answered} />;
    if (view === 'settings') return <AppsView connections={connections} refresh={refreshConnections} />;
    if (state.external_approvals.length) return <ApprovalCard state={state} onAnswered={answered} />;
    if (state.status === 'error') return <ErrorCard state={state} onRetry={retry} onSettings={() => setView('apps')} />;
    return <Welcome status={state.status} text={draft} onText={setDraft} onSend={send} busy={busy}/>;
  }, [view, state, connections, draft, busy]);

  if (phase === 'compact') return <CompactIsland state={state} onOpen={() => expand(state.external_approvals.length ? 'agents' : 'home')} />;

  return (
    <div ref={shellRef} className={`island-shell island-shell--${phase}`} inert={phase === 'closing'}
      onPointerDown={event => { if (event.target === event.currentTarget) void collapse(); }}>
      <div className="island">
        <Header view={view} onView={setView} muted={muted} onMute={() => { void linoApi.muteVoice(!muted).catch(console.error); }} onClose={collapse} />
        <main className="island-body">{state.payment_notifications?.[0] && <div className="payment-banner" role="status"><span>{paymentLabel(state.payment_notifications[0])}</span><button className="button button--ghost" onClick={()=>void linoApi.paymentRead(state.payment_notifications![0].id).catch(console.error)}>Compris</button></div>}{body}</main>
      </div>
    </div>
  );
}
