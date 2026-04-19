# System Acceptance Test Checklist (Workflow Validation)

This manual testing checklist covers end-to-end validation for the ExecutionItem progress workflow, ensuring Role limits, assignments, evidence compliance, and validation requirements are functionally secure. 

It is recommended to run `python seed_demo.py` to reset the environment before testing each persona. 
All generic accounts follow the password `pass123` unless otherwise specified.

---

## 1. Role: Lab Member (e.g., `member_ai_1`)
*Test focus: Assignee isolation, updates, evidence compliance.*

### Scenario 1.1: Dashboard Scoping
- [] **Action:** Log in as `member_ai_1` and navigate to the Dashboard.
- [] **Expected Result:** The user sees statistics strictly for `Execution Items` specifically assigned to `member_ai_1`. "Hạng mục Cần sửa" (Needs Revision) and "Quá hạn" (Overdue) reflect valid local constraints. No other member's tasks are visible.

### Scenario 1.2: Blocking Illegal Item Creation
- [] **Action:** Attempt to access `/commitments/1/execution-items/create` directly via URL.
- [] **Expected Result:** Connection is intercepted. The system redirects back to the commitment detail page and flashes *"Bạn không có quyền thêm hạng mục thực hiện."* (Unauthorized access).

### Scenario 1.3: Valid Progress Update (No Evidence Required)
- [] **Precondition:** Select an `ExecutionItem` in `STATUS_NOT_STARTED` or `STATUS_IN_PROGRESS` assigned to the member.
- [] **Action:** Click "Cập nhật", set status to `Đang làm` (In Progress), and submit without note.
- [] **Expected Result:** Form throws a validation error: *"Phải có ghi chú cho lần cập nhật này."*
- [] **Action:** Add a note and resubmit.
- [] **Expected Result:** Success flash. The update appears in the timeline without over-writing past updates.

### Scenario 1.4: Workflow Review Escalation
- [] **Action:** Update an active task to `Chờ duyệt` (Pending Review).
- [] **Expected Result:** The status successfully transitions. A backend notification is securely dispatched to the Lab Manager (`manager_ai`).

### Scenario 1.5: Valid Progress Update Bypassing Manager Review
- [] **Precondition:** Select an `ExecutionItem` that has `requires_approval = False`.
- [] **Action:** Attempt to select `Hoàn thành` (Completed) directly in the update dropdown.
- [] **Expected Result:** Operation successful. Since manager approval is not required, the member can self-close the execution item natively.

---

## 2. Role: Lab Manager (e.g., `manager_ai`)
*Test focus: Manager overrides, reviews, cross-lab security, admin-submission.*

### Scenario 2.1: Assuring Clean Assignment Boundaries
- [] **Action:** Navigate to an AI Lab commitment, and click "Giao việc" (Create/Assign Execution Item).
- [] **Expected Result:** The "Người phụ trách" drop-down exclusively displays users physically tied to `AI Lab` (e.g., `member_ai_1`, `member_ai_2`). Users from IoT Lab (`member_iot_1`) are categorically unreachable.

### Scenario 2.2: Cross-Lab Access Rejection
- [] **Precondition:** `manager_ai` logged in. Note the ID of an IoT Lab commitment (e.g., `CAM-IOT-01` -> ID 5).
- [] **Action:** Open the commitment via explicit URL, click "Đánh giá" on any pending IoT task, or attempt to re-assign an item within it.
- [] **Expected Result:** Backend forcibly rejects the action with *"Bạn không có quyền đánh giá hạng mục này."* The Lab manager boundary cannot be broken.

### Scenario 2.3: Rejecting an Execution Item (Needs Revision)
- [] **Precondition:** Navigate to an item in `Chờ duyệt` (Pending Review).
- [] **Action:** Click "Đánh giá" (Review) -> Select `Cần sửa` -> Leave note blank.
- [] **Expected Result:** Form intercepts the request: *"Phải có nhận xét khi yêu cầu sửa đổi hoặc từ chối."*
- [] **Action:** Provide a block reason/note and submit.
- [] **Expected Result:** Status shifts successfully to `Needs Revision`.

### Scenario 2.4: Rejecting Defective Admin Submission 
- [] **Precondition:** Find an Active Commitment (`CAM-AI-03`). Wait to submit it to Admin. Note that one of the Execution Items is `needs_revision`.
- [] **Action:** Click "Gửi kiểm duyệt" (Submit for Review).
- [] **Expected Result:** The system denies submission, outputting explicitly: *"Hạng mục [Title] chưa hoàn tất (Trạng thái: Cần sửa)."* The parent Commitment safely retains its `Đang thực hiện` status.

---

## 3. Role: System Admin (`admin`)
*Test focus: Final approvals, global reach, preventing workflow overrides.*

### Scenario 3.1: Global Worklist Recognition
- [] **Action:** Log in as `admin` and view the Dashboard.
- [] **Expected Result:** Total Execution Items, Total Commitments, and `Chờ Admin duyệt` (Pending Admin Review) are accurate against the platform limits natively across all labs. The Admin seamlessly sees `AI LAB` and `IOT LAB` stats.

### Scenario 3.2: Legacy Direct Progress Dead-end Route
- [] **Precondition:** Navigate to `/progress/update/1` forcibly through browser URL.
- [] **Action:** Try to manipulate the old commitment-level direct progress.
- [] **Expected Result:** Bounced inherently. Flash outputs: *"Commitment progress is now calculated from execution items and cannot be updated directly."*

### Scenario 3.3: Finalizing Verified Workflows
- [] **Precondition:** A Commitment securely rests in `Chờ admin duyệt` (STATUS_PENDING_ADMIN_REVIEW). 
- [] **Action:** Access Dashboard, hit "Duyệt" (Review). Select `Đã nghiệm thu` (Approved) and Submit.
- [] **Expected Result:** Overall tracking status is completely finalized to Approved. Notifications dynamically route to the `manager_ai` and respective `member_ai` confirming system conclusion.
