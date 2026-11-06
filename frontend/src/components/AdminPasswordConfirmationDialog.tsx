import { useEffect, useRef, type FormEventHandler } from 'react'
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
  const dialogRef = useRef<HTMLElement>(null)
  const onCancelRef = useRef(onCancel)

  useEffect(() => {
    onCancelRef.current = onCancel
  }, [onCancel])

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const dialog = dialogRef.current
    dialog?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancelRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog) return

      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => element.offsetParent !== null)
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) {
        event.preventDefault()
        dialog.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previousFocus?.focus()
    }
  }, [])

  return (
    <div className="customer-dialog-backdrop">
      <section
        ref={dialogRef}
        className="customer-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${idPrefix}-title`}
        aria-describedby={`${idPrefix}-description`}
        tabIndex={-1}
      >
        <button type="button" className="customer-dialog-close" aria-label="Close confirmation" onClick={onCancel}><X size={18} /></button>
        <p className="vehicle-kicker">ADMIN PASSWORD CONFIRMATION</p>
        <h2 id={`${idPrefix}-title`}>{title}</h2>
        <p className="customer-dialog-identity"><strong>{identityTitle}</strong><span>{identityDetail}</span></p>
        <p id={`${idPrefix}-description`}>{description}</p>
        <form className="customer-dialog-form" onSubmit={onSubmit}>
          <label htmlFor={`${idPrefix}-password`}>Enter your administrator password</label>
          <input id={`${idPrefix}-password`} name="admin-password" type="password" autoComplete="current-password" required />
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
