import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react';
import { LoaderCircle, Mic, Paperclip, Send, Square } from 'lucide-react';
import { linoApi } from '../lib/api';

export function Composer({text,onText,onSend,busy=false}: {text:string;onText:(text:string)=>void;onSend:(text:string)=>Promise<void>;busy?:boolean}) {
  const [error,setError]=useState('');const [working,setWorking]=useState(false);const [recording,setRecording]=useState(false);
  const picker=useRef<HTMLInputElement>(null);const input=useRef<HTMLInputElement>(null);
  const recorder=useRef<MediaRecorder|null>(null);const stream=useRef<MediaStream|null>(null);const timer=useRef<number>(0);const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;clearTimeout(timer.current);if(recorder.current?.state==='recording')recorder.current.stop();stream.current?.getTracks().forEach(t=>t.stop());};},[]);
  const submit=async(e:FormEvent)=>{e.preventDefault();if(!text.trim()||busy||working)return;setError('');setWorking(true);try{await onSend(text.trim());onText('');}catch(e){setError(e instanceof Error?e.message:'Envoi impossible.');}finally{if(mounted.current)setWorking(false);}};
  const attach=async(e:ChangeEvent<HTMLInputElement>)=>{
    const file=e.target.files?.[0];e.target.value='';if(!file)return;
    if(file.size>50*1024*1024){setError('Choisis un PDF de moins de 50 Mo.');return;}
    setWorking(true);setError('');
    try{const result=await linoApi.uploadDocument(file);onText(`Résume ce PDF : "${result.path}"`);input.current?.focus();}
    catch(e){setError(e instanceof Error?e.message:'Ajout du document impossible.');}finally{setWorking(false);}
  };
  const microphone=async()=>{
    if(recorder.current?.state==='recording'){recorder.current.stop();return;}
    setError('');
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){setError('Le microphone est indisponible ici. Utilise la saisie ou ton micro Android.');return;}
    try{
      stream.current=await navigator.mediaDevices.getUserMedia({audio:true});
      const rec=new MediaRecorder(stream.current);recorder.current=rec;const chunks:Blob[]=[];
      rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      rec.onstop=async()=>{clearTimeout(timer.current);stream.current?.getTracks().forEach(t=>t.stop());if(!mounted.current)return;setRecording(false);setWorking(true);
        try{const result=await linoApi.dictate(new Blob(chunks,{type:rec.mimeType}));if(mounted.current){onText(result.transcript);input.current?.focus();}}
        catch(e){if(mounted.current)setError(e instanceof Error?e.message:'Transcription impossible.');}finally{if(mounted.current)setWorking(false);}
      };
      rec.start();setRecording(true);timer.current=window.setTimeout(()=>{if(rec.state==='recording')rec.stop();},60000);
    }catch{stream.current?.getTracks().forEach(t=>t.stop());setError('Accès au microphone refusé ou microphone indisponible.');}
  };
  return <div className="composer-wrap">
    {error&&<p className="composer-error" role="alert">{error}</p>}
    <form className={`lino-composer ${recording?'is-recording':''}`} onSubmit={submit}>
      <input ref={picker} type="file" accept="application/pdf,.pdf" hidden onChange={attach}/>
      <button type="button" className="composer-attach" aria-label="Joindre un PDF" title="Joindre un PDF" disabled={busy||working||recording} onClick={()=>picker.current?.click()}><Paperclip size={19}/></button>
      <input ref={input} aria-label="Message à Lino" value={text} onChange={e=>onText(e.target.value)} placeholder={recording?'Je t’écoute… Arrête le micro pour transcrire.':'Posez votre question à Lino…'} disabled={busy||working||recording}/>
      <button type="button" aria-label={recording?'Arrêter le microphone':'Dicter un message'} title={recording?'Arrêter':'Dicter un message'} disabled={busy||working} className="composer-mic" onClick={()=>void microphone()}>{recording?<Square size={16}/>:<Mic size={18}/>}</button>
      <button className="composer-send" type="submit" aria-label="Envoyer le message" disabled={!text.trim()||busy||working||recording}>{working||busy?<LoaderCircle size={17} className="spin"/>:<Send size={17}/>}</button>
    </form>
  </div>;
}
