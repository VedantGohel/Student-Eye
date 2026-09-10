from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Course, Subject,
    HOD, Staff, Student,
    Attendance, AttendanceReport,
    LeaveReportStudent, LeaveReportStaff,
    FeedbackStudent, FeedbackStaff,
    NotificationStudent, NotificationStaff,
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display  = ('username', 'email', 'first_name', 'last_name', 'user_type', 'is_active')
    list_filter   = ('user_type', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    fieldsets = UserAdmin.fieldsets + (
        ('StudentEye Info', {'fields': ('user_type', 'profile_pic', 'address')}),
    )


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display  = ('name', 'created_at')
    search_fields = ('name',)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display  = ('name', 'course', 'staff')
    list_filter   = ('course',)
    search_fields = ('name',)


@admin.register(HOD)
class HODAdmin(admin.ModelAdmin):
    list_display = ('user',)


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('user', 'course')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display  = ('user', 'course', 'roll_no', 'session')
    list_filter   = ('course',)
    search_fields = ('user__first_name', 'user__last_name', 'roll_no')


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('subject', 'date')
    list_filter  = ('subject', 'date')


@admin.register(AttendanceReport)
class AttendanceReportAdmin(admin.ModelAdmin):
    list_display  = ('student', 'attendance', 'status')
    list_filter   = ('status',)


@admin.register(LeaveReportStudent)
class LeaveReportStudentAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status')
    list_filter  = ('status',)


@admin.register(LeaveReportStaff)
class LeaveReportStaffAdmin(admin.ModelAdmin):
    list_display = ('staff', 'date', 'status')
    list_filter  = ('status',)


@admin.register(FeedbackStudent)
class FeedbackStudentAdmin(admin.ModelAdmin):
    list_display = ('student', 'created_at')


@admin.register(FeedbackStaff)
class FeedbackStaffAdmin(admin.ModelAdmin):
    list_display = ('staff', 'created_at')


@admin.register(NotificationStudent)
class NotificationStudentAdmin(admin.ModelAdmin):
    list_display = ('student', 'message', 'created_at')


@admin.register(NotificationStaff)
class NotificationStaffAdmin(admin.ModelAdmin):
    list_display = ('staff', 'message', 'created_at')
