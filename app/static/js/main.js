// PTIT Lab Progress Management - Main JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Form validation
    const forms = document.querySelectorAll('.needs-validation');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Date validation for commitment form
    const startDateInput = document.getElementById('start_date');
    const deadlineInput = document.getElementById('deadline');

    if (startDateInput && deadlineInput) {
        deadlineInput.addEventListener('change', function() {
            if (startDateInput.value && deadlineInput.value) {
                if (new Date(deadlineInput.value) < new Date(startDateInput.value)) {
                    deadlineInput.setCustomValidity('Hạn hoàn thành phải sau ngày bắt đầu');
                } else {
                    deadlineInput.setCustomValidity('');
                }
            }
        });
    }

    // Confirm delete
    window.confirmDelete = function(id, name) {
        return confirm(`Bạn có chắc muốn xóa "${name}"?`);
    };
});