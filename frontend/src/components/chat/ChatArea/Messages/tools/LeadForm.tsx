'use client'

/**
 * The form shown when the agent needs the visitor's details.
 *
 * It posts straight to /api/leads rather than composing a sentence for the
 * model to re-transcribe into capture_lead: the visitor's own spelling of
 * their email is the one that matters, and a model paraphrasing it is a lost
 * lead.
 *
 * Takes a payload and calls back on success, so the voice modal can mount the
 * same component later if a form ever makes sense mid-call.
 */

import React, { useId, useRef, useState } from 'react'
import { Check, Loader2, Send } from 'lucide-react'
import * as LabelPrimitive from '@radix-ui/react-label'

import { Button } from '@/components/ui/button'
import { validateLead, type LeadErrors, type LeadInput } from '@/lib/leadSchema'
import type { LeadFormPayload } from '@/lib/toolPayload'

interface LeadFormProps {
  payload: LeadFormPayload
  endpoint: string
  sessionId?: string | null
  onSaved?: (leadId?: number) => void
}

type Status = 'editing' | 'submitting' | 'saved' | 'failed'

const FIELDS = [
  { key: 'name', label: 'Name', type: 'text', autoComplete: 'name' },
  { key: 'email', label: 'Email', type: 'email', autoComplete: 'email' },
  {
    key: 'company',
    label: 'Company',
    type: 'text',
    autoComplete: 'organization',
    optional: true
  }
] as const

export const LeadForm: React.FC<LeadFormProps> = ({
  payload,
  endpoint,
  sessionId,
  onSaved
}) => {
  const known = payload.known ?? {}
  const baseId = useId()
  const formRef = useRef<HTMLFormElement>(null)

  const [values, setValues] = useState<LeadInput>({
    name: known.name ?? '',
    email: known.email ?? '',
    company: known.company ?? '',
    message: known.message ?? ''
  })
  const [errors, setErrors] = useState<LeadErrors>({})
  const [status, setStatus] = useState<Status>('editing')
  const [failure, setFailure] = useState('')

  const disabled = status === 'submitting'

  const set = (key: keyof LeadInput) => (value: string) => {
    setValues((v) => ({ ...v, [key]: value }))
    // Clear the error as they fix it, rather than leaving a stale complaint.
    setErrors((e) => (e[key] ? { ...e, [key]: undefined } : e))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // Guard the double submit: a second row is worse than a slow click.
    if (status === 'submitting' || status === 'saved') return

    const found = validateLead(values)
    if (found) {
      setErrors(found)
      // Move focus to the first bad field so a keyboard or screen-reader user
      // lands on the problem instead of hunting for it.
      const firstKey = Object.keys(found)[0]
      formRef.current
        ?.querySelector<HTMLInputElement>(`[name="${firstKey}"]`)
        ?.focus()
      return
    }

    setStatus('submitting')
    setFailure('')
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...values, session_id: sessionId ?? null })
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data?.ok) {
        setStatus('saved')
        onSaved?.(data.lead_id)
        return
      }
      setStatus('failed')
      setFailure(
        typeof data?.message === 'string' && data.message
          ? data.message
          : "That didn't save. Try again in a moment."
      )
    } catch {
      setStatus('failed')
      setFailure("Couldn't reach the server. Check your connection and retry.")
    }
  }

  if (status === 'saved') {
    return (
      <div
        className="rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.07] p-3.5 backdrop-blur-md"
        role="status"
      >
        <div className="flex items-center gap-2.5">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
            <Check className="size-4" />
          </div>
          <p className="text-sm text-emerald-100">
            Thanks — your details are with Gichogu and he&apos;ll be in touch.
          </p>
        </div>
      </div>
    )
  }

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit}
      noValidate
      className="rounded-2xl border border-white/10 bg-white/[0.04] p-3.5 backdrop-blur-md"
    >
      <p className="font-large text-sm font-semibold text-white">
        Leave your details
      </p>
      <p className="mt-0.5 text-xs text-zinc-400">
        He&apos;ll get back to you directly.
      </p>

      <div className="mt-3 flex flex-col gap-2.5">
        {FIELDS.map((field) => {
          const id = `${baseId}-${field.key}`
          const errorId = `${id}-error`
          const error = errors[field.key]
          return (
            <div key={field.key} className="flex flex-col gap-1">
              <LabelPrimitive.Root
                htmlFor={id}
                className="font-mono text-[11px] uppercase tracking-wider text-zinc-400"
              >
                {field.label}
                {'optional' in field && field.optional ? (
                  <span className="ml-1 normal-case text-zinc-500">
                    (optional)
                  </span>
                ) : null}
              </LabelPrimitive.Root>
              <input
                id={id}
                name={field.key}
                type={field.type}
                autoComplete={field.autoComplete}
                disabled={disabled}
                value={values[field.key]}
                onChange={(e) => set(field.key)(e.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                className="rounded-xl border border-white/10 bg-[#0f172a]/80 px-3 py-2 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-600 focus:border-[#e85d04]/60 disabled:opacity-50 aria-[invalid=true]:border-rose-500/60"
              />
              {error ? (
                <p id={errorId} className="text-xs text-rose-300">
                  {error}
                </p>
              ) : null}
            </div>
          )
        })}

        <div className="flex flex-col gap-1">
          <LabelPrimitive.Root
            htmlFor={`${baseId}-message`}
            className="font-mono text-[11px] uppercase tracking-wider text-zinc-400"
          >
            Message
            <span className="ml-1 normal-case text-zinc-500">(optional)</span>
          </LabelPrimitive.Root>
          <textarea
            id={`${baseId}-message`}
            name="message"
            rows={3}
            disabled={disabled}
            value={values.message}
            onChange={(e) => set('message')(e.target.value)}
            aria-invalid={errors.message ? true : undefined}
            aria-describedby={
              errors.message ? `${baseId}-message-error` : undefined
            }
            className="resize-none rounded-xl border border-white/10 bg-[#0f172a]/80 px-3 py-2 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-600 focus:border-[#e85d04]/60 disabled:opacity-50 aria-[invalid=true]:border-rose-500/60"
          />
          {errors.message ? (
            <p id={`${baseId}-message-error`} className="text-xs text-rose-300">
              {errors.message}
            </p>
          ) : null}
        </div>
      </div>

      {/* Assertive: a failed submit is the one thing they must not miss. */}
      <div aria-live="assertive" className="empty:hidden">
        {status === 'failed' && failure ? (
          <p className="mt-2.5 text-xs text-rose-300">{failure}</p>
        ) : null}
      </div>

      <Button
        type="submit"
        disabled={disabled}
        className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-[#e85d04]/40 bg-[#e85d04]/15 px-3 py-1.5 text-xs text-orange-200 transition-all hover:border-[#e85d04] hover:bg-[#e85d04]/25 hover:text-white disabled:opacity-60"
      >
        {disabled ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Send className="size-3.5" />
        )}
        <span>
          {disabled ? 'Sending…' : status === 'failed' ? 'Retry' : 'Send'}
        </span>
      </Button>
    </form>
  )
}

LeadForm.displayName = 'LeadForm'

export default LeadForm
