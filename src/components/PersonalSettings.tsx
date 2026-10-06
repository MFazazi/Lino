import { useEffect, useState } from 'react';
import { linoApi } from '../lib/api';
import { ServiceIcon } from './ServiceIcon';
import type { PaymentNotification } from '../types';

export function paymentLabel(n:PaymentNotification) {
  const currency=n.currency.toUpperCase();
  try {
    const formatter=new Intl.NumberFormat('fr-FR',{style:'currency',currency});
    const digits=['ISK','UGX'].includes(currency)?2:(formatter.resolvedOptions().maximumFractionDigits ?? 2);
    return `${n.livemode?'Paiement reçu':'Paiement de test'} · ${formatter.format(n.amount / 10**digits)}`;
  } catch {return `${n.livemode?'Paiement reçu':'Paiement de test'} · ${n.amount} unités (${currency})`;}
}

export function PersonalSettings() {
  const [stripe,setStripe]=useState<Awaited<ReturnType<typeof linoApi.stripeStatus>>|null>(null);
  const [key,setKey]=useState('');const [roots,setRoots]=useState('');const [active,setActive]=useState<string[]>([]);
  const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
  useEffect(()=>{
    let alive=true;
    const refresh=()=>linoApi.stripeStatus().then(s=>{if(alive)setStripe(s);}).catch(()=>{});
    void refresh();const timer=window.setInterval(()=>void refresh(),5000);
    void linoApi.fileRoots().then(s=>{if(alive){setRoots(s.custom_roots.join('\n'));setActive(s.roots);}}).catch(()=>{});
    return ()=>{alive=false;clearInterval(timer);};
  },[]);
  const run=async(action:()=>Promise<unknown>,success:string)=>{
    setBusy(true);setMessage('');
    try{await action();setMessage(success);setStripe(await linoApi.stripeStatus());}
    catch(e){setMessage(e instanceof Error?e.message:'Action impossible.');}finally{setBusy(false);}
  };
  return <div className="personal-settings">
    <section className="personal-setting"><h3><ServiceIcon name="Stripe"/>Stripe · Paiements</h3>
      <p>{stripe?.connected?`Surveillance active · ${stripe.mode==='test'?'mode test':'paiements réels'} · toutes les 30 secondes lorsque Lino est ouvert.`:'Reçois une alerte dans Lino à chaque nouveau paiement. Connecte une clé Stripe restreinte avec accès en lecture aux événements.'}</p>
      {stripe?.error&&<p role="alert">{stripe.error}</p>}
      {stripe?.connected?<button className="button button--ghost" disabled={busy} onClick={()=>void run(()=>linoApi.stripeDisconnect(),'Stripe déconnecté.')}>Déconnecter Stripe</button>:<form onSubmit={e=>{e.preventDefault();void run(async()=>{await linoApi.stripeConnect(key);setKey('');},'Stripe connecté. Les nouveaux paiements seront signalés.');}}><input aria-label="Clé API Stripe" type="password" autoComplete="off" placeholder="rk_live_… ou rk_test_…" required value={key} onChange={e=>setKey(e.target.value)}/><button disabled={busy} className="button button--light">{busy?'Connexion…':'Connecter Stripe'}</button></form>}
      <p>Clé chiffrée par Windows, enregistrée uniquement sur ce PC.</p>
      {stripe?.notifications.slice(0,5).map(n=><p key={n.id}>{paymentLabel(n)} · {new Date(n.created*1000).toLocaleString('fr-FR')}</p>)}
    </section>
    <section className="personal-setting"><h3>Fichiers du PC</h3><p>Retrouve tes factures et documents par nom, puis demande à Lino de lire un PDF ou de l’ouvrir.</p><details><summary>Dossiers parcourus ({active.length})</summary>{active.map(p=><p key={p}>{p}</p>)}</details><p>Ajoute tes dossiers, un chemin complet par ligne.</p><form onSubmit={e=>{e.preventDefault();void run(async()=>{await linoApi.saveFileRoots(roots.split('\n').map(p=>p.trim()).filter(Boolean));setActive((await linoApi.fileRoots()).roots);},'Dossiers de recherche enregistrés.');}}><textarea aria-label="Dossiers supplémentaires" placeholder={'D:\\Factures'} value={roots} onChange={e=>setRoots(e.target.value)}/><button className="button button--ghost" disabled={busy}>Enregistrer</button></form></section>
    {message&&<p className="settings-message" role="status">{message}</p>}
  </div>;
}
