import { useEffect, useRef, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';

import type { ExternalApproval } from '../types';

export function useDesktopApprovals(muted: boolean) {
  const [approvals, setApprovals] = useState<ExternalApproval[]>([]);
  const [error, setError] = useState('');
  const answered = useRef(new Set<string>());
  const dismiss = (id: string) => { answered.current.add(id); setApprovals(items => items.filter(item => item.id !== id)); };
  const mutedRef = useRef(muted);
  mutedRef.current = muted;
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    let timer = 0;
    const announced = new Set<string>();
    const tick = async () => {
      try {
        const result = await invoke<{ approvals: ExternalApproval[] }>('scan_desktop_approvals');
        if (disposed) return;
        setApprovals(result.approvals.filter(item => !answered.current.has(item.id)));
        setError('');
        for (const item of result.approvals) {
          if (!announced.has(item.id) && !answered.current.has(item.id)) {
            announced.add(item.id);
            if (!mutedRef.current) void invoke('play_notification_sound').catch(() => undefined);
          }
        }
      } catch (e) {
        if (!disposed) { setApprovals([]); setError(String(e)); }
      } finally {
        if (!disposed) timer = window.setTimeout(tick, 250);
      }
    };
    void tick();
    return () => { disposed = true; window.clearTimeout(timer); };
  }, []);
  return { approvals, error, dismiss };
}
