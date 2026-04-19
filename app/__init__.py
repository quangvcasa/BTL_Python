from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_file, send_from_directory, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import io
import secrets
import hashlib

from config import Config
from app.models import db, User, Lab, LabMembership, Commitment, ProgressUpdate, Notification, ActivityLog, ExecutionItem, ExecutionItemUpdate, ExecutionItemEvidence
from app.csrf_utils import generate_csrf_token, validate_csrf_token
from app.utils import get_vn_time
from app.auth import (
    admin_required, lab_manager_required,
    require_same_lab_manager, require_assignee_or_manager,
    role_label,
)
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Vui lòng đăng nhập để tiếp tục.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============== CSRF PROTECTION ==============

def get_csrf_token():
    """Wrapper for Jinja2 - returns CSRF token from session."""
    return generate_csrf_token()

app.jinja_env.globals['csrf_token'] = get_csrf_token
app.jinja_env.filters['role_label'] = role_label

@app.context_processor
def inject_today():
    from datetime import datetime
    return {'today': datetime.today()}

@app.before_request
def csrf_protect():
    """Validate CSRF token on all POST/PUT/DELETE requests, except login page."""
    if request.method in ('POST', 'PUT', 'DELETE'):
        # Skip CSRF on login (login form is not a CSRF risk - no state change on server)
        if request.endpoint == 'login':
            return
        token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
        if not validate_csrf_token(token):
            flash('Yêu cầu không hợp lệ (CSRF token không đúng). Vui lòng thử lại.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))

def run_overdue_checks():
    """Ensure any commitments or execution items that pass their deadline are marked as overdue
    and notifications are generated correctly. Called on-demand in dashboard and lists."""
    from app.utils import get_vn_time
    now = get_vn_time()
    changed = False

    # 1. Overdue Commitments
    overdue_commits = Commitment.query.filter(
        Commitment.status.in_(['Mới', 'Đang thực hiện', 'Đã phân công', 'Có rủi ro']),
        Commitment.deadline < now
    ).all()
    for c in overdue_commits:
        c.status = Commitment.STATUS_OVERDUE
        if getattr(c, 'lab', None) and c.lab.manager_id:
            Notification.notify_commitment_overdue(c, c.lab.manager_id)
        changed = True

    # 2. Check Execution Items
    overdue_items = ExecutionItem.query.filter(
        ExecutionItem.due_date < now,
        ~ExecutionItem.status.in_([ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED, ExecutionItem.STATUS_OVERDUE])
    ).all()
    
    commitments_to_recalc = set()
    for i in overdue_items:
        i.status = ExecutionItem.STATUS_OVERDUE
        commitments_to_recalc.add(i.commitment)
        changed = True

        if i.assigned_to:
            Notification.notify_ei_overdue(i, i.assigned_to)
        if getattr(i.commitment, 'lab', None) and i.commitment.lab.manager_id:
            Notification.notify_ei_overdue(i, i.commitment.lab.manager_id)
            
    if changed:
        for c in commitments_to_recalc:
            c.recalculate_progress()
        db.session.commit()

def get_client_ip():
    return request.remote_addr or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()

# ============== AUTH ROUTES ==============

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            ActivityLog.log(user.id, 'LOGIN', details=f'User {username} đăng nhập thành công', ip_address=get_client_ip())
            db.session.commit()
            flash('Đăng nhập thành công!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    ActivityLog.log(current_user.id, 'LOGOUT', details=f'User {current_user.username} đăng xuất', ip_address=get_client_ip())
    db.session.commit()
    logout_user()
    flash('Đã đăng xuất.', 'info')
    return redirect(url_for('login'))

# ============== PROFILE ROUTES ==============

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        errors = []
        if not current_user.check_password(current_password):
            errors.append('Mật khẩu hiện tại không đúng.')
        if new_password and len(new_password) < 6:
            errors.append('Mật khẩu mới phải có ít nhất 6 ký tự.')
        if new_password and new_password != confirm_password:
            errors.append('Mật khẩu mới và xác nhận mật khẩu không khớp.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return redirect(url_for('profile'))

        if new_password:
            current_user.set_password(new_password)
            db.session.commit()
            ActivityLog.log(current_user.id, 'PASSWORD_CHANGE', details='User thay đổi mật khẩu', ip_address=get_client_ip())
            flash('Mật khẩu đã được thay đổi thành công!', 'success')
        else:
            flash('Không có thay đổi nào được lưu.', 'info')

        return redirect(url_for('profile'))

    return render_template('users/profile.html')

# ============== NOTIFICATION ROUTES ==============

@app.route('/notifications')
@login_required
def notifications():
    """List all notifications for current user"""
    notifications_list = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return render_template('notifications/list.html', notifications=notifications_list, unread_count=unread_count)

@app.route('/notifications/mark-read/<int:notif_id>')
@login_required
def notifications_mark_read(notif_id):
    """Mark a single notification as read"""
    notif = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first_or_404()
    notif.is_read = True
    db.session.commit()
    if notif.link:
        return redirect(notif.link)
    return redirect(url_for('notifications'))

@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def notifications_mark_all_read():
    """Mark all notifications as read"""
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('Tất cả thông báo đã được đánh dấu là đã đọc.', 'success')
    return redirect(url_for('notifications'))

@app.route('/api/notifications/count')
@login_required
def api_notifications_count():
    """Get unread notification count"""
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})

# ============== DASHBOARD ROUTES ==============

@app.route('/dashboard')
@login_required
def dashboard():
    run_overdue_checks()
    today = get_vn_time()
    context = {'unread_notif_count': Notification.query.filter_by(user_id=current_user.id, is_read=False).count()}

    manager_memberships = LabMembership.query.filter_by(
        user_id=current_user.id, role_in_lab='manager'
    ).all()
    manager_lab_ids = list({m.lab_id for m in manager_memberships}.union(
        {l.id for l in current_user.managed_labs} if current_user.managed_labs else set()
    ))

    if current_user.is_admin():
        context['role_view'] = 'admin'
        context['total'] = Commitment.query.count()
        context['total_execution_items'] = ExecutionItem.query.count()
        context['pending_review'] = Commitment.query.filter_by(status=Commitment.STATUS_PENDING_ADMIN_REVIEW).count()
        context['overdue'] = Commitment.query.filter_by(status=Commitment.STATUS_OVERDUE).count()
        context['needs_revision'] = Commitment.query.filter_by(status=Commitment.STATUS_NEEDS_REVISION).count()
        
        context['pending_items'] = ExecutionItem.query.filter_by(status=ExecutionItem.STATUS_PENDING_REVIEW).order_by(ExecutionItem.updated_at.desc()).all()
        
        context['recent'] = Commitment.query.order_by(Commitment.updated_at.desc()).limit(10).all()

        labs = Lab.query.all()
        commitments_by_lab = []
        for lab in labs:
            count = Commitment.query.filter_by(lab_id=lab.id).count()
            commitments_by_lab.append({'name': lab.name, 'count': count})
        context['commitments_by_lab'] = commitments_by_lab

        # We keep status Chart for admin
        active = Commitment.query.filter(Commitment.status == Commitment.STATUS_ACTIVE).count()
        completed = Commitment.query.filter(Commitment.status == Commitment.STATUS_DONE).count()
        new_commits = Commitment.query.filter(Commitment.status == Commitment.STATUS_NEW).count()
        context['status_chart'] = {
            'labels': ['Mới', 'Đang thực hiện', 'Hoàn thành', 'Quá hạn'],
            'data': [new_commits, active, completed, context['overdue']]
        }

    elif manager_lab_ids:
        context['role_view'] = 'manager'
        lab_ids = manager_lab_ids
        
        context['total'] = Commitment.query.filter(Commitment.lab_id.in_(lab_ids)).count()
        
        context['ei_pending_review'] = ExecutionItem.query.join(Commitment).filter(
            Commitment.lab_id.in_(lab_ids),
            ExecutionItem.status == ExecutionItem.STATUS_PENDING_REVIEW
        ).count()
        
        context['ei_needs_revision'] = ExecutionItem.query.join(Commitment).filter(
            Commitment.lab_id.in_(lab_ids),
            ExecutionItem.status == ExecutionItem.STATUS_NEEDS_REVISION
        ).count()
        
        context['ei_overdue'] = ExecutionItem.query.join(Commitment).filter(
            Commitment.lab_id.in_(lab_ids),
            ExecutionItem.due_date < today,
            ~ExecutionItem.status.in_([ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED])
        ).count()
        
        context['waiting_submit'] = Commitment.query.filter(
            Commitment.lab_id.in_(lab_ids),
            Commitment.progress >= 100,
            Commitment.status == Commitment.STATUS_DONE
        ).count()
        
        context['pending_items'] = ExecutionItem.query.join(Commitment).filter(
            Commitment.lab_id.in_(lab_ids),
            ExecutionItem.status == ExecutionItem.STATUS_PENDING_REVIEW
        ).order_by(ExecutionItem.updated_at.desc()).all()

    else:
        context['role_view'] = 'member'
        my_items_query = ExecutionItem.query.filter_by(assigned_to=current_user.id)
        
        context['my_total'] = my_items_query.count()
        context['my_active'] = my_items_query.filter(ExecutionItem.status.in_([
            ExecutionItem.STATUS_IN_PROGRESS, ExecutionItem.STATUS_PENDING_REVIEW
        ])).count()
        
        context['my_revise'] = my_items_query.filter_by(status=ExecutionItem.STATUS_NEEDS_REVISION).count()
        context['my_overdue'] = my_items_query.filter(
            ExecutionItem.due_date < today,
            ~ExecutionItem.status.in_([ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED])
        ).count()
        
        context['recent_my_items'] = my_items_query.order_by(ExecutionItem.updated_at.desc()).limit(10).all()

    return render_template('dashboard.html', **context)

@app.route('/my-tasks')
@login_required
def my_tasks():
    flash('Trang quản lý task cá nhân cũ đã được gỡ bỏ. Vui lòng sử dụng Dashboard để quản lý Hạng mục công việc.', 'info')
    return redirect(url_for('dashboard'))

# ============== LAB ROUTES ==============

@app.route('/labs')
@login_required
@admin_required
def labs_list():
    labs_list = Lab.query.order_by(Lab.created_at.desc()).all()
    return render_template('labs/list.html', labs=labs_list)


@app.route('/labs/create', methods=['GET', 'POST'])
@login_required
@admin_required
def labs_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None

        if not name:
            flash('Tên Lab không được để trống.', 'danger')
            return render_template('labs/form.html', lab=None, action='Tạo Lab mới')

        lab = Lab(name=name, description=description)
        db.session.add(lab)
        db.session.commit()

        ActivityLog.log(current_user.id, 'CREATE', 'Lab', lab.id, f'Tạo Lab mới: {name}', get_client_ip())
        db.session.commit()
        flash(f'Lab "{name}" đã được tạo thành công! Hãy gán quản lý và thành viên.', 'success')
        return redirect(url_for('labs_manage', lab_id=lab.id))

    return render_template('labs/form.html', lab=None, action='Tạo Lab mới')


@app.route('/labs/edit/<int:lab_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def labs_edit(lab_id):
    lab = Lab.query.get_or_404(lab_id)

    if request.method == 'POST':
        old_name = lab.name
        lab.name = request.form.get('name', '').strip() or lab.name
        lab.description = request.form.get('description', '').strip() or None

        db.session.commit()
        ActivityLog.log(current_user.id, 'UPDATE', 'Lab', lab.id,
                        f'Cập nhật Lab: {old_name} -> {lab.name}', get_client_ip())
        db.session.commit()
        flash(f'Lab "{lab.name}" đã được cập nhật!', 'success')
        return redirect(url_for('labs_manage', lab_id=lab.id))

    return render_template('labs/form.html', lab=lab, action='Chỉnh sửa Lab')


@app.route('/labs/delete/<int:lab_id>', methods=['POST'])
@login_required
@admin_required(redirect_to='labs_list')
def labs_delete(lab_id):
    lab = Lab.query.get_or_404(lab_id)
    lab_name = lab.name

    # Clear lab_id on all member users before deleting
    User.query.filter_by(lab_id=lab_id).update({'lab_id': None})
    # LabMembership rows are cascade-deleted via the relationship
    # Commitments are also cascade-deleted via the relationship
    db.session.delete(lab)
    db.session.commit()

    ActivityLog.log(current_user.id, 'DELETE', 'Lab', lab_id, f'Xóa Lab: {lab_name}', get_client_ip())
    db.session.commit()
    flash(f'Lab "{lab_name}" đã được xóa thành công!', 'success')
    return redirect(url_for('labs_list'))


@app.route('/labs/manage/<int:lab_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def labs_manage(lab_id):
    """Lab membership management page.
    POST actions (via hidden 'action' field):
      set_manager   – assign/change the primary manager
      add_member    – add a normal member
      remove_member – remove any membership row
    """
    lab = Lab.query.get_or_404(lab_id)

    if request.method == 'POST':
        action = request.form.get('action')

        # ------------------------------------------------------------------ #
        # ACTION: set_manager                                                  #
        # ------------------------------------------------------------------ #
        if action == 'set_manager':
            new_manager_id = request.form.get('manager_user_id', type=int)
            if not new_manager_id:
                flash('Vui lòng chọn một user làm quản lý.', 'danger')
                return redirect(url_for('labs_manage', lab_id=lab_id))

            new_manager = User.query.get(new_manager_id)
            if not new_manager or new_manager.is_admin():
                flash('User không hợp lệ.', 'danger')
                return redirect(url_for('labs_manage', lab_id=lab_id))

            # Prevent a user from being manager of multiple labs simultaneously
            existing_mgr_role = LabMembership.query.filter(
                LabMembership.user_id == new_manager_id,
                LabMembership.role_in_lab == 'manager',
                LabMembership.lab_id != lab_id
            ).first()
            if existing_mgr_role:
                flash(
                    f'User "{new_manager.username}" đã là quản lý của Lab khác. '
                    f'Một user chỉ có thể quản lý một Lab tại một thời điểm.',
                    'danger'
                )
                return redirect(url_for('labs_manage', lab_id=lab_id))

            # Demote current manager to member (if any)
            old_mgr_membership = lab.get_manager_membership()
            if old_mgr_membership and old_mgr_membership.user_id != new_manager_id:
                old_mgr_membership.role_in_lab = 'member'

            # Upsert: update existing membership or create new one
            existing = LabMembership.query.filter_by(
                lab_id=lab_id, user_id=new_manager_id).first()
            if existing:
                existing.role_in_lab = 'manager'
            else:
                membership = LabMembership(
                    lab_id=lab_id, user_id=new_manager_id, role_in_lab='manager')
                db.session.add(membership)

            lab.manager_id = new_manager_id
            new_manager.lab_id = lab_id          # sync convenience field

            db.session.commit()
            ActivityLog.log(current_user.id, 'UPDATE', 'Lab', lab_id,
                            f'Gán quản lý: {new_manager.username}', get_client_ip())
            db.session.commit()
            flash(f'"{new_manager.username}" đã được đặt làm Quản lý Lab.', 'success')

        # ------------------------------------------------------------------ #
        # ACTION: add_member                                                   #
        # ------------------------------------------------------------------ #
        elif action == 'add_member':
            member_user_id = request.form.get('member_user_id', type=int)
            if not member_user_id:
                flash('Vui lòng chọn một user để thêm.', 'danger')
                return redirect(url_for('labs_manage', lab_id=lab_id))

            member = User.query.get(member_user_id)
            if not member or member.is_admin():
                flash('User không hợp lệ.', 'danger')
                return redirect(url_for('labs_manage', lab_id=lab_id))

            # Check for duplicate membership (already in THIS lab)
            already = LabMembership.query.filter_by(
                lab_id=lab_id, user_id=member_user_id).first()
            if already:
                flash(f'User "{member.username}" đã là thành viên của Lab này.', 'warning')
                return redirect(url_for('labs_manage', lab_id=lab_id))

            # Warn if already in another lab (still allow, but inform admin)
            if member.lab_id and member.lab_id != lab_id:
                other_lab = Lab.query.get(member.lab_id)
                other_name = other_lab.name if other_lab else '?'
                flash(
                    f'Lưu ý: User "{member.username}" đang thuộc Lab "{other_name}". '
                    f'Đã thêm vào Lab này nhưng lab_id cũ giữ nguyên.', 'warning'
                )

            membership = LabMembership(
                lab_id=lab_id, user_id=member_user_id, role_in_lab='member')
            db.session.add(membership)
            member.lab_id = lab_id               # sync convenience field

            db.session.commit()
            ActivityLog.log(current_user.id, 'UPDATE', 'Lab', lab_id,
                            f'Thêm thành viên: {member.username}', get_client_ip())
            db.session.commit()
            flash(f'Thêm "{member.username}" vào Lab thành công!', 'success')

        # ------------------------------------------------------------------ #
        # ACTION: remove_member                                                #
        # ------------------------------------------------------------------ #
        elif action == 'remove_member':
            membership_id = request.form.get('membership_id', type=int)
            membership = LabMembership.query.filter_by(
                id=membership_id, lab_id=lab_id).first_or_404()

            removed_user = membership.user
            was_manager = (membership.role_in_lab == 'manager')

            db.session.delete(membership)

            # If we removed the manager, also clear Lab.manager_id
            if was_manager:
                lab.manager_id = None

            # Clear user.lab_id only if they have no other memberships
            remaining = LabMembership.query.filter(
                LabMembership.user_id == removed_user.id,
                LabMembership.lab_id != lab_id
            ).first()
            if not remaining:
                removed_user.lab_id = None

            db.session.commit()
            ActivityLog.log(current_user.id, 'UPDATE', 'Lab', lab_id,
                            f'Xóa thành viên: {removed_user.username}', get_client_ip())
            db.session.commit()
            flash(f'Đã xóa "{removed_user.username}" khỏi Lab.', 'success')

        return redirect(url_for('labs_manage', lab_id=lab_id))

    # GET – build page context
    current_memberships = lab.memberships.all()
    current_member_ids = {m.user_id for m in current_memberships}

    # Users eligible to be assigned as manager or member:
    # exclude admins and users already in this lab
    eligible_users = User.query.filter(
        User.role != 'admin',
        ~User.id.in_(current_member_ids)
    ).order_by(User.username).all()

    members = lab.get_members()
    manager_membership = lab.get_manager_membership()

    return render_template(
        'labs/manage.html',
        lab=lab,
        manager_membership=manager_membership,
        members=members,
        eligible_users=eligible_users,
    )


# ============== USER ROUTES (Admin) ==============

@app.route('/users')
@login_required
@admin_required
def users_list():
    users = User.query.order_by(User.username).all()
    return render_template('users/list.html', users=users)

@app.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def users_create():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip() or None
        email = request.form.get('email', '').strip() or None
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        # Whitelist to prevent unexpected role injection
        if role not in ('admin', 'user'):
            role = 'user'

        errors = []
        if not username:
            errors.append('Tên đăng nhập không được để trống.')
        elif User.query.filter_by(username=username).first():
            errors.append('Tên đăng nhập đã tồn tại!')
        if email and User.query.filter_by(email=email).first():
            errors.append('Email này đã được dùng bởi một tài khoản khác.')
        if not password:
            errors.append('Mật khẩu không được để trống.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('users/form.html', user=None, action='Tạo User mới')

        user = User(username=username, full_name=full_name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        ActivityLog.log(current_user.id, 'CREATE', 'User', user.id,
                        f'Tạo User mới: {username} (role={role})', get_client_ip())
        db.session.commit()
        flash(f'User "{username}" đã được tạo thành công!', 'success')
        return redirect(url_for('users_list'))

    return render_template('users/form.html', user=None, action='Tạo User mới')

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def users_edit(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        old_username = user.username
        new_role = request.form.get('role', 'user')
        # Only accept the two canonical system roles from the new form.
        # Legacy DB values (lab_manager / lab_member / lab) are preserved as-is
        # if the user object already had them – we simply don’t overwrite them
        # if the form somehow sends an unknown value.
        if new_role not in ('admin', 'user', 'lab_manager', 'lab_member', 'lab'):
            new_role = 'user'
        user.role = new_role

        user.full_name = request.form.get('full_name', '').strip() or None
        new_email = request.form.get('email', '').strip() or None

        # Email uniqueness check (allow same user to keep their own email)
        if new_email and new_email != user.email:
            if User.query.filter(User.email == new_email, User.id != user.id).first():
                flash('Email này đã được dùng bởi một tài khoản khác.', 'danger')
                return render_template('users/form.html', user=user, action='Chỉnh sửa User')
        user.email = new_email

        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)
            pw_note = ' (password thay đổi)'
        else:
            pw_note = ''

        db.session.commit()
        ActivityLog.log(current_user.id, 'UPDATE', 'User', user.id,
                        f'Cập nhật User: {old_username} -> {user.username}{pw_note}', get_client_ip())
        db.session.commit()
        flash(f'User "{user.username}" đã được cập nhật!', 'success')
        return redirect(url_for('users_list'))

    return render_template('users/form.html', user=user, action='Chỉnh sửa User')

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required(redirect_to='users_list')
def users_delete(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Không thể xóa chính mình.', 'danger')
        return redirect(url_for('users_list'))

    assigned_count = Commitment.query.filter_by(assigned_to=user.id).count()
    created_count = Commitment.query.filter_by(created_by=user.id).count()
    progress_updates_count = ProgressUpdate.query.filter_by(created_by=user.id).count()

    if assigned_count:
        flash(
            'Không thể xóa User này vì hiện tại user đang phụ trách các cam kết. ' 
            'Vui lòng chuyển giao hoặc xóa các cam kết trước khi xóa.',
            'danger'
        )
        return redirect(url_for('users_list'))

    # Disassociate nullable audit references so the user can be removed cleanly.
    Commitment.query.filter_by(created_by=user.id).update({'created_by': None})
    ProgressUpdate.query.filter_by(created_by=user.id).update({'created_by': None})
    Notification.query.filter_by(user_id=user.id).delete()
    ActivityLog.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    user_name = user.username
    db.session.delete(user)
    db.session.commit()

    ActivityLog.log(current_user.id, 'DELETE', 'User', user_id, f'Xóa User: {user_name}', get_client_ip())
    db.session.commit()
    flash(f'User "{user_name}" đã được xóa thành công!', 'success')
    return redirect(url_for('users_list'))

# ============== COMMITMENT ROUTES ==============

@app.route('/commitments')
@login_required
def commitments_list():
    run_overdue_checks()
    query = Commitment.query

    # Non-admins only see commitments belonging to their lab
    if not current_user.is_admin():
        if not current_user.lab_id:
            return render_template(
                'commitments/list.html', commitments=[], labs=[],
                info='Bạn chưa thuộc Lab nào. Liên hệ Admin để được phân công.'
            )
        query = query.filter_by(lab_id=current_user.lab_id)

    lab_filter  = request.args.get('lab_id')
    status_filter = request.args.get('status')
    priority_filter = request.args.get('priority')
    search      = request.args.get('search')

    if lab_filter:
        query = query.filter_by(lab_id=int(lab_filter))
    if status_filter:
        query = query.filter_by(status=status_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if search:
        query = query.filter(
            db.or_(
                Commitment.title.contains(search),
                Commitment.code.contains(search)
            )
        )

    commitments = query.order_by(Commitment.deadline.asc()).all()
    labs = Lab.query.all()

    return render_template(
        'commitments/list.html',
        commitments=commitments,
        labs=labs,
        info=None,
    )

@app.route('/commitments/create', methods=['GET', 'POST'])
@login_required
@admin_required
def commitments_create():
    labs = Lab.query.order_by(Lab.name).all()

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip() or None
        lab_id      = request.form.get('lab_id', type=int)
        priority    = request.form.get('priority', 'Trung bình')
        code_input  = request.form.get('code', '').strip() or None
        start_str   = request.form.get('start_date', '')
        deadline_str = request.form.get('deadline', '')

        errors = []
        if not title:
            errors.append('Tiêu đề không được để trống.')
        if not lab_id:
            errors.append('Phải chọn Lab thực hiện.')
        if not start_str:
            errors.append('Phải chọn ngày bắt đầu.')
        if not deadline_str:
            errors.append('Phải chọn hạn hoàn thành.')

        start_date = deadline = None
        if start_str and deadline_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
                deadline   = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày không hợp lệ.')
            else:
                if deadline <= start_date:
                    errors.append('Hạn hoàn thành phải sau ngày bắt đầu.')

        # Check code uniqueness if provided
        if code_input and Commitment.query.filter_by(code=code_input).first():
            errors.append(f'Mã cam kết "{code_input}" đã tồn tại.')

        if priority not in (
            Commitment.PRIORITY_LOW, Commitment.PRIORITY_MEDIUM,
            Commitment.PRIORITY_HIGH, Commitment.PRIORITY_URGENT
        ):
            priority = Commitment.PRIORITY_MEDIUM

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'commitments/form.html',
                commitment=None, labs=labs, action='Tạo Cam kết mới'
            )

        commitment = Commitment(
            code=code_input or Commitment.generate_code(),
            title=title,
            description=description,
            lab_id=lab_id,
            priority=priority,
            start_date=start_date,
            deadline=deadline,
            status=Commitment.STATUS_NEW,
            created_by=current_user.id,
        )
        db.session.add(commitment)
        db.session.commit()

        ActivityLog.log(
            current_user.id, 'CREATE', 'Commitment', commitment.id,
            f'Tạo cam kết: [{commitment.code}] {title} (lab_id={lab_id})',
            get_client_ip()
        )
        db.session.commit()

        assigned_lab = Lab.query.get(lab_id)
        if assigned_lab and assigned_lab.manager_id:
            Notification.notify_lab_assignment(commitment, assigned_lab.manager_id)
            db.session.commit()

        flash(f'Cam kết "{commitment.code} – {title}" đã được tạo!', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    return render_template(
        'commitments/form.html',
        commitment=None, labs=labs, action='Tạo Cam kết mới'
    )

@app.route('/commitments/edit/<int:commitment_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def commitments_edit(commitment_id):
    commitment = Commitment.query.get_or_404(commitment_id)
    labs = Lab.query.order_by(Lab.name).all()

    if request.method == 'POST':
        old_title = commitment.title

        code_input  = request.form.get('code', '').strip() or None
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip() or None
        lab_id      = request.form.get('lab_id', type=int)
        priority    = request.form.get('priority', commitment.priority)
        start_str   = request.form.get('start_date', '')
        deadline_str = request.form.get('deadline', '')

        errors = []
        if not title:
            errors.append('Tiêu đề không được để trống.')
        if not lab_id:
            errors.append('Phải chọn Lab thực hiện.')

        start_date = deadline = None
        if start_str and deadline_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
                deadline   = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày không hợp lệ.')
            else:
                if deadline <= start_date:
                    errors.append('Hạn hoàn thành phải sau ngày bắt đầu.')

        # Code uniqueness: allow same commitment to keep its own code
        if code_input and code_input != commitment.code:
            if Commitment.query.filter(Commitment.code == code_input,
                                       Commitment.id != commitment_id).first():
                errors.append(f'Mã cam kết "{code_input}" đã tồn tại.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'commitments/form.html',
                commitment=commitment, labs=labs, action='Chỉnh sửa Cam kết'
            )

        if code_input:
            commitment.code = code_input
        commitment.title       = title
        commitment.description = description
        commitment.lab_id      = lab_id
        commitment.priority    = priority
        commitment.start_date  = start_date
        commitment.deadline    = deadline
        commitment.update_status()

        db.session.commit()
        ActivityLog.log(
            current_user.id, 'UPDATE', 'Commitment', commitment.id,
            f'Cập nhật cam kết: {old_title} → {commitment.title}', get_client_ip()
        )
        db.session.commit()
        flash(f'Cam kết "{commitment.title}" đã được cập nhật!', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    return render_template(
        'commitments/form.html',
        commitment=commitment, labs=labs, action='Chỉnh sửa Cam kết'
    )

@app.route('/commitments/detail/<int:commitment_id>')
@login_required
def commitments_detail(commitment_id):
    commitment = Commitment.query.get_or_404(commitment_id)

    # Admin sees all; lab users only see their own lab's commitments
    if not current_user.is_admin() and commitment.lab_id != current_user.lab_id:
        flash('Bạn không có quyền xem cam kết này.', 'danger')
        return redirect(url_for('dashboard'))

    updates = ProgressUpdate.query.filter_by(
        commitment_id=commitment_id).order_by(ProgressUpdate.created_at.desc()).all()

    items = commitment.execution_items.all()
    # Refresh overdue statuses on the fly (no write needed unless they actually changed)
    now = get_vn_time()
    for item in items:
        if item.is_overdue() and item.status != ExecutionItem.STATUS_OVERDUE:
            item.auto_update_status()
    db.session.commit()

    # For the assign-member dropdown in the EI form (members of this lab)
    from app.models import LabMembership as LM
    lab_member_ids = [
        m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()
    ]
    lab_members = User.query.filter(User.id.in_(lab_member_ids)).order_by(User.username).all()

    # Can the current user manage execution items?
    can_manage_ei = (
        current_user.is_admin()
        or current_user.is_lab_manager_of(commitment.lab_id)
    )

    return render_template(
        'commitments/detail.html',
        commitment=commitment,
        updates=updates,
        items=items,
        lab_members=lab_members,
        can_manage_ei=can_manage_ei,
        ei_statuses=ExecutionItem.STATUS_LABELS,
        # can_update_ei: who can submit a progress update for an EI
        # (assignee of that item, admin, or same-lab manager)
        # Passed as a helper bool for the *current user* level; per-item
        # checks are still done in the route.
        can_update_ei=(
            current_user.is_admin()
            or current_user.is_lab_manager_of(commitment.lab_id)
            or any(i.assigned_to == current_user.id for i in items)
        ),
    )

@app.route('/commitments/delete/<int:commitment_id>', methods=['POST'])
@login_required
@admin_required(redirect_to='commitments_list')
def commitments_delete(commitment_id):
    commitment = Commitment.query.get_or_404(commitment_id)
    commit_title = commitment.title
    assigned_to  = commitment.assigned_to

    if assigned_to:
        Notification.notify_deletion(commit_title, assigned_to)

    db.session.delete(commitment)
    db.session.commit()

    ActivityLog.log(current_user.id, 'DELETE', 'Commitment', commitment_id,
                    f'Xóa cam kết: {commit_title}', get_client_ip())
    flash('!Đã xóa cam kết thành công!', 'success')
    return redirect(url_for('commitments_list'))


# ============== EXECUTION ITEM ROUTES ==============

def _can_manage_ei(commitment):
    """Return True if current_user may create/edit/delete execution items
    for the given commitment.  Used inline in routes."""
    return (
        current_user.is_authenticated
        and (
            current_user.is_admin()
            or current_user.is_lab_manager_of(commitment.lab_id)
        )
    )


@app.route('/commitments/<int:commitment_id>/execution-items/create',
           methods=['GET', 'POST'])
@login_required
def ei_create(commitment_id):
    commitment = Commitment.query.get_or_404(commitment_id)

    if not _can_manage_ei(commitment):
        flash('Bạn không có quyền thêm hạng mục thực hiện.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    # Eligible assignees: lab members (including manager)
    from app.models import LabMembership as LM
    lab_member_ids = [m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()]
    lab_members = User.query.filter(User.id.in_(lab_member_ids)).order_by(User.username).all()

    if request.method == 'POST':
        errors = []
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip() or None
        order_no    = request.form.get('order_no', 0, type=int)
        weight      = request.form.get('weight', 1.0, type=float)
        assigned_to = request.form.get('assigned_to', type=int) or None
        req_evidence = bool(request.form.get('requires_evidence'))
        req_approval = bool(request.form.get('requires_approval'))
        start_str   = request.form.get('start_date', '').strip()
        due_str     = request.form.get('due_date', '').strip()

        # Validate assignee belongs to the same lab (defence against form tampering)
        eligible_ids = {m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()}
        if assigned_to and assigned_to not in eligible_ids:
            errors.append('Người được giao không thuộc Lab này.')
            assigned_to = None

        if not title:
            errors.append('Tiêu đề không được để trống.')
        if weight is None or weight <= 0:
            errors.append('Trọng số phải là số dương.')

        start_date = due_date = None
        if start_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày bắt đầu không hợp lệ.')
        if due_str:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày đến hạn không hợp lệ.')
        if start_date and due_date and due_date <= start_date:
            errors.append('Ngày đến hạn phải sau ngày bắt đầu.')
        if due_date and due_date > commitment.deadline:
            errors.append(
                f'Ngày đến hạn không nên vượt quá hạn cam kết '
                f'({commitment.deadline.strftime("%d/%m/%Y %H:%M")}).'
            )

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'execution_items/form.html',
                commitment=commitment, item=None, lab_members=lab_members,
                action='Thêm hạng mục',
                ei_statuses=ExecutionItem.STATUS_LABELS,
            )

        item = ExecutionItem(
            commitment_id=commitment_id,
            title=title, description=description,
            order_no=order_no, weight=weight,
            assigned_to=assigned_to,
            start_date=start_date, due_date=due_date,
            requires_evidence=req_evidence,
            requires_approval=req_approval,
            created_by=current_user.id,
        )
        db.session.add(item)
        db.session.flush()

        commitment.recalculate_progress()
        db.session.commit()

        ActivityLog.log(
            current_user.id, 'CREATE', 'ExecutionItem', item.id,
            f'Thêm hạng mục [{item.id}] "{title}" cho cam kết {commitment.code}',
            get_client_ip()
        )
        db.session.commit()

        if assigned_to:
            Notification.notify_ei_assignment(item, assigned_to)
            db.session.commit()

        flash(f'Hạng mục "{title}" đã được thêm!', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    return render_template(
        'execution_items/form.html',
        commitment=commitment, item=None, lab_members=lab_members,
        action='Thêm hạng mục',
        ei_statuses=ExecutionItem.STATUS_LABELS,
    )


@app.route('/execution-items/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def ei_edit(item_id):
    item = ExecutionItem.query.get_or_404(item_id)
    commitment = item.commitment

    if not _can_manage_ei(commitment):
        flash('Bạn không có quyền sửa hạng mục này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    from app.models import LabMembership as LM
    lab_member_ids = [m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()]
    lab_members = User.query.filter(User.id.in_(lab_member_ids)).order_by(User.username).all()

    if request.method == 'POST':
        errors = []
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip() or None
        order_no    = request.form.get('order_no', item.order_no, type=int)
        weight      = request.form.get('weight', item.weight, type=float)
        assigned_to = request.form.get('assigned_to', type=int) or None
        new_status  = request.form.get('status', item.status)
        req_evidence = bool(request.form.get('requires_evidence'))
        req_approval = bool(request.form.get('requires_approval'))
        start_str   = request.form.get('start_date', '').strip()
        due_str     = request.form.get('due_date', '').strip()

        # Validate assignee belongs to the same lab (defence against form tampering)
        eligible_ids = {m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()}
        if assigned_to and assigned_to not in eligible_ids:
            errors.append('Người được giao không thuộc Lab này.')
            assigned_to = None

        if not title:
            errors.append('Tiêu đề không được để trống.')
        if weight is None or weight <= 0:
            errors.append('Trọng số phải là số dương.')
        if new_status not in ExecutionItem.STATUS_LABELS:
            new_status = item.status

        start_date = due_date = None
        if start_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày bắt đầu không hợp lệ.')
        if due_str:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày đến hạn không hợp lệ.')
        if start_date and due_date and due_date <= start_date:
            errors.append('Ngày đến hạn phải sau ngày bắt đầu.')
        if due_date and due_date > commitment.deadline:
            errors.append(
                f'Ngày đến hạn không nên vượt quá hạn cam kết '
                f'({commitment.deadline.strftime("%d/%m/%Y %H:%M")}).'
            )

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'execution_items/form.html',
                commitment=commitment, item=item, lab_members=lab_members,
                action='Sửa hạng mục',
                ei_statuses=ExecutionItem.STATUS_LABELS,
            )

        old_title    = item.title
        old_assignee = item.assigned_to
        item.title           = title
        item.description     = description
        item.order_no        = order_no
        item.weight          = weight
        item.assigned_to     = assigned_to
        item.status          = new_status
        item.start_date      = start_date
        item.due_date        = due_date
        item.requires_evidence = req_evidence
        item.requires_approval = req_approval

        commitment.recalculate_progress()
        db.session.commit()
        ActivityLog.log(
            current_user.id, 'UPDATE', 'ExecutionItem', item.id,
            f'Sửa hạng mục [{item.id}] "{old_title}" → "{item.title}"',
            get_client_ip()
        )
        db.session.commit()

        if assigned_to and assigned_to != old_assignee:
            Notification.notify_ei_assignment(item, assigned_to)
            db.session.commit()

        flash(f'Hạng mục "{item.title}" đã được cập nhật!', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    return render_template(
        'execution_items/form.html',
        commitment=commitment, item=item, lab_members=lab_members,
        action='Sửa hạng mục',
        ei_statuses=ExecutionItem.STATUS_LABELS,
    )


@app.route('/commitments/<int:commitment_id>/submit', methods=['POST'])
@login_required
def commitment_submit(commitment_id):
    """Submit commitment for admin review."""
    commitment = Commitment.query.get_or_404(commitment_id)

    if commitment.status == Commitment.STATUS_PENDING_ADMIN_REVIEW:
        flash('Cam kết đã được gửi lên Admin từ trước.', 'warning')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    is_valid, errors = commitment.validate_ready_for_submit(current_user)
    
    if not is_valid:
        for err in errors:
            flash(err, 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    commitment.status = Commitment.STATUS_PENDING_ADMIN_REVIEW
    commitment.submitted_by_id = current_user.id
    from app.utils import get_vn_time
    commitment.submitted_at = get_vn_time()

    ActivityLog.log(
        current_user.id, 'SUBMIT', 'Commitment', commitment_id,
        f'Gửi cam kết {commitment.code} lên Admin kiểm duyệt',
        get_client_ip()
    )
    db.session.commit()

    admins = User.query.filter_by(role='admin').all()
    for ad in admins:
        Notification.notify_commitment_submitted(commitment, ad.id)
    db.session.commit()

    flash('Đã gửi cam kết lên Admin để xét duyệt.', 'success')
    return redirect(url_for('commitments_detail', commitment_id=commitment_id))


@app.route('/commitments/<int:commitment_id>/admin-review', methods=['GET', 'POST'])
@login_required
def commitment_admin_review(commitment_id):
    """Final admin review for a submitted Commitment."""
    if not current_user.is_admin():
        flash('Chỉ có Quản trị viên mới được thực hiện chức năng này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    commitment = Commitment.query.get_or_404(commitment_id)

    if commitment.status != Commitment.STATUS_PENDING_ADMIN_REVIEW:
        flash('Cam kết chưa được gửi lên hoặc không ở trạng thái chờ duyệt.', 'warning')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    allowed_decisions = [
        Commitment.STATUS_APPROVED,
        Commitment.STATUS_NEEDS_REVISION,
        Commitment.STATUS_REJECTED
    ]

    if request.method == 'POST':
        errors = []
        decision = request.form.get('decision', '').strip()
        review_note = request.form.get('review_note', '').strip() or None

        if decision not in allowed_decisions:
            errors.append('Quyết định không hợp lệ.')

        if decision in [Commitment.STATUS_NEEDS_REVISION, Commitment.STATUS_REJECTED] and not review_note:
            errors.append('Phải có lý do (nhận xét) khi yêu cầu sửa đổi hoặc từ chối.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'commitments/admin_review_form.html',
                commitment=commitment,
                allowed_decisions=allowed_decisions,
            )

        old_status = commitment.status
        commitment.status = decision
        commitment.admin_review_note = review_note
        commitment.reviewed_by_id = current_user.id
        from app.utils import get_vn_time
        commitment.reviewed_at = get_vn_time()

        db.session.commit()

        ActivityLog.log(
            current_user.id, 'ADMIN_REVIEW', 'Commitment', commitment_id,
            f'Admin duyệt cam kết {commitment.code}: {old_status} → {decision}',
            get_client_ip()
        )
        db.session.commit()

        if commitment.lab and commitment.lab.manager_id:
            Notification.notify_commitment_reviewed(commitment, commitment.lab.manager_id, decision, review_note)
            db.session.commit()

        flash(f'Đã lưu kết quả kiểm duyệt cho cam kết {commitment.code}.', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    return render_template(
        'commitments/admin_review_form.html',
        commitment=commitment,
        allowed_decisions=allowed_decisions
    )


@app.route('/execution-items/<int:item_id>/delete', methods=['POST'])
@login_required
def ei_delete(item_id):
    item = ExecutionItem.query.get_or_404(item_id)
    commitment_id = item.commitment_id
    commitment = item.commitment

    if not _can_manage_ei(commitment):
        flash('Bạn không có quyền xóa hạng mục này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment_id))

    title = item.title
    db.session.delete(item)
    db.session.flush()  # item removed from DB before recalculation

    commitment.recalculate_progress()
    db.session.commit()

    ActivityLog.log(
        current_user.id, 'DELETE', 'ExecutionItem', item_id,
        f'Xóa hạng mục "{title}" khỏi cam kết {commitment.code}',
        get_client_ip()
    )
    db.session.commit()
    flash(f'Đã xóa hạng mục "{title}".', 'success')
    return redirect(url_for('commitments_detail', commitment_id=commitment_id))



@app.route('/execution-items/<int:item_id>/reassign', methods=['GET', 'POST'])
@login_required
def ei_reassign(item_id):
    """Manager reassignment workflow for ExecutionItem."""
    item = ExecutionItem.query.get_or_404(item_id)
    commitment = item.commitment

    if not _can_manage_ei(commitment):
        flash('Bạn không có quyền phân công lại hạng mục này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    from app.models import LabMembership as LM
    lab_member_ids = [m.user_id for m in LM.query.filter_by(lab_id=commitment.lab_id).all()]
    lab_members = User.query.filter(User.id.in_(lab_member_ids)).order_by(User.username).all()

    if request.method == 'POST':
        errors = []
        new_assignee_id = request.form.get('assigned_to', type=int) or None
        reason = request.form.get('reason', '').strip()

        if not new_assignee_id:
            errors.append('Vui lòng chọn người phụ trách mới.')
        elif new_assignee_id == item.assigned_to:
            errors.append('Người phụ trách mới phải khác với người hiện tại.')
        elif new_assignee_id not in lab_member_ids:
            errors.append('Người được giao không thuộc Lab của cam kết này.')

        if not reason:
            errors.append('Vui lòng nhập lý do phân công lại.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'execution_items/reassign_form.html',
                item=item, commitment=commitment, lab_members=lab_members
            )

        new_assignee = User.query.get(new_assignee_id)
        old_assignee_id = item.assigned_to
        old_name = item.assignee.display_name() if item.assignee else 'Chưa có'
        new_name = new_assignee.display_name() if new_assignee else 'Chưa có'

        # Record reassignment event
        note_text = f"Phân công lại từ [{old_name}] sang [{new_name}]. Lý do: {reason}"
        
        record = ExecutionItemUpdate(
            execution_item_id=item.id,
            updated_by_id=current_user.id,
            update_type='reassignment',
            old_status=item.status,
            new_status=item.status,
            note=note_text
        )
        db.session.add(record)

        item.assigned_to = new_assignee_id
        db.session.commit()

        ActivityLog.log(
            current_user.id, 'EI_REASSIGN', 'ExecutionItem', item.id,
            f'Phân công lại [{item.id}] "{item.title}": {old_name} → {new_name}',
            get_client_ip()
        )
        db.session.commit()

        Notification.notify_ei_reassigned(item, old_assignee_id, new_assignee_id, reason)
        db.session.commit()

        flash(f'Đã phân công lại hạng mục cho {new_name}.', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    return render_template(
        'execution_items/reassign_form.html',
        item=item, commitment=commitment, lab_members=lab_members
    )


@app.route('/execution-items/<int:item_id>/update', methods=['GET', 'POST'])
@login_required
def ei_update(item_id):
    """Submit a progress update for one ExecutionItem.
    Authorised users: assignee of that item, admin, same-lab manager.
    Every submission creates an ExecutionItemUpdate row (append-only).
    """
    item = ExecutionItem.query.get_or_404(item_id)
    commitment = item.commitment

    # ---- Authorization --------------------------------------------------- #
    is_assignee = (item.assigned_to == current_user.id)
    is_manager  = current_user.is_lab_manager_of(commitment.lab_id)
    if not (current_user.is_admin() or is_manager or is_assignee):
        flash('Bạn không có quyền cập nhật hạng mục này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    # Already completed / rejected – block further updates from regular members
    if item.status in (ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED):
        if not (current_user.is_admin() or is_manager):
            flash('Hạng mục này đã kết thúc. Liên hệ quản lý nếu cần mở lại.', 'warning')
            return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    # Eligible statuses for this user strictly bounded by the centralized policy
    allowed_statuses = item.get_allowed_transitions(current_user, is_review=False)

    if request.method == 'POST':
        errors = []
        new_status  = request.form.get('new_status', '').strip()
        note        = request.form.get('note', '').strip() or None
        blocker_reason = request.form.get('blocker_reason', '').strip() or None
        finish_str  = request.form.get('expected_finish_date', '').strip()

        # --- Validation --------------------------------------------------- #
        is_valid, transition_err = item.can_transition_execution_item(current_user, new_status, is_review=False)
        if not is_valid:
            errors.append(transition_err)

        # Note is required for any meaningful status change
        if not note:
            errors.append('Phải có ghi chú cho lần cập nhật này.')

        # blocker_reason required when reporting revision-needed
        if new_status == ExecutionItem.STATUS_NEEDS_REVISION and not blocker_reason:
            errors.append('Phải nêu lý do khi trạng thái là “Cần sửa”.')

        expected_finish = None
        if finish_str:
            try:
                expected_finish = datetime.strptime(finish_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                errors.append('Ngày dự kiến không hợp lệ.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'execution_items/update_form.html',
                item=item, commitment=commitment,
                allowed_statuses=allowed_statuses,
                ei_statuses=ExecutionItem.STATUS_LABELS,
            )

        # --- Persist -------------------------------------------------------- #
        old_status = item.status
        record = ExecutionItemUpdate(
            execution_item_id=item.id,
            updated_by_id=current_user.id,
            old_status=old_status,
            new_status=new_status,
            note=note,
            blocker_reason=blocker_reason,
            expected_finish_date=expected_finish,
        )
        db.session.add(record)
        db.session.flush()

        evidence_files = request.files.getlist('evidence_files')
        if evidence_files:
            evidence_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'execution_item_evidence')
            os.makedirs(evidence_dir, exist_ok=True)
            import uuid
            for f in evidence_files:
                if f and f.filename:
                    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                    if ext in {'exe', 'bat', 'sh', 'php', 'js'}:
                        continue
                    sec_name = secure_filename(f.filename)
                    if not sec_name:
                        sec_name = 'upload.bin'
                    stored_name = f"{get_vn_time().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}_{sec_name}"
                    relative_path = f"execution_item_evidence/{stored_name}"
                    absolute_path = os.path.join(evidence_dir, stored_name)
                    
                    f.save(absolute_path)
                    
                    ev = ExecutionItemEvidence(
                        execution_item_update_id=record.id,
                        original_filename=f.filename,
                        stored_filename=stored_name,
                        file_path=relative_path,
                        uploaded_by_id=current_user.id
                    )
                    db.session.add(ev)

        # Update the item's current status
        item.status = new_status
        # If the member provided an expected finish date, store it on the item too
        if expected_finish:
            item.expected_finish_date = expected_finish

        # Recalculate parent Commitment progress from all items
        commitment.recalculate_progress()
        db.session.commit()

        ActivityLog.log(
            current_user.id, 'EI_UPDATE', 'ExecutionItem', item.id,
            f'Cập nhật [{item.id}] "{item.title}": {old_status} → {new_status}',
            get_client_ip()
        )
        db.session.commit()

        if new_status == ExecutionItem.STATUS_PENDING_REVIEW:
            if commitment.lab and commitment.lab.manager_id:
                Notification.notify_ei_pending_review(item, commitment.lab.manager_id)
            admins = User.query.filter_by(role='admin').all()
            for ad in admins:
                Notification.notify_ei_pending_review(item, ad.id)
            db.session.commit()

        flash(f'Hạng mục "{item.title}" đã được cập nhật.', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    # GET
    return render_template(
        'execution_items/update_form.html',
        item=item, commitment=commitment,
        allowed_statuses=allowed_statuses,
        ei_statuses=ExecutionItem.STATUS_LABELS,
    )


@app.route('/execution-items/<int:item_id>/review', methods=['GET', 'POST'])
@login_required
def ei_review(item_id):
    """Manager review for a pending ExecutionItem."""
    item = ExecutionItem.query.get_or_404(item_id)
    commitment = item.commitment

    # ---- Authorization --------------------------------------------------- #
    if not _can_manage_ei(commitment):
        flash('Bạn không có quyền đánh giá hạng mục này.', 'danger')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    if item.status != ExecutionItem.STATUS_PENDING_REVIEW:
        flash('Chỉ có thể đánh giá hạng mục đang ở trạng thái Chờ duyệt.', 'warning')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    allowed_decisions = item.get_allowed_transitions(current_user, is_review=True)

    if request.method == 'POST':
        errors = []
        decision = request.form.get('decision', '').strip()
        review_note = request.form.get('review_note', '').strip() or None

        is_valid, transition_err = item.can_transition_execution_item(current_user, decision, is_review=True)
        if not is_valid:
            errors.append(transition_err)

        if decision in [ExecutionItem.STATUS_NEEDS_REVISION, ExecutionItem.STATUS_REJECTED] and not review_note:
            errors.append('Phải có nhận xét khi yêu cầu sửa đổi hoặc từ chối.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'execution_items/review_form.html',
                item=item, commitment=commitment,
                allowed_decisions=allowed_decisions,
                ei_statuses=ExecutionItem.STATUS_LABELS,
            )

        old_status = item.status
        record = ExecutionItemUpdate(
            execution_item_id=item.id,
            updated_by_id=current_user.id,
            update_type='review_action',
            old_status=old_status,
            new_status=decision,
            note=review_note
        )
        db.session.add(record)

        item.status = decision
        commitment.recalculate_progress()
        db.session.commit()

        ActivityLog.log(
            current_user.id, 'EI_REVIEW', 'ExecutionItem', item.id,
            f'Đánh giá [{item.id}] "{item.title}": {old_status} → {decision}',
            get_client_ip()
        )
        db.session.commit()

        if item.assigned_to:
            Notification.notify_ei_reviewed(item, item.assigned_to, review_note, decision)
            db.session.commit()

        flash(f'Đã ghi nhận kết quả đánh giá cho "{item.title}".', 'success')
        return redirect(url_for('commitments_detail', commitment_id=commitment.id))

    return render_template(
        'execution_items/review_form.html',
        item=item, commitment=commitment,
        allowed_decisions=allowed_decisions,
        ei_statuses=ExecutionItem.STATUS_LABELS,
    )


# ============== PROGRESS UPDATE ROUTES ==============

@app.route('/progress/update/<int:commitment_id>', methods=['GET', 'POST'])
@login_required
def progress_update(commitment_id):
    flash('Commitment progress is now calculated from execution items and cannot be updated directly. Tính năng cập nhật trực tiếp đã ngưng hoạt động.', 'warning')
    return redirect(url_for('commitments_detail', commitment_id=commitment_id))

# ============== FILE DOWNLOAD ROUTES ==============

@app.route('/uploads/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

# ============== REPORT ROUTES ==============

@app.route('/reports')
@login_required
def reports():
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('dashboard'))

    labs = Lab.query.all()

    total = Commitment.query.count()
    completed = Commitment.query.filter_by(status='Hoàn thành').count()
    completion_rate = (completed / total * 100) if total > 0 else 0

    lab_data = []
    for lab in labs:
        commits = Commitment.query.filter_by(lab_id=lab.id).all()
        total_lab = len(commits)
        completed_lab = len([c for c in commits if c.status == 'Hoàn thành'])
        overdue_lab = len([c for c in commits if c.status == 'Quá hạn'])
        lab_data.append({
            'name': lab.name,
            'total': total_lab,
            'completed': completed_lab,
            'overdue': overdue_lab,
            'rate': (completed_lab / total_lab * 100) if total_lab > 0 else 0
        })

    status_dist = db.session.query(
        Commitment.status,
        db.func.count(Commitment.id)
    ).group_by(Commitment.status).all()

    chart_labels = [s[0] for s in status_dist]
    chart_data = [s[1] for s in status_dist]

    return render_template('reports/index.html',
                           labs=labs,
                           total=total,
                           completed=completed,
                           completion_rate=completion_rate,
                           lab_data=lab_data,
                           chart_labels=chart_labels,
                           chart_data=chart_data)

# ============== EXPORT ROUTES ==============

def export_to_csv(data):
    """Export data to CSV using Python's built-in csv module."""
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    for row in data['rows']:
        writer.writerow(row)
    output.seek(0)
    return output


@app.route('/export/commitments')
@login_required
def export_commitments():
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('dashboard'))

    commitments = Commitment.query.order_by(Commitment.deadline.asc()).all()

    rows = []
    rows.append(['STT', 'Tiêu đề', 'Lab', 'Người phụ trách', 'Tiến độ (%)', 'Ngày bắt đầu', 'Deadline', 'Trạng thái'])
    for idx, c in enumerate(commitments, 1):
        lab_name = c.lab.name if c.lab else '-'
        assignee = c.assignee.username if c.assignee else '-'
        rows.append([
            idx, c.title, lab_name, assignee,
            c.progress,
            c.start_date.strftime('%d/%m/%Y %H:%M:%S'),
            c.deadline.strftime('%d/%m/%Y %H:%M:%S'),
            c.status
        ])

    output = export_to_csv({'rows': rows})
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='danh_sach_cam_ket.csv'
    )


@app.route('/export/labs')
@login_required
def export_labs():
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('dashboard'))

    labs = Lab.query.all()
    rows = []
    rows.append(['STT', 'Tên Lab', 'Quản lý', 'Email', 'Tổng cam kết', 'Hoàn thành', 'Quá hạn', 'Tỷ lệ (%)'])

    for idx, lab in enumerate(labs, 1):
        commits = Commitment.query.filter_by(lab_id=lab.id).all()
        total = len(commits)
        completed = len([c for c in commits if c.status == 'Hoàn thành'])
        overdue = len([c for c in commits if c.status == 'Quá hạn'])
        rate = (completed / total * 100) if total > 0 else 0
        rows.append([
            idx,
            lab.name,
            lab.manager.display_name() if lab.manager else (lab.manager_name or '—'),  # prefer linked User
            lab.manager.email if lab.manager else (lab.email or '—'),               # prefer linked User
            total, completed, overdue, f'{rate:.1f}'
        ])

    output = export_to_csv({'rows': rows})
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='bao_cao_theo_lab.csv'
    )


def get_pdf_font_name():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return 'Helvetica'

    font_name = 'UnicodeFont'
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name

    windir = os.environ.get('WINDIR', r'C:\Windows')
    font_files = [
        os.path.join(windir, 'Fonts', 'arialuni.ttf'),
        os.path.join(windir, 'Fonts', 'ARIALUNI.TTF'),
        os.path.join(windir, 'Fonts', 'SegoeUI.ttf'),
        os.path.join(windir, 'Fonts', 'calibri.ttf'),
        os.path.join(windir, 'Fonts', 'arial.ttf'),
        os.path.join(windir, 'Fonts', 'times.ttf'),
        os.path.join(windir, 'Fonts', 'DejaVuSans.ttf'),
    ]

    for font_path in font_files:
        try:
            if font_path and os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                pdfmetrics.registerFontFamily(font_name,
                                              normal=font_name,
                                              bold=font_name,
                                              italic=font_name,
                                              boldItalic=font_name)
                return font_name
        except Exception:
            continue

    return 'Helvetica'


def export_to_pdf(data, title, filename):
    """Export data to PDF using reportlab"""
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError:
        return None

    font_name = get_pdf_font_name()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1*cm, leftMargin=1*cm, topMargin=1*cm, bottomMargin=1*cm)
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Title'], fontName=font_name, fontSize=16, spaceAfter=20, alignment=1)
    elements.append(Paragraph(title, title_style))

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0D6EFD')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
    ]))
    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    return buffer


def export_dashboard_to_pdf(summary_data, status_rows, lab_rows, upcoming_rows):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError:
        return None

    font_name = get_pdf_font_name()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1*cm, leftMargin=1*cm, topMargin=1*cm, bottomMargin=1*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontName=font_name, fontSize=20, alignment=1, textColor=colors.HexColor('#0D6EFD'), spaceAfter=16)
    header_style = ParagraphStyle('Header', parent=styles['Heading2'], fontName=font_name, fontSize=14, textColor=colors.HexColor('#083E7D'), spaceAfter=8)
    normal_style = ParagraphStyle('Normal', parent=styles['BodyText'], fontName=font_name, fontSize=10, leading=14)

    elements = [
        Paragraph('BÁO CÁO TOÀN BỘ DASHBOARD', title_style),
        Paragraph(f'Ngày tạo: {get_vn_time().strftime("%d/%m/%Y %H:%M")}', normal_style),
        Spacer(1, 12)
    ]

    elements.append(Paragraph('1. Tổng quan', header_style))
    summary_table = Table(summary_data, colWidths=[90] * len(summary_data[0]))
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0D6EFD')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTNAME', (0, 1), (-1, 1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#E9F2FF')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph('2. Phân bố theo trạng thái', header_style))
    status_table = Table(status_rows, colWidths=[220, 120])
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')])
    ]))
    elements.append(status_table)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph('3. Chi tiết theo Lab', header_style))
    lab_table = Table(lab_rows, colWidths=[35, 145, 75, 75, 75, 75])
    lab_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0D6EFD')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')])
    ]))
    elements.append(lab_table)
    elements.append(Spacer(1, 18))

    if upcoming_rows:
        elements.append(Paragraph('4. Cam kết sắp tới hạn', header_style))
        upcoming_table = Table(upcoming_rows, colWidths=[35, 220, 90, 90, 90])
        upcoming_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC3545')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), font_name),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')])
        ]))
        elements.append(upcoming_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


@app.route('/export/report/pdf')
@login_required
def export_report_pdf():
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('dashboard'))

    today = get_vn_time()
    total = Commitment.query.count()
    active = Commitment.query.filter(Commitment.status == 'Đang thực hiện').count()
    completed = Commitment.query.filter_by(status='Hoàn thành').count()
    overdue = Commitment.query.filter_by(status='Quá hạn').count()
    new_commits = Commitment.query.filter_by(status='Mới').count()
    completion_rate = (completed / total * 100) if total > 0 else 0

    status_dist = db.session.query(
        Commitment.status,
        db.func.count(Commitment.id)
    ).group_by(Commitment.status).all()

    labs = Lab.query.all()
    lab_rows = [['STT', 'Tên Lab', 'Tổng cam kết', 'Hoàn thành', 'Quá hạn', 'Tỷ lệ (%)']]
    for idx, lab in enumerate(labs, 1):
        commits = Commitment.query.filter_by(lab_id=lab.id).all()
        total_lab = len(commits)
        completed_lab = len([c for c in commits if c.status == 'Hoàn thành'])
        overdue_lab = len([c for c in commits if c.status == 'Quá hạn'])
        rate = (completed_lab / total_lab * 100) if total_lab > 0 else 0
        lab_rows.append([idx, lab.name, total_lab, completed_lab, overdue_lab, f'{rate:.1f}'])

    upcoming_commitments = Commitment.query.filter(
        Commitment.deadline <= today + timedelta(days=7),
        Commitment.deadline >= today,
        Commitment.status.in_(['Mới', 'Đang thực hiện'])
    ).order_by(Commitment.deadline.asc()).limit(10).all()
    upcoming_rows = [['STT', 'Tiêu đề', 'Lab', 'Deadline', 'Trạng thái']]
    for idx, c in enumerate(upcoming_commitments, 1):
        lab_name = c.lab.name if c.lab else '-'
        upcoming_rows.append([
            idx,
            c.title,
            lab_name,
            c.deadline.strftime('%d/%m/%Y %H:%M:%S'),
            c.status
        ])

    summary_data = [
        ['Tổng cam kết', 'Hoàn thành', 'Đang thực hiện', 'Quá hạn', 'Mới', 'Tỷ lệ (%)'],
        [
            str(total),
            str(completed),
            str(active),
            str(overdue),
            str(new_commits),
            f'{completion_rate:.1f}%'
        ]
    ]

    status_rows = [['Trạng thái', 'Số lượng']] + [[status, count] for status, count in status_dist]

    output = export_dashboard_to_pdf(summary_data, status_rows, lab_rows, upcoming_rows)

    if output:
        return send_file(output, mimetype='application/pdf', as_attachment=True, download_name='bao_cao_dashboard.pdf')

    flash('PDF export unavailable: reportlab chưa được cài đặt.', 'danger')
    return redirect(url_for('reports'))


# ============== ACTIVITY LOG ROUTES ==============

@app.route('/activity-logs')
@login_required
def activity_logs():
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = 50

    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('activity_logs/list.html', logs=logs)


# ============== API ROUTES ==============

@app.route('/api/stats')
@login_required
def api_stats():
    if current_user.is_admin():
        commitments = Commitment.query.all()
    else:
        commitments = Commitment.query.filter_by(lab_id=current_user.lab_id).all()

    stats = {
        'total': len(commitments),
        'by_status': {},
        'avg_progress': 0
    }

    for c in commitments:
        stats['by_status'][c.status] = stats['by_status'].get(c.status, 0) + 1

    if commitments:
        stats['avg_progress'] = sum(c.progress for c in commitments) / len(commitments)

    return jsonify(stats)

@app.route('/api/commitments/<int:commitment_id>/timeline')
@login_required
def api_timeline(commitment_id):
    commitment = Commitment.query.get_or_404(commitment_id)
    updates = ProgressUpdate.query.filter_by(commitment_id=commitment_id).order_by(ProgressUpdate.created_at).all()

    timeline = [{
        'date': commitment.start_date.isoformat(),
        'progress': 0,
        'note': 'Bắt đầu'
    }]
    timeline.extend([{
        'date': u.created_at.isoformat(),
        'progress': u.progress,
        'note': u.notes
    } for u in updates])

    return jsonify(timeline)

@app.route('/api/labs/<int:lab_id>/users')
@login_required
def api_lab_users(lab_id):
    """Return users who are members of the given lab (via LabMembership).
    Falls back to User.lab_id sync field for legacy rows that predate LabMembership.
    """
    # Primary source: LabMembership table
    from app.models import LabMembership as LM
    membership_user_ids = [
        m.user_id for m in LM.query.filter_by(lab_id=lab_id).all()
    ]
    if membership_user_ids:
        users = User.query.filter(User.id.in_(membership_user_ids)).all()
    else:
        # Legacy fallback: users whose lab_id sync field still points here
        users = User.query.filter(
            User.lab_id == lab_id,
            User.role.in_(['user', 'lab_manager', 'lab_member', 'lab'])
        ).all()
    return jsonify([{'id': u.id, 'username': u.username} for u in users])

# ============== ERROR HANDLERS ==============

@app.errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

# ============== INIT DATABASE ==============

def ensure_tables():
    """Create new tables (notifications, activity_logs) if they don't exist."""
    with app.app_context():
        inspector = db.inspect(db.engine)
        existing_tables = inspector.get_table_names()

        # Ensure new tables are created
        tables_to_check = ['notifications', 'activity_logs']
        for table in tables_to_check:
            if table not in existing_tables:
                db.create_all()
                print(f'Created new table: {table}')
                break

        # Migration for old commitments table
        if 'commitments' in existing_tables:
            columns = [c['name'] for c in inspector.get_columns('commitments')]
            if 'assigned_to' not in columns:
                try:
                    db.session.execute('ALTER TABLE commitments ADD COLUMN assigned_to INTEGER')
                    db.session.commit()
                    print('Migration: added commitments.assigned_to column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add assigned_to column: {e}')

            # Migrate start_date format from Date to DateTime
            try:
                db.session.execute(text("UPDATE commitments SET start_date = start_date || ' 00:00:00' WHERE length(start_date) = 10"))
                db.session.commit()
                print('Migration: synchronized start_date to DateTime format')
            except Exception as e:
                db.session.rollback()
                print(f'Migration warning: start_date updates failed: {e}')

            # Migrate deadline format from Date to DateTime
            try:
                db.session.execute(text("UPDATE commitments SET deadline = deadline || ' 23:59:59' WHERE length(deadline) = 10"))
                db.session.commit()
                print('Migration: synchronized deadline to DateTime format')
            except Exception as e:
                db.session.rollback()
                print(f'Migration warning: deadline updates failed: {e}')

        # Custom historical tracker for VN tz migration
        if 'migrations' not in existing_tables:
            db.session.execute(text("CREATE TABLE migrations (id INTEGER PRIMARY KEY, name TEXT)"))
            db.session.commit()
            
        mig_check = db.session.execute(text("SELECT * FROM migrations WHERE name='tz_vn_shift'")).fetchone()
        if not mig_check:
            tables = ['labs', 'commitments', 'progress_updates', 'notifications', 'activity_logs']
            for t in tables:
                db.session.execute(text(f"UPDATE {t} SET created_at = datetime(created_at, '+7 hours') WHERE created_at IS NOT NULL"))
            db.session.execute(text("UPDATE commitments SET updated_at = datetime(updated_at, '+7 hours') WHERE updated_at IS NOT NULL"))
            db.session.execute(text("INSERT INTO migrations (name) VALUES ('tz_vn_shift')"))
            db.session.commit()
            print("Migration: shift to VN time (+7 hours) successful")

        # Migration: add full_name column to users table
        if 'users' in existing_tables:
            user_columns = [c['name'] for c in inspector.get_columns('users')]
            if 'full_name' not in user_columns:
                try:
                    db.session.execute(text('ALTER TABLE users ADD COLUMN full_name VARCHAR(100)'))
                    db.session.commit()
                    print('Migration: added users.full_name column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add full_name column: {e}')
            if 'email' not in user_columns:
                try:
                    db.session.execute(text('ALTER TABLE users ADD COLUMN email VARCHAR(120)'))
                    db.session.commit()
                    print('Migration: added users.email column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add email column: {e}')

        # Migration: add manager_id column to labs table
        if 'labs' in existing_tables:
            lab_columns = [c['name'] for c in inspector.get_columns('labs')]
            if 'manager_id' not in lab_columns:
                try:
                    db.session.execute(text('ALTER TABLE labs ADD COLUMN manager_id INTEGER REFERENCES users(id)'))
                    db.session.commit()
                    print('Migration: added labs.manager_id column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add manager_id column: {e}')

        # Migration: create lab_memberships table if it doesn't exist
        if 'lab_memberships' not in existing_tables:
            try:
                db.create_all()   # creates only missing tables
                print('Migration: created lab_memberships table')
            except Exception as e:
                print(f'Migration warning: could not create lab_memberships table: {e}')

        # Migration: add code and priority columns to commitments table
        if 'commitments' in existing_tables:
            commit_cols = [c['name'] for c in inspector.get_columns('commitments')]
            if 'code' not in commit_cols:
                try:
                    db.session.execute(text('ALTER TABLE commitments ADD COLUMN code VARCHAR(20)'))
                    db.session.commit()
                    print('Migration: added commitments.code column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add code column: {e}')
            if 'priority' not in commit_cols:
                try:
                    db.session.execute(text("ALTER TABLE commitments ADD COLUMN priority VARCHAR(20) NOT NULL DEFAULT 'Trung bình'"))
                    db.session.commit()
                    print('Migration: added commitments.priority column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add priority column: {e}')

        # Migration: create execution_items table if missing
        if 'execution_items' not in existing_tables:
            try:
                db.create_all()  # only creates missing tables
                print('Migration: created execution_items table')
            except Exception as e:
                print(f'Migration warning: could not create execution_items table: {e}')

        # Migration: add expected_finish_date column to execution_items
        if 'execution_items' in existing_tables:
            ei_cols = [c['name'] for c in inspector.get_columns('execution_items')]
            if 'expected_finish_date' not in ei_cols:
                try:
                    db.session.execute(text('ALTER TABLE execution_items ADD COLUMN expected_finish_date DATETIME'))
                    db.session.commit()
                    print('Migration: added execution_items.expected_finish_date column')
                except Exception as e:
                    db.session.rollback()
                    print(f'Migration warning: could not add expected_finish_date: {e}')

        # Migration: create execution_item_updates table if missing
        if 'execution_item_updates' not in existing_tables:
            try:
                db.create_all()  # only creates missing tables
                print('Migration: created execution_item_updates table')
            except Exception as e:
                print(f'Migration warning: could not create execution_item_updates table: {e}')




def init_db():
    """Initialize database with tables and default admin user"""
    with app.app_context():
        db.create_all()
        ensure_tables()

        if User.query.filter_by(username='manager_ai').count() == 0 and Lab.query.count() == 0:
            try:
                import seed_demo
                seed_demo.seed_all(reset=False)
            except Exception as e:
                print(f"Error executing seed_demo: {e}")


with app.app_context():
    init_db()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
