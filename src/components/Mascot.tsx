import { type CSSProperties, useEffect, useRef, useState } from 'react';
import type { LinoStatus } from '../types';
import mascotImage from '../assets/lino-blob.png';

export function Mascot({ status, compact = false }: { status: LinoStatus; compact?: boolean }) {
  const [blink, setBlink] = useState(false);
  const [boop, setBoop] = useState(false);
  const [look, setLook] = useState({ x: 0, y: 0 });
  const timer = useRef<number | null>(null);
  const blinkEnd = useRef<number | null>(null);
  const boopEnd = useRef<number | null>(null);
  const mood = status === 'acting' ? 'searching' : status;

  useEffect(() => {
    let cancelled = false;
    const schedule = () => {
      const delay = 2300 + Math.random() * 3600;
      timer.current = window.setTimeout(() => {
        if (cancelled) return;
        setBlink(true);
        blinkEnd.current = window.setTimeout(() => {
          if (cancelled) return;
          setBlink(false);
          if (!cancelled) schedule();
        }, 135);
      }, delay);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
      if (blinkEnd.current) window.clearTimeout(blinkEnd.current);
      if (boopEnd.current) window.clearTimeout(boopEnd.current);
    };
  }, []);

  const poke = () => {
    setBoop(true);
    if (boopEnd.current) window.clearTimeout(boopEnd.current);
    boopEnd.current = window.setTimeout(() => setBoop(false), 380);
  };

  return (
    <div
      className={`lino-creature lino-creature--${mood}${compact ? ' lino-creature--compact' : ''}${blink ? ' is-blinking' : ''}${boop ? ' is-booped' : ''}`}
      aria-label={`Lino — ${mood}`}
      role={compact ? undefined : 'button'}
      tabIndex={compact ? undefined : 0}
      title={compact ? undefined : 'Fais coucou à Lino'}
      style={{ '--look-x': `${look.x}px`, '--look-y': `${look.y}px` } as CSSProperties}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        setLook({ x: ((event.clientX - box.left) / box.width - .5) * 10, y: ((event.clientY - box.top) / box.height - .5) * 6 });
      }}
      onPointerEnter={poke}
      onPointerLeave={() => setLook({ x: 0, y: 0 })}
      onKeyDown={(event) => {
        if (!compact && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); poke(); }
      }}
      onClick={(event) => { if (!compact) event.stopPropagation(); poke(); }}
    >
      <div className="lino-creature__shadow" />
      <div className="lino-creature__body">
        <div className="lino-creature__face">
          <img src={mascotImage} alt="" draggable={false} />
          <span className="lino-creature__lid lino-creature__lid--left" />
          <span className="lino-creature__lid lino-creature__lid--right" />
        </div>

      </div>
      <div className="lino-creature__thought" aria-hidden="true"><i /><i /><i /></div>
      <div className="lino-creature__listen" aria-hidden="true"><i /><i /><i /></div>
      <div className="lino-creature__voice" aria-hidden="true"><i /><i /><i /></div>
      <div className="lino-creature__alert" aria-hidden="true">!</div>
    </div>
  );
}

