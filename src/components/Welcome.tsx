import { ChevronRight, FileText, Lightbulb, ListTodo, Search } from 'lucide-react';
import { Composer } from './Composer';
import { Mascot } from './Mascot';
import type { LinoStatus } from '../types';

const shortcuts=[
  {icon:Search,label:'Rechercher une information',description:'Obtenez des réponses claires et fiables.',draft:'Recherche une information sur ',color:'blue'},
  {icon:FileText,label:'Résumer un document',description:'Extrayez l’essentiel en quelques secondes.',draft:'Résume le document PDF suivant : ',color:'purple'},
  {icon:Lightbulb,label:'Générer une idée',description:'Explorez de nouvelles perspectives créatives.',draft:'Aide-moi à trouver des idées pour ',color:'gold'},
  {icon:ListTodo,label:'Vous accompagner dans une tâche',description:'Avancez plus vite, plus simplement.',draft:'Aide-moi à ',color:'green'},
];
export function Welcome({status,text,onText,onSend,busy}:{status:LinoStatus;text:string;onText:(s:string)=>void;onSend:(s:string)=>Promise<void>;busy:boolean}){
 const choose=(draft:string)=>{onText(draft);requestAnimationFrame(()=>document.querySelector<HTMLInputElement>('.welcome input[aria-label="Message à Lino"]')?.focus());};
 return <section className="welcome">
   <div className="welcome-hero"><div className="welcome-art"><Mascot status={busy && status === 'ready' ? 'thinking' : status}/></div><div className="welcome-greeting"><h1>Bonjour !</h1><p>Comment puis-je vous aider aujourd’hui ?</p></div></div>
   <div className="welcome-shortcuts">{shortcuts.map(({icon:Icon,label,description,draft,color})=><button key={color} className={`welcome-shortcut welcome-shortcut--${color}`} onClick={()=>choose(draft)}><span className="shortcut-icon"><Icon size={22}/></span><span className="shortcut-title">{label}</span><ChevronRight className="shortcut-arrow" size={17}/><span className="shortcut-description">{description}</span></button>)}</div>
   <Composer text={text} onText={onText} onSend={onSend} busy={busy}/>
 </section>;
}
