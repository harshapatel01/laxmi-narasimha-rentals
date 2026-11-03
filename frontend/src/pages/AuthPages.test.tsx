import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { PasswordResetPage } from './AuthPages'

function renderPasswordResetPage(path: string, confirm = false) {
  return renderToString(
    <MemoryRouter initialEntries={[path]}>
      <PasswordResetPage confirm={confirm} />
    </MemoryRouter>,
  )
}

describe('password reset forms', () => {
  it('renders the forgot-password email request form', () => {
    const markup = renderPasswordResetPage('/password-reset')

    expect(markup).toContain('Reset your password.')
    expect(markup).toContain('If an account can be reset')
    expect(markup).toContain('for="reset-email"')
    expect(markup).toContain('type="email"')
    expect(markup).toContain('Request reset link')
  })

  it('renders the password and confirmation fields for a reset link', () => {
    const markup = renderPasswordResetPage(
      '/password-reset/confirm?token=a-valid-looking-reset-token',
      true,
    )

    expect(markup).toContain('Choose a new password.')
    expect(markup).toContain('for="reset-password"')
    expect(markup).toContain('for="reset-confirm-password"')
    expect(markup).toContain('minLength="12"')
    expect(markup).toContain('Update password')
  })

  it('requires a reset link before rendering the new-password form', () => {
    const markup = renderPasswordResetPage('/password-reset/confirm', true)

    expect(markup).toContain('A valid reset link is required.')
    expect(markup).not.toContain('for="reset-password"')
  })
})
