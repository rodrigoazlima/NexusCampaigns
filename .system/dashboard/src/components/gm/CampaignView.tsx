'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { CampaignFrame } from '@/lib/types'
import type { CampaignData } from '@/lib/campaign'
import { PILLARS } from '@/lib/pillars'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import { Tip } from './Tip'
import {
  Dices, Sparkles, ArrowRight, Pencil, Play, Check, X, Loader2,
  CheckCircle2, Circle, Link2, AlertTriangle, Save,
} from 'lucide-react'

const TONES = ['grim', 'heroic', 'intrigue', 'survival', 'mystery', 'horror', 'exploration', 'comedy']
const SCALES = ['valley', 'city', 'region', 'continent']
const SELECT_CLS = 'text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors'
const INPUT_CLS = 'w-full text-xs bg-surface-3 border border-surface-3 text-zinc-200 px-2.5 py-2 rounded outline-none focus:border-primary/40 transition-colors'

interface Toast { message: string; type: 'success' | 'error' }

const EMPTY: Omit<CampaignFrame, 'active'> = {
  id: '', pitch: '', tone_primary: '', tone_secondary: '', scale: '', central_tension: '', player_buyin: '',
}

function ReadinessRing({ passed, total }: { passed: number; total: number }) {
  const r = 34
  const c = 2 * Math.PI * r
  const pct = total ? passed / total : 0
  const done = passed === total
  const color = done ? 'text-success' : passed >= total - 1 ? 'text-warning' : 'text-primary'
  return (
    <div className="relative w-24 h-24 flex-shrink-0">
      <svg className="w-24 h-24 -rotate-90" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r={r} className="stroke-surface-3" strokeWidth="6" fill="none" />
        <circle
          cx="40" cy="40" r={r} strokeWidth="6" fill="none" strokeLinecap="round"
          className={`${color} transition-all`} stroke="currentColor"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-lg font-bold font-mono ${color}`}>{passed}/{total}</span>
        <span className="text-[9px] uppercase tracking-wide text-zinc-500">ready</span>
      </div>
    </div>
  )
}

export default function CampaignView({ data, frame }: { data: CampaignData; frame: CampaignFrame | null }) {
  const router = useRouter()
  const [toast, setToast] = useState<Toast | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<Omit<CampaignFrame, 'active'>>(frame ?? EMPTY)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const passed = data.checks.filter((c) => c.ok).length
  const total = data.checks.length
  const allReady = passed === total

  const openEditor = () => { setForm(frame ?? EMPTY); setEditing(true) }

  const save = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/gm/campaign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const d = await res.json()
      if (d.ok) { showToast('Setting frame saved', 'success'); setEditing(false); router.refresh() }
      else showToast(d.error ?? 'Save failed', 'error')
    } catch {
      showToast('Save failed', 'error')
    } finally {
      setSaving(false)
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Dices}
        title="Campaign Setting"
        subtitle={frame?.pitch || 'Untitled setting — is it ready to run?'}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={openEditor}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-3 text-zinc-300 hover:text-white border border-surface-3 transition-colors"
            >
              <Pencil size={13} /> Edit frame
            </button>
            <Tip label={allReady ? 'Session-zero summary — coming soon' : `Pass all ${total} checks to run`}>
              <button
                onClick={() => allReady ? showToast('Session-zero summary — coming soon', 'success') : undefined}
                disabled={!allReady}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                  allReady
                    ? 'bg-success/15 text-success border-success/30 hover:bg-success/25'
                    : 'bg-surface-3 text-zinc-600 border-surface-3 cursor-not-allowed'
                }`}
              >
                <Play size={13} /> Run
              </button>
            </Tip>
          </div>
        }
      />

      {/* Needs-you banner */}
      {data.unreviewed > 0 && (
        <Link
          href="/gm/review"
          className="panel flex items-center gap-3 p-3 mb-5 border border-warning/30 bg-warning/5 hover:bg-warning/10 transition-colors group"
        >
          <Sparkles size={18} className="text-warning flex-shrink-0" />
          <span className="text-sm text-zinc-200 flex-1">
            <span className="font-semibold text-warning">{data.unreviewed}</span> fresh{' '}
            {data.unreviewed === 1 ? 'draft is' : 'drafts are'} waiting for your review
          </span>
          <span className="text-xs text-zinc-500 group-hover:text-warning flex items-center gap-1">
            Review <ArrowRight size={14} />
          </span>
        </Link>
      )}

      {/* Frame editor (inline) */}
      {editing && (
        <div className="panel p-4 mb-5 border border-primary/30">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-semibold text-zinc-100">Setting frame</span>
            <button onClick={() => setEditing(false)} className="text-zinc-500 hover:text-zinc-300"><X size={16} /></button>
          </div>
          <div className="space-y-3">
            <div>
              <label className="text-[11px] text-zinc-500 mb-1 block">Pitch — say it in one line</label>
              <input value={form.pitch} onChange={set('pitch')} placeholder="Frontier town bought out by a death cult that pays in gold" className={INPUT_CLS} />
            </div>
            <div className="flex flex-wrap gap-3">
              <div>
                <label className="text-[11px] text-zinc-500 mb-1 block">Primary tone</label>
                <select value={form.tone_primary} onChange={set('tone_primary')} className={SELECT_CLS}>
                  <option value="">—</option>
                  {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-zinc-500 mb-1 block">Secondary tone</label>
                <select value={form.tone_secondary} onChange={set('tone_secondary')} className={SELECT_CLS}>
                  <option value="">—</option>
                  {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-zinc-500 mb-1 block">Scale</label>
                <select value={form.scale} onChange={set('scale')} className={SELECT_CLS}>
                  <option value="">—</option>
                  {SCALES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="text-[11px] text-zinc-500 mb-1 block">Central tension — what is wrong in this world right now</label>
              <textarea value={form.central_tension} onChange={set('central_tension')} rows={2} className={INPUT_CLS} />
            </div>
            <div>
              <label className="text-[11px] text-zinc-500 mb-1 block">Player buy-in — what characters this setting invites</label>
              <textarea value={form.player_buyin} onChange={set('player_buyin')} rows={2} className={INPUT_CLS} />
            </div>
            <div className="flex justify-end">
              <button onClick={save} disabled={saving} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-success/15 text-success border border-success/30 hover:bg-success/25 transition-colors disabled:opacity-50">
                {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save frame
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Frame card + readiness ring */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
        <div className="panel p-4 lg:col-span-2">
          {frame ? (
            <>
              <div className="text-sm text-zinc-100 font-medium mb-2">{frame.pitch || 'Untitled setting'}</div>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {[frame.tone_primary, frame.tone_secondary, frame.scale].filter(Boolean).map((t) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-surface-3 text-zinc-400 capitalize">{t}</span>
                ))}
              </div>
              {frame.central_tension && (
                <p className="text-xs text-zinc-400 leading-relaxed border-l-2 border-surface-4 pl-3">{frame.central_tension}</p>
              )}
            </>
          ) : (
            <div className="text-center py-4">
              <div className="text-sm text-zinc-300 mb-1">Start your setting</div>
              <p className="text-xs text-zinc-500 mb-3">Say it in one line — the pitch constrains every choice after.</p>
              <button onClick={openEditor} className="text-xs px-3 py-1.5 rounded bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors">
                + Set the frame
              </button>
            </div>
          )}
        </div>
        <div className="panel p-4 flex items-center gap-4">
          <ReadinessRing passed={passed} total={total} />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-zinc-100">
              {allReady ? 'Ready to run' : `${total - passed} blocker${total - passed === 1 ? '' : 's'}`}
            </div>
            <p className="text-xs text-zinc-500 mt-0.5">
              {allReady ? 'This setting is ready to run.' : 'Clear the checklist below.'}
            </p>
            <div className="text-[11px] text-zinc-600 mt-2">
              {data.totals.entities} entities · {data.totals.drafts} drafts · {data.totals.canon} canon
            </div>
          </div>
        </div>
      </div>

      {/* Pillar progress grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-5">
        {PILLARS.map((p) => {
          const stat = data.pillars.find((s) => s.key === p.key)!
          const Icon = p.icon
          return (
            <Link key={p.key} href={p.href} className="panel p-4 border border-surface-3 hover:border-surface-4 transition-colors group">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-surface-3 flex items-center justify-center flex-shrink-0">
                  <Icon size={18} className={p.accent} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-zinc-200 truncate group-hover:text-white">{p.label}</span>
                    <span className={`text-base font-mono font-bold ${p.accent}`}>{stat.count}</span>
                    {stat.waiting > 0 && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-warning/15 text-warning font-medium">{stat.waiting} new</span>
                    )}
                  </div>
                  <p className="text-[11px] text-zinc-500 mt-0.5 truncate">{p.hint}</p>
                </div>
                <ArrowRight size={14} className="text-zinc-600 group-hover:text-zinc-300 group-hover:translate-x-0.5 transition-all flex-shrink-0" />
              </div>
              <div className="mt-3 h-1.5 rounded-full bg-surface-3 overflow-hidden">
                <div className={`h-full rounded-full ${stat.pct >= 100 ? 'bg-success' : 'bg-primary'}`} style={{ width: `${stat.pct}%` }} />
              </div>
            </Link>
          )
        })}
      </div>

      {/* Readiness checklist */}
      <div className="panel mb-5">
        <div className="px-4 py-2.5 border-b border-surface-3/60 text-xs font-semibold text-zinc-300">
          Readiness — ready to run when all seven pass
        </div>
        {data.checks.map((c) => (
          <div key={c.id} className="flex items-center gap-3 px-4 py-2.5 border-b border-surface-3/40 last:border-0">
            {c.ok
              ? <CheckCircle2 size={16} className="text-success flex-shrink-0" />
              : <Circle size={16} className="text-warning flex-shrink-0" />}
            <div className="flex-1 min-w-0">
              <div className={`text-xs ${c.ok ? 'text-zinc-300' : 'text-zinc-200'}`}>{c.label}</div>
              <div className="text-[11px] text-zinc-500">{c.detail}</div>
            </div>
            {!c.ok && (
              <Link href={c.fixHref} className="text-[11px] text-primary hover:underline flex items-center gap-0.5 flex-shrink-0">
                Fix it <ArrowRight size={11} />
              </Link>
            )}
          </div>
        ))}
      </div>

      {/* Wiring health */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="panel p-4">
          <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1">
            {data.wiring.orphans > 0 ? <AlertTriangle size={14} className="text-warning" /> : <Check size={14} className="text-success" />}
            Orphans
          </div>
          <div className={`text-xl font-mono font-bold ${data.wiring.orphans > 0 ? 'text-warning' : 'text-success'}`}>{data.wiring.orphans}</div>
          <p className="text-[11px] text-zinc-600 mt-0.5">entities with no relationships</p>
        </div>
        <div className="panel p-4">
          <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1">
            <Dices size={14} className="text-purple-400" /> Faction clocks
          </div>
          <div className="text-xl font-mono font-bold text-zinc-200">{data.wiring.factionClocks}</div>
          <p className="text-[11px] text-zinc-600 mt-0.5">factions that advance when ignored</p>
        </div>
        <div className="panel p-4">
          <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1">
            <Link2 size={14} className="text-primary" /> One thread
          </div>
          <div className="text-xs font-mono text-zinc-200 truncate mt-1">{data.wiring.thread ?? '—'}</div>
          <p className="text-[11px] text-zinc-600 mt-0.5">
            {data.wiring.thread ? 'links across 3+ pillars' : 'no thread spans 3+ pillars yet'}
          </p>
        </div>
      </div>

      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-lg text-sm font-medium z-50 shadow-lg ${toast.type === 'success' ? 'bg-success text-white' : 'bg-danger text-white'}`}>
          {toast.message}
        </div>
      )}
    </div>
  )
}
