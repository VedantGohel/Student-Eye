from django.db import models
from core.models import Staff, Student, Subject


class EngagementSession(models.Model):
    PENDING    = 'pending'
    PROCESSING = 'processing'
    DONE       = 'done'
    FAILED     = 'failed'

    STATUS_CHOICES = (
        (PENDING,    'Pending'),
        (PROCESSING, 'Processing'),
        (DONE,       'Done'),
        (FAILED,     'Failed'),
    )

    staff               = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='sessions')
    subject             = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    session_date        = models.DateField()
    video               = models.FileField(upload_to='videos/')
    annotated_video     = models.FileField(upload_to='annotated/', null=True, blank=True)
    status              = models.CharField(max_length=20, default=PENDING, choices=STATUS_CHOICES)
    avg_attention       = models.FloatField(null=True, blank=True)
    total_students      = models.IntegerField(default=0)
    frames_processed    = models.IntegerField(default=0)
    processing_time_sec = models.FloatField(null=True, blank=True)
    error_message       = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-session_date', '-created_at']

    def __str__(self):
        return f"Session {self.id} — {self.staff} — {self.session_date}"

    @property
    def attention_label(self):
        if self.avg_attention is None:
            return 'N/A'
        if self.avg_attention >= 70:
            return 'Highly Attentive'
        if self.avg_attention >= 40:
            return 'Moderately Attentive'
        return 'Distracted'


class StudentAttentionScore(models.Model):
    session          = models.ForeignKey(EngagementSession, on_delete=models.CASCADE, related_name='scores')
    student          = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attention_scores', null=True, blank=True)
    student_name     = models.CharField(max_length=200, blank=True)
    roll_no          = models.CharField(max_length=50, blank=True)

    # Core scores
    avg_attention    = models.FloatField()
    min_attention    = models.FloatField(default=0)
    max_attention    = models.FloatField(default=0)
    frames_counted   = models.IntegerField(default=0)

    # Emotion
    dominant_emotion = models.CharField(max_length=50, blank=True)

    # Head pose (averages across session)
    avg_yaw          = models.FloatField(default=0)   # left/right head turn
    avg_pitch        = models.FloatField(default=0)   # up/down head tilt
    avg_roll         = models.FloatField(default=0)   # head sideways tilt

    # Eye metrics
    avg_ear          = models.FloatField(default=0)   # Eye Aspect Ratio
    eyes_closed_pct  = models.FloatField(default=0)   # % frames eyes were closed

    # Component scores (for breakdown display)
    pose_score       = models.FloatField(default=0)   # head pose contribution
    ear_score        = models.FloatField(default=0)   # EAR contribution
    emotion_score    = models.FloatField(default=0)   # emotion contribution

    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-avg_attention']

    def __str__(self):
        name = self.student.user.get_full_name() if self.student else self.student_name
        return f"{name} — {self.avg_attention:.1f}%"

    @property
    def label(self):
        if self.avg_attention >= 70:
            return 'Attentive'
        if self.avg_attention >= 40:
            return 'Moderate'
        return 'Distracted'

    @property
    def badge_color(self):
        if self.avg_attention >= 70:
            return 'success'
        if self.avg_attention >= 40:
            return 'warning'
        return 'danger'


class FrameEmotionLog(models.Model):
    session       = models.ForeignKey(EngagementSession, on_delete=models.CASCADE, related_name='frame_logs')
    frame_index   = models.IntegerField()
    timestamp_sec = models.FloatField()
    face_count    = models.IntegerField(default=0)
    avg_attention = models.FloatField(null=True, blank=True)
    avg_yaw       = models.FloatField(null=True, blank=True)
    avg_pitch     = models.FloatField(null=True, blank=True)
    avg_ear       = models.FloatField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['frame_index']
