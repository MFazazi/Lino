import { linoApi } from '../lib/api';
import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import type { ExternalApproval } from '../types';

export function ApprovalActions({ approval, onAnswered }: { approval: ExternalApproval; onAnswered: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  if (!approval.can_respond) return <div className="approval-unavailable"><strong>Notification reçue · réponse indisponible ici</strong><small>Ouvre la demande dans {approval.app}. Lino affichera ses boutons dès qu’ils seront accessibles.</small></div>;
  const answer = async (decision: 'allow' | 'deny') => {
    setBusy(true);
    try {
      const result = approval.source === 'mcp' ? await linoApi.mcpDecision(approval.id, decision) : await invoke<{message: string}>('answer_desktop_approval', { id: approval.id, decision });
      setMessage(result.message);
      onAnswered(approval.id);
    } catch (e) {
      setMessage(String(e));
      // An uncertain result must be checked in the source app, not retried blindly.
    }
  };
  return <div className="approval-response">
    <div className="hero-card__actions">
      <button className="button button--light" disabled={busy} onClick={() => void answer('allow')}>Autoriser une fois</button>
      <button className="button button--ghost" disabled={busy} onClick={() => void answer('deny')}>Refuser</button>
    </div>
    <small className="approval-hint">Cette demande uniquement</small>
    {message && <div className="approval-error" role="status">{message}</div>}
  </div>;
}
