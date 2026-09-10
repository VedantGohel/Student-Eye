from django.db import models
from django.contrib.auth.models import AbstractUser


# ---------------------------------------------------------------------------
# Custom User — single user table with role field
# ---------------------------------------------------------------------------

class CustomUser(AbstractUser):
    HOD     = 1
    STAFF   = 2
    STUDENT = 3

    USER_TYPE_CHOICES = (
        (HOD,     'HOD'),
        (STAFF,   'Staff'),
        (STUDENT, 'Student'),
    )

    user_type       = models.IntegerField(default=HOD, choices=USER_TYPE_CHOICES)
    profile_pic     = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    address         = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_user_type_display()})"


# ---------------------------------------------------------------------------
# Course (e.g. B.Tech Computer Engineering)
# ---------------------------------------------------------------------------

class Course(models.Model):
    name       = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Subject (e.g. Data Structures)
# ---------------------------------------------------------------------------

class Subject(models.Model):
    name       = models.CharField(max_length=255)
    course     = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='subjects')
    staff      = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True,
                                   limit_choices_to={'user_type': CustomUser.STAFF},
                                   related_name='subjects_taught')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.course.name})"


# ---------------------------------------------------------------------------
# HOD profile
# ---------------------------------------------------------------------------

class HOD(models.Model):
    user       = models.OneToOneField(CustomUser, on_delete=models.CASCADE,
                                      related_name='hod_profile')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"HOD: {self.user.get_full_name()}"


# ---------------------------------------------------------------------------
# Staff (Professor) profile
# ---------------------------------------------------------------------------

class Staff(models.Model):
    user       = models.OneToOneField(CustomUser, on_delete=models.CASCADE,
                                      related_name='staff_profile')
    course     = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Staff: {self.user.get_full_name()}"


# ---------------------------------------------------------------------------
# Student profile
# ---------------------------------------------------------------------------

class Student(models.Model):
    user       = models.OneToOneField(CustomUser, on_delete=models.CASCADE,
                                      related_name='student_profile')
    course     = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    session    = models.CharField(max_length=50, blank=True)   # e.g. "2023-24"
    roll_no    = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Student: {self.user.get_full_name()} ({self.roll_no})"


# ---------------------------------------------------------------------------
# Attendance (per subject, per student, per date)
# ---------------------------------------------------------------------------

class Attendance(models.Model):
    subject    = models.ForeignKey(Subject, on_delete=models.CASCADE)
    date       = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('subject', 'date')

    def __str__(self):
        return f"{self.subject.name} — {self.date}"


class AttendanceReport(models.Model):
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE)
    student    = models.ForeignKey(Student, on_delete=models.CASCADE)
    status     = models.BooleanField(default=False)   # True = Present
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('attendance', 'student')

    def __str__(self):
        return f"{self.student} — {'Present' if self.status else 'Absent'}"


# ---------------------------------------------------------------------------
# Leave requests
# ---------------------------------------------------------------------------

class LeaveReportStudent(models.Model):
    PENDING  = 0
    APPROVED = 1
    REJECTED = 2

    STATUS_CHOICES = (
        (PENDING,  'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    )

    student    = models.ForeignKey(Student, on_delete=models.CASCADE)
    date       = models.CharField(max_length=60)
    message    = models.TextField()
    status     = models.IntegerField(default=PENDING, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Leave: {self.student} — {self.date}"


class LeaveReportStaff(models.Model):
    PENDING  = 0
    APPROVED = 1
    REJECTED = 2

    STATUS_CHOICES = (
        (PENDING,  'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    )

    staff      = models.ForeignKey(Staff, on_delete=models.CASCADE)
    date       = models.CharField(max_length=60)
    message    = models.TextField()
    status     = models.IntegerField(default=PENDING, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Leave: {self.staff} — {self.date}"


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackStudent(models.Model):
    student  = models.ForeignKey(Student, on_delete=models.CASCADE)
    feedback = models.TextField()
    reply    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback from {self.student}"


class FeedbackStaff(models.Model):
    staff    = models.ForeignKey(Staff, on_delete=models.CASCADE)
    feedback = models.TextField()
    reply    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback from {self.staff}"


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationStudent(models.Model):
    student  = models.ForeignKey(Student, on_delete=models.CASCADE)
    message  = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification → {self.student}"


class NotificationStaff(models.Model):
    staff    = models.ForeignKey(Staff, on_delete=models.CASCADE)
    message  = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification → {self.staff}"
