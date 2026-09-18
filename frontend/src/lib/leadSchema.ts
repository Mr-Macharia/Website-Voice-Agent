/**
 * Validation for the lead-capture form.
 *
 * The limits mirror `LeadFormRequest` in `backend/server.py`, and the "name or
 * email" floor mirrors `capture_lead`. Both sides validate: the server because
 * /api/leads is reachable without the form, the client so the visitor is told
 * what is wrong before a round trip. Change one, change the other.
 */

import { z } from 'zod'

export const leadSchema = z
  .object({
    name: z.string().trim().max(200, 'That name is too long.'),
    email: z
      .string()
      .trim()
      .max(320, 'That email is too long.') // RFC 5321 maximum
      .refine((v) => v === '' || z.email().safeParse(v).success, {
        message: "That email doesn't look right."
      }),
    company: z.string().trim().max(200, 'That company name is too long.'),
    message: z.string().trim().max(4000, 'That message is too long.')
  })
  // capture_lead refuses to store a row it cannot identify anyone by, so the
  // form asks for one of the two rather than letting the submit fail server-side.
  .refine((v) => v.name !== '' || v.email !== '', {
    message: 'Add your name or your email.',
    path: ['name']
  })

export type LeadInput = z.infer<typeof leadSchema>

export type LeadErrors = Partial<Record<keyof LeadInput, string>>

/** Field-keyed errors, or null when the input is valid. */
export function validateLead(input: LeadInput): LeadErrors | null {
  const result = leadSchema.safeParse(input)
  if (result.success) return null

  const errors: LeadErrors = {}
  for (const issue of result.error.issues) {
    const key = issue.path[0] as keyof LeadInput | undefined
    // First error per field: showing three messages under one input is noise.
    if (key && !errors[key]) errors[key] = issue.message
  }
  return errors
}
