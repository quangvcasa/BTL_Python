from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app.utils import get_vn_time
from flask import url_for, has_request_context

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True, unique=True)
    password_hash = db.Column(db.String(200), nullable=False)
    # System-level role: 'admin' or 'user'.
    # Lab-specific roles (manager/member) are handled by LabMembership.
    # Legacy values 'lab_manager', 'lab_member', 'lab' are accepted for backward compat.
    role = db.Column(db.String(20), nullable=False, default='user')
    # lab_id is a convenience sync field written by the Lab membership flow.
    # Do NOT write this directly from User create/edit forms.
    lab_id = db.Column(db.Integer, db.ForeignKey('labs.id', ondelete='SET NULL'), nullable=True)
    # Membership rows (the proper relationship source of truth)
    memberships = db.relationship('LabMembership', back_populates='user',
                                  cascade='all, delete-orphan', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ------------------------------------------------------------------
    # Role helpers – kept as regular methods (not @property) so that
    # existing Jinja2 calls like current_user.is_admin() keep working.
    # ------------------------------------------------------------------

    def is_admin(self):
        """Return True if this user is a system administrator."""
        return self.role == 'admin'

    def is_lab_manager(self):
        """Return True if this user is a lab manager."""
        if self.role == 'lab_manager':
            return True
        is_manager = LabMembership.query.filter_by(user_id=self.id, role_in_lab='manager').first() is not None
        return is_manager

    def is_lab_member(self):
        """Return True if this user is a regular lab member.
        The legacy role value 'lab' is treated as an alias."""
        return self.role in ('lab_member', 'lab')

    def is_lab_user(self):
        """Return True for any non-admin user.
        Includes the new simplified 'user' role and legacy lab-specific roles."""
        return self.role in ('user', 'lab_manager', 'lab_member', 'lab')

    def display_name(self):
        """Return full_name if set, otherwise fall back to username."""
        return self.full_name or self.username

    def get_lab_membership(self):
        """Return the LabMembership row for this user, or None."""
        return LabMembership.query.filter_by(user_id=self.id).first()

    def is_lab_manager_of(self, lab_id):
        """Return True if this user is the primary manager of the given lab.
        Checks LabMembership (new design) and falls back to Lab.manager_id."""
        mem = LabMembership.query.filter_by(
            user_id=self.id, lab_id=lab_id, role_in_lab='manager'
        ).first()
        if mem:
            return True
        # Fallback: legacy manager_id on Lab
        lab = Lab.query.get(lab_id)
        return lab is not None and lab.manager_id == self.id

class LabMembership(db.Model):
    """Tracks which users belong to a Lab and their role inside that Lab.

    role_in_lab values:
      'manager' – primary manager of the lab
      'member'  – regular lab member
    """
    __tablename__ = 'lab_memberships'
    __table_args__ = (
        db.UniqueConstraint('lab_id', 'user_id', name='uq_lab_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey('labs.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role_in_lab = db.Column(db.String(20), nullable=False, default='member')  # 'manager' or 'member'
    created_at = db.Column(db.DateTime, default=get_vn_time)

    lab = db.relationship('Lab', back_populates='memberships')
    user = db.relationship('User', back_populates='memberships')

class Lab(db.Model):
    __tablename__ = 'labs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    # DEPRECATED – free-text fields kept so existing DB rows are not broken.
    # No route writes to these any more; use manager_id + LabMembership instead.
    # TODO: drop these columns and remove from DB via migration when safe.
    manager_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    # Convenience FK to the primary manager User (nullable – lab may have no manager yet).
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=get_vn_time)

    # manager User object (convenience relationship)
    manager = db.relationship('User', foreign_keys=[manager_id], backref='managed_labs')
    # All Users whose lab_id points here (legacy sync field – kept for commitment access control)
    users = db.relationship('User', foreign_keys='User.lab_id', backref='lab', lazy=True)
    # Proper membership rows
    memberships = db.relationship('LabMembership', back_populates='lab',
                                  cascade='all, delete-orphan', lazy='dynamic')
    commitments = db.relationship('Commitment', backref='lab', lazy=True, cascade='all, delete-orphan')

    def get_members(self):
        """Return list of LabMembership rows with role_in_lab='member'."""
        return self.memberships.filter_by(role_in_lab='member').all()

    def get_manager_membership(self):
        """Return the LabMembership row for the manager, or None."""
        return self.memberships.filter_by(role_in_lab='manager').first()

commitment_collaborators = db.Table('commitment_collaborators',
    db.Column('commitment_id', db.Integer, db.ForeignKey('commitments.id', ondelete='CASCADE'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
)

class Commitment(db.Model):
    __tablename__ = 'commitments'

    # Status values (single source of truth)
    STATUS_NEW             = 'new'
    STATUS_ACTIVE          = 'active'
    STATUS_OVERDUE         = 'overdue'
    STATUS_PENDING_MANAGER = 'pending_manager'
    STATUS_PENDING_ADMIN   = 'pending_admin'
    STATUS_COMPLETED       = 'completed'
    STATUS_REJECTED        = 'rejected'
    
    STATUS_LABELS = {
        STATUS_NEW: 'Mới',
        STATUS_ACTIVE: 'Đang thực hiện',
        STATUS_OVERDUE: 'Quá hạn',
        STATUS_PENDING_MANAGER: 'Chờ quản lý duyệt',
        STATUS_PENDING_ADMIN: 'Chờ Admin duyệt',
        STATUS_COMPLETED: 'Đã hoàn thành',
        STATUS_REJECTED: 'Từ chối'
    }

    STATUS_COLORS = {
        STATUS_NEW: 'secondary',
        STATUS_ACTIVE: 'primary',
        STATUS_OVERDUE: 'danger',
        STATUS_PENDING_MANAGER: 'info',
        STATUS_PENDING_ADMIN: 'warning',
        STATUS_COMPLETED: 'success',
        STATUS_REJECTED: 'danger'
    }

    PRIORITY_LOW     = 'Thấp'
    PRIORITY_MEDIUM  = 'Trung bình'
    PRIORITY_HIGH    = 'Cao'
    PRIORITY_URGENT  = 'Khẩn cấp'

    id = db.Column(db.Integer, primary_key=True)
    # Human-readable code auto-generated on creation, e.g. CAM-0042
    code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    lab_id = db.Column(db.Integer, db.ForeignKey('labs.id'), nullable=False)
    # assigned_to links to the specific user responsible for execution.
    # This is OPTIONAL at creation time – lab assignment (lab_id) is sufficient.
    # TODO: execution-phase will formalise this into ExecutionItem.
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    priority = db.Column(db.String(20), nullable=False, default='Trung bình')
    start_date = db.Column(db.DateTime, nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    progress = db.Column(db.Integer, default=0)  # 0–100
    status = db.Column(db.String(30), default=STATUS_NEW)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=get_vn_time)
    updated_at = db.Column(db.DateTime, default=get_vn_time, onupdate=get_vn_time)
    update_count = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    admin_review_note = db.Column(db.Text, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='commitments_created')
    assignee = db.relationship('User', foreign_keys=[assigned_to], backref='tasks_assigned')
    collaborators = db.relationship('User', secondary=commitment_collaborators, backref=db.backref('collaborations', lazy='dynamic'))
    submitter = db.relationship('User', foreign_keys=[submitted_by_id], backref='commitments_submitted')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id], backref='commitments_reviewed')
    progress_updates = db.relationship('ProgressUpdate', backref='commitment', lazy=True, cascade='all, delete-orphan')
    execution_items = db.relationship(
        'ExecutionItem', back_populates='commitment',
        order_by='ExecutionItem.order_no', cascade='all, delete-orphan', lazy='dynamic'
    )

    # ------------------------------------------------------------------ #
    # Auto-generate a human-readable code like CAM-0042                  #
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_code():
        last = Commitment.query.order_by(Commitment.id.desc()).first()
        next_id = (last.id + 1) if last else 1
        return f'CAM-{next_id:04d}'

    def touch(self):
        """Manually trigger an update to the commitment's timestamp and counter."""
        from app.utils import get_vn_time
        self.update_count = (self.update_count or 0) + 1
        self.updated_at = get_vn_time()

    def recalculate_progress(self):
        """Derive Commitment.progress and Commitment.status from child ExecutionItems."""
        from app.utils import get_vn_time
        items = self.execution_items.all()

        if not items:
            self.progress = 0
            if getattr(self, 'status', None) not in [self.STATUS_PENDING_MANAGER, self.STATUS_PENDING_ADMIN, self.STATUS_COMPLETED, self.STATUS_REJECTED]:
                self.status = self.STATUS_NEW
            return

        total_weight     = sum(i.weight for i in items if i.status != ExecutionItem.STATUS_REJECTED)
        completed_weight = sum(i.weight for i in items if i.status == ExecutionItem.STATUS_COMPLETED)

        if total_weight > 0:
            self.progress = min(100, int(round((completed_weight / total_weight) * 100)))
        else:
            self.progress = 0

        statuses = {i.status for i in items}
        all_done = all(i.status in (ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED) for i in items)
        any_started = bool(statuses - {ExecutionItem.STATUS_NOT_STARTED})

        terminal_admin_statuses = {
            self.STATUS_PENDING_MANAGER,
            self.STATUS_PENDING_ADMIN,
            self.STATUS_COMPLETED,
            self.STATUS_REJECTED
        }

        if getattr(self, 'status', None) in terminal_admin_statuses:
            pass # Keep review status, prevent auto status reassignment during approval chain
        elif any_started or all_done:
            self.status = self.STATUS_ACTIVE
        else:
            self.status = self.STATUS_NEW

    @property
    def is_overdue(self):
        from app.utils import get_vn_time
        return self.status not in (self.STATUS_COMPLETED, self.STATUS_REJECTED) and self.deadline < get_vn_time()

    @property
    def is_at_risk(self):
        return any(i.status in (ExecutionItem.STATUS_NEEDS_REVISION, ExecutionItem.STATUS_OVERDUE) for i in self.execution_items.all())

    def update_status(self):
        """Deprecated shim – now delegates to recalculate_progress().
        Kept so existing call sites (e.g. legacy progress_update route) don’t crash.
        """
        self.recalculate_progress()
        
    def get_status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    def get_status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')


    def get_priority_color(self):
        return {
            self.PRIORITY_URGENT: 'danger',
            self.PRIORITY_HIGH:   'warning',
            self.PRIORITY_MEDIUM: 'primary',
            self.PRIORITY_LOW:    'secondary',
        }.get(self.priority, 'secondary')

    def validate_ready_for_submit(self, actor):
        """Validates all item requirements and actor authorization.
        Returns (is_valid: bool, errors: list[str])
        """
        errors = []
        is_lead = actor.id == self.assigned_to
        is_manager = actor.is_admin() or getattr(actor, 'is_lab_manager_of', lambda x: False)(self.lab_id)
        if not (is_manager or is_lead):
            errors.append("Chỉ Phụ trách chính, Quản lý Lab hoặc Admin mới có quyền gửi xác nhận tiến độ này.")

        items = self.execution_items.all()
        if not items:
            errors.append("Không thể gửi cam kết khi chưa có hạng mục công việc nào.")

        for item in items:
            if item.status not in (ExecutionItem.STATUS_COMPLETED, ExecutionItem.STATUS_REJECTED):
                errors.append(f'Hạng mục "{item.title}" chưa hoàn tất (Trạng thái: {item.get_status_label()}).')
            if not item.has_required_evidence():
                errors.append(f'Hạng mục "{item.title}" bắt buộc phải có tài liệu minh chứng, nhưng chưa có tải lên.')

        return len(errors) == 0, errors


class ExecutionItem(db.Model):
    """A concrete sub-work item that breaks down one Commitment.

    Status lifecycle:
      not_started  →  in_progress  →  pending_review  →  completed
                                   ↓ needs_revision (loop)
      Any state   →  overdue  (when due_date passes without completion)
      Any state   →  rejected (admin/manager decision)
    """
    __tablename__ = 'execution_items'

    # ---- Status constants ------------------------------------------------ #
    STATUS_NOT_STARTED     = 'not_started'
    STATUS_IN_PROGRESS     = 'in_progress'
    STATUS_PENDING_REVIEW  = 'pending_review'
    STATUS_NEEDS_REVISION  = 'needs_revision'
    STATUS_COMPLETED       = 'completed'
    STATUS_REJECTED        = 'rejected'
    STATUS_OVERDUE         = 'overdue'

    STATUS_LABELS = {
        STATUS_NOT_STARTED:    'Chưa bắt đầu',
        STATUS_IN_PROGRESS:    'Đang làm',
        STATUS_PENDING_REVIEW: 'Chờ duyệt',
        STATUS_NEEDS_REVISION: 'Cần sửa',
        STATUS_COMPLETED:      'Hoàn thành',
        STATUS_REJECTED:       'Từ chối',
        STATUS_OVERDUE:        'Quá hạn',
    }

    STATUS_COLORS = {
        STATUS_NOT_STARTED:    'secondary',
        STATUS_IN_PROGRESS:    'primary',
        STATUS_PENDING_REVIEW: 'info',
        STATUS_NEEDS_REVISION: 'warning',
        STATUS_COMPLETED:      'success',
        STATUS_REJECTED:       'danger',
        STATUS_OVERDUE:        'danger',
    }

    # ---- Columns --------------------------------------------------------- #
    id = db.Column(db.Integer, primary_key=True)
    commitment_id = db.Column(
        db.Integer, db.ForeignKey('commitments.id', ondelete='CASCADE'), nullable=False
    )
    # Assignee is optional at this stage; execution-phase may assign later
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    order_no    = db.Column(db.Integer, nullable=False, default=0)  # display order within commitment
    start_date  = db.Column(db.DateTime, nullable=True)
    due_date    = db.Column(db.DateTime, nullable=True)
    status      = db.Column(db.String(30), nullable=False, default=STATUS_NOT_STARTED)
    weight      = db.Column(db.Float, nullable=False, default=1.0)  # relative weight for progress calc

    # Feature flags
    requires_evidence  = db.Column(db.Boolean, nullable=False, default=False)
    requires_approval  = db.Column(db.Boolean, nullable=False, default=False)

    # Optional field set/updated during progress updates
    expected_finish_date = db.Column(db.DateTime, nullable=True)

    created_by  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at  = db.Column(db.DateTime, default=get_vn_time)
    updated_at  = db.Column(db.DateTime, default=get_vn_time, onupdate=get_vn_time)

    # ---- Relationships --------------------------------------------------- #
    commitment = db.relationship('Commitment', back_populates='execution_items')
    assignee   = db.relationship('User', foreign_keys=[assigned_to],  backref='execution_items_assigned')
    creator    = db.relationship('User', foreign_keys=[created_by],   backref='execution_items_created')
    updates    = db.relationship(
        'ExecutionItemUpdate', back_populates='execution_item',
        order_by='ExecutionItemUpdate.created_at.desc()',
        cascade='all, delete-orphan', lazy='dynamic'
    )

    # ---- Helpers --------------------------------------------------------- #
    def get_status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    def get_status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    def is_overdue(self):
        return (
            self.due_date is not None
            and self.status not in (self.STATUS_COMPLETED, self.STATUS_REJECTED)
            and self.due_date < get_vn_time()
        )

    def auto_update_status(self):
        """Mark overdue if past due_date and not finished/rejected."""
        if self.is_overdue():
            self.status = self.STATUS_OVERDUE

    def latest_update(self):
        """Return the most recent ExecutionItemUpdate, or None."""
        return self.updates.first()

    def has_required_evidence(self):
        """Returns True if evidence is either not required, or has been successfully attached."""
        if not self.requires_evidence:
            return True
        for update in self.updates:
            if getattr(update, 'evidence_files', None) and update.evidence_files.count() > 0:
                return True
        return False

    def can_transition_execution_item(self, actor, target_status, is_review=False):
        """
        Centralized workflow validation state machine.
        Returns (is_valid, error_reason)
        """
        is_lead = actor.id == self.commitment.assigned_to

        if not is_review and target_status == self.STATUS_NOT_STARTED:
            return False, "Trạng thái này chỉ dùng làm mặc định. Hãy chọn trạng thái khác để ghi nhận tiến độ."

        # Allow keeping current status strictly to append notes (unless in explicit review mode)
        if not is_review and target_status == self.status:
            return True, ""

        if is_review:
            if not is_lead:
                return False, "Chỉ Phụ trách chính (Lead) hoặc Admin mới có quyền đánh giá hạng mục."
            if self.status != self.STATUS_PENDING_REVIEW:
                return False, "Chỉ có thể đánh giá khi đang ở trạng thái Chờ duyệt."
            if target_status not in [self.STATUS_COMPLETED, self.STATUS_NEEDS_REVISION, self.STATUS_REJECTED]:
                return False, "Trạng thái đánh giá không hợp lệ."
            return True, ""

        # Regular update flow
        if target_status == self.STATUS_REJECTED:
            return False, "Không thể chủ động thiết lập trạng thái 'Từ chối' khi cập nhật tiến độ."

        if target_status == self.STATUS_NEEDS_REVISION:
            return False, "Trạng thái 'Cần sửa' chỉ được thiết lập bởi Phụ trách chính trong vòng đánh giá."

        # Reopen terminal states
        if self.status in [self.STATUS_COMPLETED, self.STATUS_REJECTED]:
            if not is_lead:
                return False, "Hạng mục đã kết thúc. Vui lòng liên hệ Phụ trách chính để mở lại."
            if target_status not in [self.STATUS_IN_PROGRESS, self.STATUS_PENDING_REVIEW]:
                 return False, "Chỉ có thể mở lại chuyển qua 'Đang làm' hoặc 'Chờ duyệt'."
            return True, ""

        # Normal Working States
        if target_status in [self.STATUS_IN_PROGRESS, self.STATUS_PENDING_REVIEW]:
            return True, ""

        if target_status == self.STATUS_COMPLETED:
            if self.requires_approval:
                return False, "Hạng mục yêu cầu duyệt nên không thể bỏ qua thao tác đánh giá. Vui lòng chuyển động sang 'Chờ duyệt'."
            return True, ""

        return False, "Lỗi trạng thái hệ thống không xác định."

    def get_allowed_transitions(self, actor, is_review=False):
        """Returns valid status list by polling the core engine against all possibilities."""
        valid_statuses = []
        for st in self.STATUS_LABELS.keys():
            is_valid, _ = self.can_transition_execution_item(actor, st, is_review)
            if is_valid:
                valid_statuses.append(st)
        return valid_statuses


class ExecutionItemUpdate(db.Model):
    """Immutable history record for each status change on an ExecutionItem.

    Writeable by: assignee, admin, same-lab manager.
    NOT deleted when the item is updated – this is append-only history.
    Cascade delete is driven by the relationship on ExecutionItem.
    """
    __tablename__ = 'execution_item_updates'

    # Status values allowed for member-driven updates (subset of ExecutionItem statuses).
    # 'overdue' and 'rejected' are system/manager states, not selectable by the member.
    MEMBER_STATUSES = [
        ExecutionItem.STATUS_NOT_STARTED,
        ExecutionItem.STATUS_IN_PROGRESS,
        ExecutionItem.STATUS_PENDING_REVIEW,
        ExecutionItem.STATUS_NEEDS_REVISION,
        ExecutionItem.STATUS_COMPLETED,
    ]

    id = db.Column(db.Integer, primary_key=True)
    execution_item_id = db.Column(
        db.Integer, db.ForeignKey('execution_items.id', ondelete='CASCADE'), nullable=False
    )
    updated_by_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    update_type          = db.Column(db.String(30), nullable=False, default='progress_update')
    old_status           = db.Column(db.String(30), nullable=True)
    new_status           = db.Column(db.String(30), nullable=False)
    note                 = db.Column(db.Text, nullable=True)
    blocker_reason       = db.Column(db.Text, nullable=True)  # required when new_status in (needs_revision, pending_review + blocked)
    expected_finish_date = db.Column(db.DateTime, nullable=True)
    created_at           = db.Column(db.DateTime, default=get_vn_time)

    # ---- Relationships --------------------------------------------------- #
    execution_item = db.relationship('ExecutionItem', back_populates='updates')
    updated_by     = db.relationship('User', backref='ei_updates_made')

    # ---- Helpers --------------------------------------------------------- #
    def get_status_label(self):
        return ExecutionItem.STATUS_LABELS.get(self.new_status, self.new_status)

    def get_status_color(self):
        return ExecutionItem.STATUS_COLORS.get(self.new_status, 'secondary')

    def is_status_change(self):
        return self.old_status != self.new_status

class ExecutionItemEvidence(db.Model):
    """Stores individual uploaded evidence files attached to an ExecutionItemUpdate."""
    __tablename__ = 'execution_item_evidence'

    id = db.Column(db.Integer, primary_key=True)
    execution_item_update_id = db.Column(
        db.Integer, db.ForeignKey('execution_item_updates.id', ondelete='CASCADE'), nullable=False
    )
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename   = db.Column(db.String(255), nullable=False, unique=True)
    file_path         = db.Column(db.String(500), nullable=False)
    uploaded_by_id    = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    uploaded_at       = db.Column(db.DateTime, default=get_vn_time)

    # ---- Relationships --------------------------------------------------- #
    update_record = db.relationship(
        'ExecutionItemUpdate', 
        backref=db.backref('evidence_files', lazy='dynamic', cascade='all, delete-orphan')
    )
    uploaded_by   = db.relationship('User', backref='ei_evidence_uploaded')

class ProgressUpdate(db.Model):
    """
    [DEPRECATED] 
    This legacy model was historically used for manually pushing arbitrary progress percentages to Commitments.
    It is retained only to display historical actions in the timeline format.
    The active workflow now strictly calculates progress automatically from ExecutionItem statuses.
    """
    __tablename__ = 'progress_updates'

    id = db.Column(db.Integer, primary_key=True)
    commitment_id = db.Column(db.Integer, db.ForeignKey('commitments.id'), nullable=False)
    progress = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text)
    attachment = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=get_vn_time)

    creator = db.relationship('User', backref='progress_updates')


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='info')  # info, warning, success, danger
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=get_vn_time)

    user = db.relationship('User', backref='notifications')

    @staticmethod
    def create(user_id, title, message, type='info', link=None):
        notif = Notification(user_id=user_id, title=title, message=message, type=type, link=link)
        db.session.add(notif)
        return notif

    @staticmethod
    def notify_lab_assignment(commitment, manager_id):
        title = "Cam kết mới được giao"
        message = f"Lab của bạn vừa nhận được cam kết mới: [{commitment.code}] {commitment.title}."
        link = url_for('commitments_detail', commitment_id=commitment.id, _external=False)
        return Notification.create(manager_id, title, message, 'info', link)

    @staticmethod
    def notify_ei_assignment(item, assignee_id):
        title = "Phân công hạng mục"
        message = f"Bạn được phân công phụ trách hạng mục: '{item.title}'."
        link = url_for('commitments_detail', commitment_id=item.commitment_id, _external=False)
        return Notification.create(assignee_id, title, message, 'info', link)

    @staticmethod
    def notify_ei_pending_review(item, manager_id):
        title = "Hạng mục chờ đánh giá"
        message = f"Hạng mục '{item.title}' đang chờ bạn đánh giá."
        link = url_for('commitments_detail', commitment_id=item.commitment_id, _external=False)
        return Notification.create(manager_id, title, message, 'warning', link)

    @staticmethod
    def notify_ei_reviewed(item, assignee_id, review_note, status):
        title = "Kết quả đánh giá hạng mục"
        message = f"Hạng mục '{item.title}' đã có kết quả: {item.get_status_label()}."
        if review_note:
            message += f" Nhận xét: {review_note}"
        ntype = "success" if status == ExecutionItem.STATUS_COMPLETED else ("warning" if status == ExecutionItem.STATUS_NEEDS_REVISION else "danger")
        link = url_for('commitments_detail', commitment_id=item.commitment_id, _external=False)
        return Notification.create(assignee_id, title, message, ntype, link)

    @staticmethod
    def notify_ei_reassigned(item, old_assignee_id, new_assignee_id, reason):
        link = url_for('commitments_detail', commitment_id=item.commitment_id, _external=False)
        if old_assignee_id:
            msg_old = f"Hạng mục '{item.title}' đã được phân công cho người khác. Lý do: {reason}"
            Notification.create(old_assignee_id, "Thay đổi phụ trách", msg_old, 'info', link)
        if new_assignee_id:
            msg_new = f"Bạn được giao tiếp quản hạng mục: '{item.title}'. Lý do: {reason}"
            Notification.create(new_assignee_id, "Phân công hạng mục", msg_new, 'info', link)

    @staticmethod
    def notify_commitment_submitted(commitment, admin_id):
        title = "Cam kết chờ nghiệm thu"
        message = f"Cam kết '{commitment.code}' đã được Trưởng nhóm Lab nộp và đang chờ Quản lý duyệt."
        link = url_for('commitments_detail', commitment_id=commitment.id, _external=False)
        return Notification.create(admin_id, title, message, 'info', link)

    @staticmethod
    def notify_commitment_reviewed(commitment, manager_id, decision, review_note):
        if manager_id is None:
            return None
        title = "Quyết định nghiệm thu Admin"
        message = f"Cam kết '{commitment.code}' đã có quyết định từ Admin: {decision}."
        if review_note:
            message += f" Nhận xét: {review_note}"
        ntype = "success" if decision == Commitment.STATUS_COMPLETED else "danger"
        
        try:
            if has_request_context():
                link = url_for('commitments_detail', commitment_id=commitment.id, _external=False)
            else:
                link = f"/commitments/detail/{commitment.id}"
        except Exception:
            link = f"/commitments/detail/{commitment.id}"
            
        return Notification.create(manager_id, title, message, ntype, link)

    @staticmethod
    def notify_ei_overdue(item, user_id):
        title = f"Quá hạn hạng mục: {item.title}"
        message = f"Hạng mục '{item.title}' đã quá hạn (deadline: {item.due_date.strftime('%d/%m/%Y %H:%M')})"
        link = url_for('commitments_detail', commitment_id=item.commitment_id, _external=False)
        # Deduplication check: Avoid sending exact same unread overdue notification.
        existing = Notification.query.filter_by(user_id=user_id, title=title, is_read=False).first()
        if not existing:
            return Notification.create(user_id, title, message, 'danger', link)
        return existing

    @staticmethod
    def notify_commitment_overdue(commitment, user_id):
        title = f"Quá hạn cam kết: {commitment.code}"
        message = f"Cam kết '{commitment.title}' đã quá hạn (deadline: {commitment.deadline.strftime('%d/%m/%Y %H:%M')})"
        link = url_for('commitments_detail', commitment_id=commitment.id, _external=False)
        # Deduplication check: Avoid sending exact same unread overdue notification.
        existing = Notification.query.filter_by(user_id=user_id, title=title, is_read=False).first()
        if not existing:
            return Notification.create(user_id, title, message, 'danger', link)
        return existing

    @staticmethod
    def notify_deletion(commitment_title, user_id):
        """Notify when a commitment is deleted"""
        title = f"Cam kết bị xóa: {commitment_title}"
        message = f"Cam kết '{commitment_title}' bạn được giao đã bị Admin xóa khỏi hệ thống."
        link = "/dashboard"
        return Notification.create(user_id, title, message, 'danger', link)


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # CREATE, UPDATE, DELETE, LOGIN, LOGOUT
    entity_type = db.Column(db.String(50))  # Commitment, Lab, User, ProgressUpdate
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=get_vn_time)

    user = db.relationship('User', backref='activity_logs')

    @staticmethod
    def log(user_id, action, entity_type=None, entity_id=None, details=None, ip_address=None):
        log = ActivityLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address
        )
        db.session.add(log)
        return log