import { Globe2, Link2, Smartphone } from 'lucide-react';
import gmail from '../assets/services/gmail.png';
import docs from '../assets/services/google-docs.ico';
import notion from '../assets/services/notion.svg';
import n8n from '../assets/services/n8n.svg';
import stripe from '../assets/services/stripe.svg';
import github from '../assets/services/github.svg';

const logos: Record<string, { source: string; brand: string }> = {
  gmail: { source: gmail, brand: 'gmail' },
  'google docs': { source: docs, brand: 'docs' },
  googledocs: { source: docs, brand: 'docs' },
  notion: { source: notion, brand: 'notion' },
  n8n: { source: n8n, brand: 'n8n' },
  stripe: { source: stripe, brand: 'stripe' },
  github: { source: github, brand: 'github' },
};

/** Brand artwork is bundled locally; generic icons are only used for non-brand services. */
export function ServiceIcon({ name }: { name: string }) {
  const service = name.trim().toLowerCase();
  const logo = logos[service];
  const brand = logo?.brand ?? (service === 'web' ? 'web' : service === 'téléphone' ? 'phone' : 'generic');
  return <span className={`service-icon service-icon--${brand}`} aria-hidden="true">
    {logo ? <img src={logo.source} alt="" draggable={false}/> : service === 'web' ? <Globe2/> : service === 'téléphone' ? <Smartphone/> : <Link2/>}
  </span>;
}
