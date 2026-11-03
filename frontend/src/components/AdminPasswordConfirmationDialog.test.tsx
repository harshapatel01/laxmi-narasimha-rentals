import { renderToString } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { AdminPasswordConfirmationDialog } from './AdminPasswordConfirmationDialog'

describe('admin password confirmation dialog', () => {
  it('renders the consequence, required password, optional reason, and actions accessibly', () => {
    const markup = renderToString(
      <AdminPasswordConfirmationDialog
        idPrefix="customer-action"
        title="Deactivate this customer?"
        identityTitle="Ravi Kumar"
        identityDetail="ravi@example.test"
        description="Booking, payment, and audit history will be preserved."
        submitLabel="Confirm deactivation"
        error=""
        busy={false}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(markup).toContain('role="dialog"')
    expect(markup).toContain('aria-modal="true"')
    expect(markup).toContain('Deactivate this customer?')
    expect(markup).toContain('Booking, payment, and audit history will be preserved.')
    expect(markup).toContain('id="customer-action-password"')
    expect(markup).toContain('name="admin-password"')
    expect(markup).toContain('required=""')
    expect(markup).toContain('id="customer-action-reason"')
    expect(markup).toContain('Confirm deactivation')
  })
})
