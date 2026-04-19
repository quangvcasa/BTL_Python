import os
from datetime import timedelta
from app import app
from app.models import db, User, Lab, LabMembership, Commitment, ExecutionItem, ExecutionItemUpdate, Notification, ActivityLog
from app.utils import get_vn_time
from werkzeug.security import generate_password_hash

def clear_db():
    print("Clearing out old data...")
    # Be careful! This wipes existing tables to avoid duplicate unique constraints.
    db.session.query(ActivityLog).delete()
    db.session.query(Notification).delete()
    db.session.query(ExecutionItemUpdate).delete()
    db.session.query(ExecutionItem).delete()
    db.session.query(Commitment).delete()
    db.session.query(LabMembership).delete()
    db.session.query(Lab).delete()
    db.session.query(User).delete()
    db.session.commit()
    print("Database cleared.\n")

def seed():
    with app.app_context():
        # UNCOMMENT THE LINE BELOW IF YOU WANT A COMPLETELY FRESH DB BEFORE RUNNING
        # clear_db()

        print("1/4: Creating demo users...")
        now = get_vn_time()
        
        # Admins
        admin = User(username='admin_demo', email='admin@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='admin', full_name='Global Admin')
        
        # Managers
        mgr_alpha = User(username='mgr_alpha', email='m_alpha@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='Alpha Manager')
        mgr_beta = User(username='mgr_beta', email='m_beta@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='Beta Manager')
        
        # Members
        mem1_alpha = User(username='mem1_alpha', email='m1_alpha@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='Alice Student')
        mem2_alpha = User(username='mem2_alpha', email='m2_alpha@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='Bob Student')
        
        mem1_beta = User(username='mem1_beta', email='m1_beta@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='Charlie Student')
        mem2_beta = User(username='mem2_beta', email='m2_beta@ptit.edu.vn', password_hash=generate_password_hash('123456'), role='user', full_name='David Student')
        
        db.session.add_all([admin, mgr_alpha, mgr_beta, mem1_alpha, mem2_alpha, mem1_beta, mem2_beta])
        db.session.commit()

        print("2/4: Creating labs...")
        lab_alpha = Lab(name='AI Research Lab (Alpha)', description='Lab nghiên cứu Deep Learning.', manager_id=mgr_alpha.id)
        lab_beta = Lab(name='IoT Lab (Beta)', description='Lab nghiên cứu phần cứng.', manager_id=mgr_beta.id)
        db.session.add_all([lab_alpha, lab_beta])
        db.session.commit()

        # Memberships mapping
        db.session.add_all([
            LabMembership(user_id=mgr_alpha.id, lab_id=lab_alpha.id, role_in_lab='manager'),
            LabMembership(user_id=mem1_alpha.id, lab_id=lab_alpha.id, role_in_lab='member'),
            LabMembership(user_id=mem2_alpha.id, lab_id=lab_alpha.id, role_in_lab='member'),
            LabMembership(user_id=mgr_beta.id, lab_id=lab_beta.id, role_in_lab='manager'),
            LabMembership(user_id=mem1_beta.id, lab_id=lab_beta.id, role_in_lab='member'),
            LabMembership(user_id=mem2_beta.id, lab_id=lab_beta.id, role_in_lab='member'),
        ])
        
        # Auto-update legacy `lab_id` columns since old template views sometimes rely on `current_user.lab_id`
        for r in [mgr_alpha, mem1_alpha, mem2_alpha]: r.lab_id = lab_alpha.id
        for r in [mgr_beta, mem1_beta, mem2_beta]: r.lab_id = lab_beta.id
        db.session.commit()

        print("3/4: Creating commitments...")
        # C1: Pending Admin Review (Lab Alpha) - Shows Admin the "Needs Check" metric, Lab Manager the "Submitted" tag
        c1 = Commitment(code='CAM-0001', title='Xuất bản bài báo Q1 AI', lab_id=lab_alpha.id, priority='Cao', start_date=now - timedelta(days=30), deadline=now + timedelta(days=10), status=Commitment.STATUS_PENDING_ADMIN_REVIEW, created_by=admin.id, submitted_by_id=mgr_alpha.id, submitted_at=now)
        
        # C2: Needs Revision by Admin (Lab Alpha) - Gives Lab Alpha Manager an actionable failed task to fix
        c2 = Commitment(code='CAM-0002', title='Xây dựng Data Center', lab_id=lab_alpha.id, priority='Khẩn cấp', start_date=now - timedelta(days=10), deadline=now + timedelta(days=5), status=Commitment.STATUS_NEEDS_REVISION, created_by=admin.id, admin_review_note="Thiếu báo cáo tài chính vòng 2", reviewed_by_id=admin.id, reviewed_at=now)
        
        # C3: In Progress (Lab Beta) - Holds the majority of the messy ExecutionItems (pending review, overdue, needs revision)
        c3 = Commitment(code='CAM-0003', title='Triển khai Board mạch nhúng', lab_id=lab_beta.id, priority='Trung bình', start_date=now - timedelta(days=15), deadline=now + timedelta(days=20), status=Commitment.STATUS_ACTIVE, created_by=admin.id)
        
        # C4: Fully Approved (Lab Beta) - Acts as a pristine historical success for tracking
        c4 = Commitment(code='CAM-0004', title='Nghiệm thu phần mềm', lab_id=lab_beta.id, priority='Thấp', start_date=now - timedelta(days=60), deadline=now - timedelta(days=5), status=Commitment.STATUS_APPROVED, created_by=admin.id, progress=100)
        
        db.session.add_all([c1, c2, c3, c4])
        db.session.commit()

        print("4/4: Weaving Execution Items & Logs...")
        # Items for fully-completed C1
        ei1 = ExecutionItem(commitment_id=c1.id, title='Thu thập dữ liệu', assigned_to=mem1_alpha.id, order_no=1, weight=1, status=ExecutionItem.STATUS_COMPLETED, created_by=mgr_alpha.id)
        ei2 = ExecutionItem(commitment_id=c1.id, title='Train model', assigned_to=mem2_alpha.id, order_no=2, weight=2, status=ExecutionItem.STATUS_COMPLETED, created_by=mgr_alpha.id)
        
        # Items for admin-rejected C2
        ei3 = ExecutionItem(commitment_id=c2.id, title='Lập hồ sơ tài chính', assigned_to=mem1_alpha.id, order_no=1, weight=1, status=ExecutionItem.STATUS_COMPLETED, created_by=mgr_alpha.id)
        
        # Items for messy in-progress C3 (This demonstrates exactly what students and managers deal with)
        ei4_revise = ExecutionItem(commitment_id=c3.id, title='Hàn PCB', assigned_to=mem1_beta.id, order_no=1, weight=1, status=ExecutionItem.STATUS_NEEDS_REVISION, created_by=mgr_beta.id)
        ei5_pending = ExecutionItem(commitment_id=c3.id, title='Kiểm thử', assigned_to=mem2_beta.id, order_no=2, weight=1, status=ExecutionItem.STATUS_PENDING_REVIEW, created_by=mgr_beta.id, due_date=now - timedelta(days=1)) # Trễ hạn
        ei6_reassign = ExecutionItem(commitment_id=c3.id, title='Lập trình Firmware', assigned_to=mem1_beta.id, order_no=3, weight=2, status=ExecutionItem.STATUS_IN_PROGRESS, created_by=mgr_beta.id, due_date=now + timedelta(days=5))
        
        db.session.add_all([ei1, ei2, ei3, ei4_revise, ei5_pending, ei6_reassign])
        db.session.commit()

        # Generate realistic Update logs for the Timeline API
        up1 = ExecutionItemUpdate(execution_item_id=ei4_revise.id, updated_by_id=mgr_beta.id, update_type='review_action', old_status=ExecutionItem.STATUS_PENDING_REVIEW, new_status=ExecutionItem.STATUS_NEEDS_REVISION, note='Mối hàn chưa đẹp, làm lại từ mạch thứ 3.')
        up2 = ExecutionItemUpdate(execution_item_id=ei6_reassign.id, updated_by_id=mgr_beta.id, update_type='reassignment', old_status=ExecutionItem.STATUS_NOT_STARTED, new_status=ExecutionItem.STATUS_NOT_STARTED, note='Nhân sự ốm, chuyển từ David sang Charlie.')
        db.session.add_all([up1, up2])
        db.session.commit()

        # Recalculate physical progress to fix standard UI limits
        for c in [c1, c2, c3, c4]:
            c.recalculate_progress()
        db.session.commit()
        
        print("Success! Demo layout cleanly established.")

if __name__ == '__main__':
    seed()
