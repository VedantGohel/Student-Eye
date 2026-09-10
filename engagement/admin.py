from django.contrib import admin
from .models import EngagementSession, StudentAttentionScore, FrameEmotionLog


@admin.register(EngagementSession)
class EngagementSessionAdmin(admin.ModelAdmin):
    list_display  = ('id', 'staff', 'subject', 'session_date', 'status', 'avg_attention', 'total_students')
    list_filter   = ('status', 'session_date')
    search_fields = ('staff__user__first_name', 'staff__user__last_name')
    readonly_fields = ('avg_attention', 'total_students', 'frames_processed',
                       'processing_time_sec', 'error_message', 'created_at', 'updated_at')


@admin.register(StudentAttentionScore)
class StudentAttentionScoreAdmin(admin.ModelAdmin):
    list_display  = ('session', 'student_name', 'roll_no', 'avg_attention', 'dominant_emotion')
    list_filter   = ('session',)
    search_fields = ('student_name', 'roll_no')


@admin.register(FrameEmotionLog)
class FrameEmotionLogAdmin(admin.ModelAdmin):
    list_display = ('session', 'frame_index', 'timestamp_sec', 'face_count', 'avg_attention')
    list_filter  = ('session',)
