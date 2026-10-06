"""Read-only Stripe event polling, encrypted key, persistent cursor and notifications."""
import asyncio
import time
from contextlib import suppress
import httpx
from services.mcp_connections import SecureStorage
from user_config import app_data_dir
from state import runtime


class StripeMonitor:
    def __init__(self, storage=None):
        self.storage=storage or SecureStorage(app_data_dir() / 'stripe.dpapi')
        self.data={}; self.error=''; self.checked=None; self.task=None
        self.lock=asyncio.Lock()

    def snapshot(self):
        return {'connected':bool(self.data.get('key')), 'error':self.error,
                'mode':'test' if '_test_' in self.data.get('key','') else 'live',
                'last_checked':self.checked,'interval_seconds':30,
                'notifications':self.data.get('notifications',[])}

    def publish(self):
        runtime.update(payment_notifications=[dict(n) for n in self.data.get('notifications',[]) if not n.get('read')])

    async def events(self,key,params):
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.get('https://api.stripe.com/v1/events',auth=(key,''),params=params)
            if response.status_code in (401,403):
                raise ValueError('Clé Stripe refusée. Vérifie son accès en lecture aux événements.')
            if response.status_code != 200:
                raise ValueError(f'Stripe indisponible (HTTP {response.status_code}). Nouvelle tentative automatique.')
            return response.json()

    async def connect(self,key):
        key=key.strip()
        if not key.startswith(('rk_live_','rk_test_','sk_live_','sk_test_')):
            raise ValueError('Saisis une clé API Stripe secrète ou restreinte, avec accès en lecture aux événements.')
        async with self.lock:
            started=int(time.time())
            await self.events(key,{'limit':1,'type':'payment_intent.succeeded'})
            candidate=self.data if self.data.get('key') == key else {'key':key,'since':started,'cursor':started,'seen':[], 'notifications':[]}
            self.storage.save(candidate);self.data=candidate;self.error='';self.publish()
        return self.snapshot()

    async def disconnect(self):
        async with self.lock:
            self.storage.save({});self.data={};self.error='';self.publish()
        return self.snapshot()

    async def acknowledge(self,event_id):
        async with self.lock:
            for item in self.data.get('notifications',[]):
                if item['id']==event_id: item['read']=True
            self.storage.save(self.data);self.publish()
        return self.snapshot()

    async def poll(self):
        async with self.lock:
            key=self.data.get('key')
            if not key:return
            # Overlap covers equal timestamps and delayed visibility. Pagination is fully drained
            # before advancing the watermark, so a burst of >100 payments is not dropped.
            lower=max(self.data.get('since',0), self.data.get('cursor',0)-120)
            params={'limit':100,'type':'payment_intent.succeeded','created[gte]':lower}
            events=[]
            while True:
                page=await self.events(key,params);batch=page.get('data',[]);events.extend(batch)
                if not page.get('has_more'):break
                if not batch:raise ValueError('Pagination Stripe incomplète, nouvelle tentative automatique.')
                params['starting_after']=batch[-1]['id']
            seen={item['id']:item['created'] for item in self.data.get('seen',[])}
            notices=list(self.data.get('notifications',[]));fresh=False
            cursor=self.data.get('cursor',lower)
            for event in sorted(events,key=lambda e:(e['created'],e['id'])):
                cursor=max(cursor,event['created'])
                if event['id'] in seen:continue
                seen[event['id']]=event['created']
                if event.get('type') != 'payment_intent.succeeded':continue
                obj=event['data']['object']
                notices.insert(0,{'id':event['id'],'payment_id':obj['id'],'amount':obj.get('amount_received',obj.get('amount',0)),
                    'currency':obj.get('currency','eur'),'created':event['created'],'livemode':event.get('livemode',False),'read':False})
                fresh=True
            candidate={**self.data,'cursor':cursor,'seen':[{'id':i,'created':t} for i,t in seen.items() if t>=cursor-120],'notifications':notices[:50]}
            self.storage.save(candidate);self.data=candidate;self.checked=int(time.time());self.error='';self.publish()
            if fresh:runtime.request_ui('show_payments')

    async def run(self):
        while True:
            try:await self.poll()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.error=str(exc) if isinstance(exc,ValueError) else 'Connexion Stripe interrompue. Nouvelle tentative dans 30 secondes.'
            await asyncio.sleep(30)

    async def start(self):
        try:self.data=self.storage.load()
        except Exception:self.error='Impossible de lire la connexion Stripe. Reconnecte ton compte.'
        self.publish();self.task=asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):await self.task


stripe_monitor=StripeMonitor()
