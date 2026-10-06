import { useEffect, useState } from 'react';
import { useDesktopApprovals } from './lib/useDesktopApprovals';
import { Island } from './components/Island';
import { linoApi } from './lib/api';
import type { LinoState } from './types';

const initialState: LinoState = {
  status: 'ready',
  status_label: 'En veille',
  transcript: '',
  answer: '',
  actions: [],
  sources: [],
  external_approvals: [],
  approval_monitor: { ready: false, message: 'Démarrage…' },
  android_connected: false,
  awake: false,
  ui_event: 'none',
  ui_event_id: 0,
  updated_at: new Date().toISOString(),
};

export default function App() {
  const [state, setState] = useState<LinoState>(initialState);

  useEffect(() => {
    let mounted = true;
    const tick = async () => {
      try {
        const next = await linoApi.getState();
        if (!mounted) return;
        setState(next);
      } catch {
        if (mounted) setState((current) => ({ ...current, status: 'error', status_label: 'Core hors ligne', answer: 'Lino Core ne répond pas.' }));
      }
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => { mounted = false; window.clearInterval(id); };
  }, []);

  const send = async (message: string) => {
    setState((current) => ({ ...current, transcript: message, answer: '', status: 'thinking', status_label: 'Analyse' }));
    try {
      const response = await linoApi.chat(message);
      setState((current) => ({ ...current, answer: response.answer, actions: response.actions, sources: response.sources, awake: true }));
    } catch (error) {
      setState((current) => ({ ...current, status: 'error', status_label: 'Erreur', answer: error instanceof Error ? error.message : 'Erreur inconnue' }));
      throw error;
    }
  };

  const desktop = useDesktopApprovals(state.voice_muted ?? false);
  const combined = {
    ...state,
    external_approvals: [...desktop.approvals, ...state.external_approvals.filter(item => {
      if (item.source === 'mcp') return true;
      const family = (app: string) => /chatgpt|codex/i.test(app) ? 'openai' : app.toLowerCase();
      return !desktop.approvals.some(local => family(local.app) === family(item.app)) && !item.id.includes(':notification:');
    })].sort((a, b) => Number(Boolean(b.can_respond)) - Number(Boolean(a.can_respond))),
    approval_monitor: desktop.error ? { ready: false, message: desktop.error } : { ready: true, message: 'Demandes et notifications des applications' },
  };
  return <Island state={combined} onSend={send} onApprovalAnswered={desktop.dismiss} />;
}
