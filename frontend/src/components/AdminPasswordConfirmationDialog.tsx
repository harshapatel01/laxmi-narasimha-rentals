import type { FormEventHandler } from 'react'
import { X } from 'lucide-react'

interface AdminPasswordConfirmationDialogProps {
  idPrefix: string
  title: string
  identityTitle: string
  identityDetail: string
  description: string
  submitLabel: string
  error: string
  busy: boolean
  onSubmit: FormEventHandler<HTMLFormElement>
  onCancel: () => void
}

export function AdminPasswordConfirmationDialog({
  idPrefix,
  title,
  identityTitle,
  identityDetail,
  description,
  submitLabel,
  error,
  busy,
  onSubmit,
  onCancel,
}: AdminPasswordConfirmationDialogProps) {
  return (
    <div className="customer-dialog-backdrop">
      <section className="customer-dialog" role="dialog" aria-modal="true" aria-labelledby={`${idPrefix}-title`}>
        <button type="button" className="customer-dialog-close" aria-label="Close confirmation" onClick={onCancel}><X size={18} /></button>
        <p className="vehicle-kicker">ADMIN PASSWORD CONFIRMATION</p>
        <h2 id={`${idPrefix}-title`}>{title}</h2>
        <p className="customer-dialog-identity"><strong>{identityTitle}</strong><span>{identityDetail}</span></p>
        <p>{description}</p>
        <form className="customer-dialog-form" onSubmit={onSubmit}>
          <label htmlFor={`${idPrefix}-password`}>Enter your administrator password</label>
          <input id={`${idPrefix}-password`} name="admin-password" type="password" autoComplete="off" required />
          <label htmlFor={`${idPrefix}-reason`}>Reason (optional)</label>
          <textarea id={`${idPrefix}-reason`} name="reason" maxLength={1000} rows={3} />
          {error && <p className="vehicle-notice error" role="alert">{error}</p>}
          <div className="customer-dialog-actions">
            <button className="vehicle-secondary-button" type="button" onClick={onCancel}>Cancel</button>
            <button className="vehicle-primary-button" type="submit" disabled={busy}>{busy ? 'Verifying…' : submitLabel}</button>
          </div>
        </form>
      </section>
    </div>
  )
}
