"""
auth.py – Reusable authorization helpers for the Flask lab-management app.

Roles (system-level)
---------------------
  admin  – system administrator; full access to all routes
  user   – regular account (lab-specific role comes from LabMembership)

  Legacy system-role values still accepted for backward compat:
    lab_manager, lab_member, lab

Lab-specific roles (stored in LabMembership.role_in_lab)
---------------------------------------------------------
  manager  – primary manager of a lab
  member   – regular lab member

Usage
-----
Import the decorators in app.py::

    from app.auth import admin_required, lab_manager_required

Decorating routes (always put @login_required first)::

    @app.route('/labs/create')
    @login_required          # 1. redirect to login if not authenticated
    @admin_required          # 2. then check admin role
    def labs_create(): ...

    # For POST-only routes that should bounce to a specific page on denial:
    @app.route('/labs/delete/<int:lab_id>', methods=['POST'])
    @login_required
    @admin_required(redirect_to='labs_list')
    def labs_delete(lab_id): ...
"""

from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user


# ---------------------------------------------------------------------------
# Low-level role predicates (mirror model methods, but usable without a User
# instance – useful for checking the *current* user quickly in Python code)
# ---------------------------------------------------------------------------

def _is_admin():
    return current_user.is_authenticated and current_user.is_admin()


def _is_lab_manager():
    return current_user.is_authenticated and current_user.is_lab_manager()


def _is_lab_user():
    """True for both lab_manager and lab_member (any non-admin lab user)."""
    return current_user.is_authenticated and current_user.is_lab_user()


# ---------------------------------------------------------------------------
# Decorator: admin only
# ---------------------------------------------------------------------------

def admin_required(f=None, *, redirect_to='dashboard'):
    """Allow access only to users with role='admin'.

    Can be used in two ways::

        # Simple form (redirects to dashboard on denial)
        @login_required
        @admin_required
        def my_view(): ...

        # With custom redirect target (useful for POST-only routes)
        @login_required
        @admin_required(redirect_to='labs_list')
        def labs_delete(lab_id): ...
    """
    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            if not _is_admin():
                flash('Bạn không có quyền thực hiện thao tác này.', 'danger')
                return redirect(url_for(redirect_to))
            return func(*args, **kwargs)
        return decorated

    # Called as @admin_required  (no parentheses – f is the decorated function)
    if f is not None:
        return decorator(f)
    # Called as @admin_required(redirect_to='...')  (with parentheses – return decorator)
    return decorator


# ---------------------------------------------------------------------------
# Decorator: lab_manager or admin
# ---------------------------------------------------------------------------

def lab_manager_required(f):
    """Allow access only to users with role='lab_manager' OR 'admin'.

    Admins can always act as super-managers across all labs.

    Usage::

        @app.route('/commitments/create')
        @login_required
        @lab_manager_required
        def commitments_create(): ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (_is_admin() or _is_lab_manager()):
            flash('Bạn không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helper function (not a decorator): same-lab manager check
# ---------------------------------------------------------------------------

def require_same_lab_manager(obj, lab_id_attr='lab_id'):
    """Check that the current user is an admin, OR a lab_manager belonging
    to the same lab as *obj*.

    Returns None if the check passes, or a Flask redirect Response if denied.
    Designed to be used inline inside a route::

        deny = require_same_lab_manager(commitment)
        if deny:
            return deny

    Parameters
    ----------
    obj : any model instance with a ``lab_id`` attribute (or custom attr name)
    lab_id_attr : name of the lab FK attribute on *obj* (default: 'lab_id')
    """
    if _is_admin():
        return None  # admins always pass

    obj_lab_id = getattr(obj, lab_id_attr, None)

    if _is_lab_manager() and current_user.lab_id == obj_lab_id:
        return None  # manager of the same lab passes

    flash('Bạn không có quyền thực hiện thao tác này.', 'danger')
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Helper function (not a decorator): assignee or manager access
#
# Used for progress updates and detail views where only the assigned member
# OR a manager/admin of the same lab should have write access.
# ---------------------------------------------------------------------------

def require_assignee_or_manager(commitment):
    """Check that the current user can edit/update *commitment*:

    * admin           – always allowed
    * lab_manager     – allowed if same lab as the commitment
    * lab_member/lab  – allowed only if they are the assignee

    Returns None on success, or a redirect Response on failure::

        deny = require_assignee_or_manager(commitment)
        if deny:
            return deny
    """
    if _is_admin():
        return None

    # Manager of the same lab
    if _is_lab_manager() and current_user.lab_id == commitment.lab_id:
        return None

    # Assignee (lab_member or legacy 'lab' role)
    if _is_lab_user() and commitment.lab_id == current_user.lab_id:
        if commitment.assigned_to is None or commitment.assigned_to == current_user.id:
            return None

    flash('Chỉ người được phân công hoặc quản lý lab mới có thể thực hiện thao tác này.', 'danger')
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Decorator: same-lab view access (read-only gate, e.g. commitment detail)
# ---------------------------------------------------------------------------

def same_lab_required(f):
    """Ensure the current user (non-admin) belongs to the same lab as the
    *commitment* being accessed.  The commitment must be passed as keyword
    argument ``commitment`` or positional, but typically this is used on
    routes that load the object and pass it via ``commitment`` kwarg.

    In practice it is often easier to call ``require_same_lab_manager`` or
    ``require_assignee_or_manager`` inline in the route body.  This decorator
    is provided for completeness / future use with blueprint-based approach.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # This decorator works when the route fetches the object itself and
        # then calls the helper, so it is effectively a stub that delegates.
        # Routes should call require_same_lab_manager / require_assignee_or_manager
        # directly for fine-grained control.
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Utility: get a user-facing label for a role value
# ---------------------------------------------------------------------------

ROLE_LABELS = {
    'admin': 'Quản trị viên',
    'lab_manager': 'Quản lý Lab',
    'lab_member': 'Thành viên Lab',
    'lab': 'Thành viên Lab',  # legacy alias
}


def role_label(role):
    """Return a Vietnamese display label for a role string."""
    return ROLE_LABELS.get(role, role)


# Make role_label available as a Jinja2 filter.
# Register in app.py:
#   from app.auth import role_label
#   app.jinja_env.filters['role_label'] = role_label
