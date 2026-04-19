"""
CSRF token utilities - Flask session-based.
"""
import secrets

def generate_csrf_token():
    """
    Get or create CSRF token for current Flask session.
    Called by Jinja2 (no args) and by app.py get_csrf_token() wrapper.
    """
    from flask import session
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

def validate_csrf_token(token):
    """Validate the submitted CSRF token against session."""
    from flask import session
    if not token:
        return False
    stored = session.get('_csrf_token')
    if not stored:
        return False
    return secrets.compare_digest(stored, token)
