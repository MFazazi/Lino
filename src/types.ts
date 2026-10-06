export type LinoStatus = 'ready' | 'listening' | 'thinking' | 'acting' | 'speaking' | 'error';
export type IslandView = 'home' | 'chat' | 'apps' | 'agents' | 'settings';

export interface SourceItem {
  id: string;
  title: string;
  url: string;
  domain: string;
  snippet?: string;
  age?: string | null;
}

export interface ActionItem {
  id: string;
  label: string;
  detail?: string;
  state: 'pending' | 'running' | 'done' | 'error';
  tool?: string;
}

export interface ExternalApproval {
  id: string;
  app: 'Claude' | 'Codex' | string;
  title: string;
  message: string;
  detected_at: string;
  source?: 'hook' | 'visual' | 'test' | 'desktop' | 'mcp';
  can_respond?: boolean;
  allow_label?: string;
  deny_label?: string;
}

export interface ApprovalMonitor {
  ready: boolean;
  message: string;
}

export interface PaymentNotification { id:string; payment_id:string; amount:number; currency:string; created:number; livemode:boolean; read:boolean }

export interface LinoState {
  payment_notifications?: PaymentNotification[];
  status: LinoStatus;
  status_label: string;
  transcript: string;
  answer: string;
  actions: ActionItem[];
  sources: SourceItem[];
  external_approvals: ExternalApproval[];
  approval_monitor: ApprovalMonitor;
  android_connected: boolean;
  awake: boolean;
  voice_muted?: boolean;
  ui_event: 'none' | 'expand_island' | 'show_island' | 'compact_island' | 'hide_island' | string;
  ui_event_id: number;
  updated_at: string;
}

export interface ChatResponse {
  answer: string;
  actions: ActionItem[];
  sources: SourceItem[];
}

export interface HealthResponse {
  ok: boolean;
  version: string;
  model: string;
  web_enabled: boolean;
  web_mode?: 'automatic' | 'brave' | string;
  awake: boolean;
  voice_muted?: boolean;
  android_connected: boolean;
  approval_monitor?: ApprovalMonitor;
  external_approvals?: ExternalApproval[];
  gmail: {
    connected?: boolean;
    ready_to_connect?: boolean;
    needs_setup?: boolean;
    account?: string | null;
    message?: string;
  };
  tts: {
    enabled?: boolean;
    backend?: string;
    ready?: boolean;
    last_error?: string;
  };
}

export interface ConnectionSnapshot {
  ok: boolean;
  gmail: {
    connected: boolean;
    ready_to_connect: boolean;
    needs_setup: boolean;
    account?: string | null;
    message?: string;
  };
  web: {
    connected: boolean;
    mode: string;
    detail: string;
  };
  n8n: {
    connected: boolean;
    url: string;
  };
  phone: {
    connected: boolean;
    detail: string;
  };
  voice: {
    connected: boolean;
    backend: string;
  };
}
