import os
from datetime import timedelta
from sqlalchemy import text
from app import app, db
from app.models import (User, Lab, LabMembership, Commitment, ExecutionItem, 
                    ExecutionItemUpdate, ExecutionItemEvidence, Notification)
from app.utils import get_vn_time

def seed_all(reset=False):
    with app.app_context():
        if reset:
            print("Clearing existing data...")
            ExecutionItemEvidence.query.delete()
            ExecutionItemUpdate.query.delete()
            ExecutionItem.query.delete()
            Commitment.query.delete()
            LabMembership.query.delete()
            Notification.query.delete()
            
            # Clear Lab manager_id FK constraint before deleting users
            for lab in Lab.query.all():
                lab.manager_id = None
            db.session.commit()
            
            Lab.query.delete()
            # Careful: keep admin!
            User.query.filter(User.username != 'admin').delete()
            db.session.commit()
            print("Database cleaned.")
            
        # Check if already seeded
        if User.query.filter_by(username='manager_ai').first():
            print("Seed data already present. Skipping.")
            return

        print("Seeding Users...")
        # Make sure admin exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', full_name='System Admin', role='admin', email='demo.admin@ptit.edu.vn')
            admin.set_password('admin123')
            db.session.add(admin)

        # Build users 
        users_data = [
            ('manager_ai', 'AI Manager', 'lab_manager', 'manager.ai@ptit.edu.vn'),
            ('member_ai_1', 'AI Member 1', 'member', 'member1.ai@ptit.edu.vn'),
            ('member_ai_2', 'AI Member 2', 'member', 'member2.ai@ptit.edu.vn'),
            
            ('manager_iot', 'IoT Manager', 'lab_manager', 'manager.iot@ptit.edu.vn'),
            ('member_iot_1', 'IoT Member 1', 'member', 'member1.iot@ptit.edu.vn'),
            ('member_iot_2', 'IoT Member 2', 'member', 'member2.iot@ptit.edu.vn'),
            
            ('manager_net', 'Network Manager', 'lab_manager', 'manager.net@ptit.edu.vn'),
            ('member_net_1', 'Network Member 1', 'member', 'member1.net@ptit.edu.vn'),
        ]
        
        user_map = {}
        for (uname, fname, role, email) in users_data:
            u = User(username=uname, full_name=fname, role=role, email=email)
            u.set_password('pass123')
            db.session.add(u)
            user_map[uname] = u
            
        db.session.commit()

        print("Seeding Labs & Memberships...")
        labs_data = [
            ('Phòng thí nghiệm AI', 'Nghiên cứu ứng dụng Trí tuệ Nhân tạo', 'manager_ai', ['member_ai_1', 'member_ai_2']),
            ('Phòng thí nghiệm IoT', 'Phát triển thiết bị Internet of Things', 'manager_iot', ['member_iot_1', 'member_iot_2']),
            ('Phòng thí nghiệm Mạng', 'Nghiên cứu an toàn thông tin & Truyền thông', 'manager_net', ['member_net_1']),
        ]
        
        lab_map = {}
        for (lname, ldesc, mname, members) in labs_data:
            manager_user = user_map[mname]
            lab = Lab(name=lname, description=ldesc, manager_id=manager_user.id)
            db.session.add(lab)
            db.session.flush() # get lab.id
            lab_map[lname] = lab
            
            # Create Manager Membership
            db.session.add(LabMembership(lab_id=lab.id, user_id=manager_user.id, role_in_lab='manager'))
            
            # Create Member Memberships
            for m in members:
                mem_user = user_map[m]
                db.session.add(LabMembership(lab_id=lab.id, user_id=mem_user.id, role_in_lab='member'))
                
        db.session.commit()

        now = get_vn_time()
        
        print("Seeding Commitments and Execution Items...")
        
        # ---------------------------------------------------------
        # AI Lab Commitments
        # ---------------------------------------------------------
        ai_lab = lab_map['Phòng thí nghiệm AI']
        
        # 1. Completed & Approved
        cam1 = Commitment(
            code='CAM-AI-01', title='Phát triển Mô hình Ngôn ngữ VN',
            lab_id=ai_lab.id, start_date=now - timedelta(days=60), deadline=now - timedelta(days=10),
            progress=100, status=Commitment.STATUS_APPROVED
        )
        db.session.add(cam1)
        db.session.flush()
        
        ei1 = ExecutionItem(
            commitment_id=cam1.id, assigned_to=user_map['member_ai_1'].id, title='Thu thập dữ liệu',
            start_date=now - timedelta(days=60), due_date=now - timedelta(days=50), status=ExecutionItem.STATUS_COMPLETED
        )
        ei2 = ExecutionItem(
            commitment_id=cam1.id, assigned_to=user_map['member_ai_2'].id, title='Huấn luyện mô hình',
            requires_evidence=True, requires_approval=True, start_date=now - timedelta(days=50), 
            due_date=now - timedelta(days=20), status=ExecutionItem.STATUS_COMPLETED
        )
        db.session.add_all([ei1, ei2])
        db.session.flush()
        
        # Add a rich history log for ei2 showing evidence uploaded and completion
        u1 = ExecutionItemUpdate(execution_item_id=ei2.id, updated_by_id=user_map['member_ai_2'].id, new_status=ExecutionItem.STATUS_PENDING_REVIEW, note="Đã up model weights.")
        db.session.add(u1)
        db.session.flush()
        evi = ExecutionItemEvidence(execution_item_update_id=u1.id, original_filename='model_v1.pth', stored_filename='demo_model_v1.pth', file_path='/demo_model_v1.pth', uploaded_by_id=user_map['member_ai_2'].id)
        u2 = ExecutionItemUpdate(execution_item_id=ei2.id, updated_by_id=user_map['manager_ai'].id, old_status=ExecutionItem.STATUS_PENDING_REVIEW, new_status=ExecutionItem.STATUS_COMPLETED, note="Chất lượng tốt.")
        db.session.add_all([evi, u2])

        # 2. Pending Admin Review
        cam2 = Commitment(
            code='CAM-AI-02', title='Hệ thống Demo Nhận diện Khuôn mặt',
            lab_id=ai_lab.id, start_date=now - timedelta(days=30), deadline=now + timedelta(days=15),
            progress=100, status=Commitment.STATUS_PENDING_ADMIN_REVIEW
        )
        db.session.add(cam2)
        db.session.flush()
        ei3 = ExecutionItem(
            commitment_id=cam2.id, assigned_to=user_map['member_ai_1'].id, title='Viết UI',
            due_date=now - timedelta(days=5), status=ExecutionItem.STATUS_COMPLETED
        )
        db.session.add(ei3)
        db.session.flush()
        # Admin pending means items are fully completed
        db.session.add(ExecutionItemUpdate(execution_item_id=ei3.id, updated_by_id=user_map['manager_ai'].id, new_status=ExecutionItem.STATUS_COMPLETED))


        # 3. In Progress (Needs Revision inside)
        cam3 = Commitment(
            code='CAM-AI-03', title='Tối ưu Hiệu suất Model',
            lab_id=ai_lab.id, start_date=now - timedelta(days=10), deadline=now + timedelta(days=30),
            progress=50, status=Commitment.STATUS_ACTIVE
        )
        db.session.add(cam3)
        db.session.flush()
        ei4 = ExecutionItem(
            commitment_id=cam3.id, assigned_to=user_map['member_ai_1'].id, title='Benchmark hệ thống',
            due_date=now + timedelta(days=5), status=ExecutionItem.STATUS_COMPLETED
        )
        ei5 = ExecutionItem(
            commitment_id=cam3.id, assigned_to=user_map['member_ai_2'].id, title='Refactor code C++',
            due_date=now + timedelta(days=15), status=ExecutionItem.STATUS_NEEDS_REVISION
        )
        db.session.add_all([ei4, ei5])
        db.session.flush()
        
        # History for needs revision
        db.session.add(ExecutionItemUpdate(execution_item_id=ei5.id, updated_by_id=user_map['member_ai_2'].id, new_status=ExecutionItem.STATUS_PENDING_REVIEW, note="Xong code nháp"))
        db.session.add(ExecutionItemUpdate(execution_item_id=ei5.id, updated_by_id=user_map['manager_ai'].id, old_status=ExecutionItem.STATUS_PENDING_REVIEW, new_status=ExecutionItem.STATUS_NEEDS_REVISION, note="Code bị memory leak! Vui lòng sửa gấp.", blocker_reason="Lỗi rò rỉ bộ nhớ backend."))


        # 4. Overdue
        cam4 = Commitment(
            code='CAM-AI-04', title='Dự án Quá Hạn Phân Tích',
            lab_id=ai_lab.id, start_date=now - timedelta(days=90), deadline=now - timedelta(days=10),
            progress=0, status=Commitment.STATUS_OVERDUE
        )
        db.session.add(cam4)
        db.session.flush()
        ei6 = ExecutionItem(
            commitment_id=cam4.id, assigned_to=user_map['member_ai_1'].id, title='Tìm kiếm Dataset',
            due_date=now - timedelta(days=20), status=ExecutionItem.STATUS_OVERDUE
        )
        db.session.add(ei6)

        # ---------------------------------------------------------
        # IoT Lab Commitments
        # ---------------------------------------------------------
        iot_lab = lab_map['Phòng thí nghiệm IoT']
        
        # 5. Newly Assigned
        cam5 = Commitment(
            code='CAM-IOT-01', title='Mạng Cảm biến Nông nghiệp',
            lab_id=iot_lab.id, start_date=now - timedelta(days=2), deadline=now + timedelta(days=60),
            progress=0, status=Commitment.STATUS_ASSIGNED
        )
        db.session.add(cam5)
        db.session.flush()
        ei7 = ExecutionItem(
            commitment_id=cam5.id, assigned_to=user_map['member_iot_1'].id, title='Mua linh kiện Arduino',
            due_date=now + timedelta(days=10), status=ExecutionItem.STATUS_NOT_STARTED
        )
        db.session.add(ei7)
        
        # 6. Commitment Needs Revision (Admin rejected!)
        cam6 = Commitment(
            code='CAM-IOT-02', title='Smart Home Hub Controller',
            lab_id=iot_lab.id, start_date=now - timedelta(days=30), deadline=now + timedelta(days=20),
            progress=50, status=Commitment.STATUS_NEEDS_REVISION
        )
        db.session.add(cam6)
        db.session.flush()
        ei8 = ExecutionItem( # Still in progress / rejected mapping context
            commitment_id=cam6.id, assigned_to=user_map['member_iot_2'].id, title='Lập trình Firmware',
            due_date=now + timedelta(days=5), status=ExecutionItem.STATUS_PENDING_REVIEW
        )
        db.session.add(ei8)

        db.session.commit()
        print("Demo data seeded successfully!")

if __name__ == '__main__':
    # You can force a reset by passing True
    seed_all(reset=True)
