from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .models import (
    CustomUser, Course, Subject,
    HOD, Staff, Student,
    Attendance, AttendanceReport,
    LeaveReportStudent, LeaveReportStaff,
)
from .forms import (
    AddStaffForm, EditStaffForm,
    AddStudentForm, EditStudentForm,
    CourseForm, SubjectForm,
)


# ===========================================================================
# Auth
# ===========================================================================

def login_view(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        try:
            user_obj = CustomUser.objects.get(email=email)
            username = user_obj.username
        except CustomUser.DoesNotExist:
            messages.error(request, 'Invalid email or password.')
            return render(request, 'login.html')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return _redirect_by_role(user)
        messages.error(request, 'Invalid email or password.')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


def _redirect_by_role(user):
    if user.is_superuser or user.user_type == CustomUser.HOD:
        return redirect('hod_home')
    elif user.user_type == CustomUser.STAFF:
        return redirect('staff_home')
    elif user.user_type == CustomUser.STUDENT:
        return redirect('student_home')
    return redirect('login')


# ===========================================================================
# HOD Views
# ===========================================================================

@login_required(login_url='/')
def hod_home(request):
    from engagement.models import EngagementSession
    import json

    # Engagement trend — last 10 sessions avg attention per date
    sessions_qs = EngagementSession.objects.filter(
        status='done', avg_attention__isnull=False
    ).order_by('session_date')[:10]

    trend_labels = json.dumps([str(s.session_date) for s in sessions_qs])
    trend_data   = json.dumps([float(s.avg_attention) for s in sessions_qs])

    # Subject-wise avg attention
    from django.db.models import Avg
    subject_stats = EngagementSession.objects.filter(
        status='done', avg_attention__isnull=False, subject__isnull=False
    ).values('subject__name').annotate(avg=Avg('avg_attention')).order_by('-avg')

    subj_labels = json.dumps([s['subject__name'] for s in subject_stats])
    subj_data   = json.dumps([round(s['avg'], 1) for s in subject_stats])

    context = {
        'total_students':  Student.objects.count(),
        'total_staff':     Staff.objects.count(),
        'total_courses':   Course.objects.count(),
        'total_subjects':  Subject.objects.count(),
        'recent_sessions': EngagementSession.objects.select_related(
            'staff__user', 'subject'
        ).order_by('-created_at')[:5],
        'trend_labels': trend_labels,
        'trend_data':   trend_data,
        'subj_labels':  subj_labels,
        'subj_data':    subj_data,
    }
    return render(request, 'hod_template/home.html', context)


# --- Staff Management ---

@login_required(login_url='/')
def hod_add_staff(request):
    form = AddStaffForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        if CustomUser.objects.filter(email=d['email']).exists():
            messages.error(request, 'Email already registered.')
        else:
            user = CustomUser.objects.create_user(
                username=d['email'], email=d['email'],
                password=d['password'],
                first_name=d['first_name'], last_name=d['last_name'],
                user_type=CustomUser.STAFF, address=d.get('address', ''),
            )
            Staff.objects.create(user=user, course=d.get('course'))
            messages.success(request, f"Staff {user.get_full_name()} added.")
            return redirect('hod_manage_staff')
    return render(request, 'hod_template/add_staff.html', {'form': form})


@login_required(login_url='/')
def hod_manage_staff(request):
    staff_list = Staff.objects.select_related('user', 'course').all()
    return render(request, 'hod_template/manage_staff.html', {'staff_list': staff_list})


@login_required(login_url='/')
def hod_edit_staff(request, staff_id):
    staff = get_object_or_404(Staff, id=staff_id)
    if request.method == 'POST':
        form = EditStaffForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            staff.user.first_name = d['first_name']
            staff.user.last_name  = d['last_name']
            staff.user.email      = d['email']
            staff.user.address    = d.get('address', '')
            staff.user.save()
            staff.course = d.get('course')
            staff.save()
            messages.success(request, 'Staff updated.')
            return redirect('hod_manage_staff')
    else:
        form = EditStaffForm(initial={
            'first_name': staff.user.first_name,
            'last_name':  staff.user.last_name,
            'email':      staff.user.email,
            'course':     staff.course,
            'address':    staff.user.address,
        })
    return render(request, 'hod_template/edit_staff.html', {'form': form, 'staff': staff})


@login_required(login_url='/')
def hod_delete_staff(request, staff_id):
    staff = get_object_or_404(Staff, id=staff_id)
    staff.user.delete()
    messages.success(request, 'Staff deleted.')
    return redirect('hod_manage_staff')


# --- Student Management ---

@login_required(login_url='/')
def hod_add_student(request):
    form = AddStudentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        if CustomUser.objects.filter(email=d['email']).exists():
            messages.error(request, 'Email already registered.')
        else:
            user = CustomUser.objects.create_user(
                username=d['email'], email=d['email'],
                password=d['password'],
                first_name=d['first_name'], last_name=d['last_name'],
                user_type=CustomUser.STUDENT, address=d.get('address', ''),
            )
            if request.FILES.get('profile_pic'):
                user.profile_pic = request.FILES['profile_pic']
                user.save()
            Student.objects.create(
                user=user, course=d.get('course'),
                session=d.get('session', ''), roll_no=d.get('roll_no', ''),
            )
            messages.success(request, f"Student {user.get_full_name()} added.")
            return redirect('hod_manage_students')
    return render(request, 'hod_template/add_student.html', {'form': form})


@login_required(login_url='/')
def hod_manage_students(request):
    students = Student.objects.select_related('user', 'course').all()
    return render(request, 'hod_template/manage_students.html', {'students': students})


@login_required(login_url='/')
def hod_edit_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    if request.method == 'POST':
        form = EditStudentForm(request.POST, request.FILES)
        if form.is_valid():
            d = form.cleaned_data
            student.user.first_name = d['first_name']
            student.user.last_name  = d['last_name']
            student.user.email      = d['email']
            student.user.address    = d.get('address', '')
            if request.FILES.get('profile_pic'):
                student.user.profile_pic = request.FILES['profile_pic']
            student.user.save()
            student.course  = d.get('course')
            student.session = d.get('session', '')
            student.roll_no = d.get('roll_no', '')
            student.save()
            messages.success(request, 'Student updated.')
            return redirect('hod_manage_students')
    else:
        form = EditStudentForm(initial={
            'first_name': student.user.first_name,
            'last_name':  student.user.last_name,
            'email':      student.user.email,
            'course':     student.course,
            'session':    student.session,
            'roll_no':    student.roll_no,
            'address':    student.user.address,
        })
    return render(request, 'hod_template/edit_student.html', {'form': form, 'student': student})


@login_required(login_url='/')
def hod_delete_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    student.user.delete()
    messages.success(request, 'Student deleted.')
    return redirect('hod_manage_students')


# --- Course & Subject ---

@login_required(login_url='/')
def hod_add_course(request):
    form = CourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Course added.')
        return redirect('hod_add_course')
    courses = Course.objects.all()
    return render(request, 'hod_template/add_course.html', {'form': form, 'courses': courses})


@login_required(login_url='/')
def hod_delete_course(request, course_id):
    get_object_or_404(Course, id=course_id).delete()
    messages.success(request, 'Course deleted.')
    return redirect('hod_add_course')


@login_required(login_url='/')
def hod_add_subject(request):
    form = SubjectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Subject added.')
        return redirect('hod_add_subject')
    subjects = Subject.objects.select_related('course', 'staff').all()
    return render(request, 'hod_template/add_subject.html', {'form': form, 'subjects': subjects})


@login_required(login_url='/')
def hod_delete_subject(request, subject_id):
    get_object_or_404(Subject, id=subject_id).delete()
    messages.success(request, 'Subject deleted.')
    return redirect('hod_add_subject')


@login_required(login_url='/')
def hod_sessions(request):
    from engagement.models import EngagementSession
    sessions = EngagementSession.objects.select_related(
        'staff__user', 'subject'
    ).order_by('-session_date')
    return render(request, 'hod_template/sessions.html', {'sessions': sessions})


# ===========================================================================
# Staff Views
# ===========================================================================

@login_required(login_url='/')
def staff_home(request):
    from engagement.models import EngagementSession
    import json
    try:
        staff = request.user.staff_profile
    except Exception:
        messages.error(request, 'Staff profile not found.')
        return redirect('login')

    sessions = EngagementSession.objects.filter(
        staff=staff
    ).order_by('-created_at')[:10]

    # Trend data for staff dashboard
    trend_qs = EngagementSession.objects.filter(
        staff=staff, status='done', avg_attention__isnull=False
    ).order_by('session_date')
    trend_labels = json.dumps([str(s.session_date) for s in trend_qs])
    trend_data   = json.dumps([float(s.avg_attention) for s in trend_qs])

    context = {
        'staff':          staff,
        'sessions':       sessions,
        'total_sessions': EngagementSession.objects.filter(staff=staff).count(),
        'trend_labels':   trend_labels,
        'trend_data':     trend_data,
    }
    return render(request, 'staff_template/home.html', context)


@login_required(login_url='/')
def staff_upload_session(request):
    from engagement.models import EngagementSession
    from engagement.processor import process_video_async

    try:
        staff = request.user.staff_profile
    except Exception:
        messages.error(request, 'Staff profile not found.')
        return redirect('login')

    subjects = Subject.objects.filter(staff=request.user)

    if request.method == 'POST':
        video        = request.FILES.get('video')
        subject_id   = request.POST.get('subject') or None
        session_date = request.POST.get('session_date')

        if not video:
            messages.error(request, 'Please select a video file.')
        else:
            subject = Subject.objects.filter(id=subject_id).first() if subject_id else None
            session = EngagementSession.objects.create(
                staff=staff, subject=subject,
                session_date=session_date,
                video=video,
                status=EngagementSession.PENDING,
            )
            process_video_async(session)
            messages.success(request, 'Video analysed successfully!')
            return redirect('session_detail', pk=session.id)

    return render(request, 'staff_template/upload_session.html', {'subjects': subjects})


@login_required(login_url='/')
def staff_sessions(request):
    from engagement.models import EngagementSession
    try:
        staff = request.user.staff_profile
    except Exception:
        return redirect('login')

    sessions = EngagementSession.objects.filter(
        staff=staff
    ).order_by('-created_at')
    return render(request, 'staff_template/sessions.html', {'sessions': sessions})


@login_required(login_url='/')
def session_detail(request, pk):
    from engagement.models import EngagementSession
    session = get_object_or_404(EngagementSession, pk=pk)
    return render(request, 'staff_template/session_detail.html', {'session': session})


def _auto_mark_attendance(session, scores):
    """Auto-mark attendance for students detected in the session."""
    if not session.subject or not session.subject_id:
        return
    try:
        attendance, created = Attendance.objects.get_or_create(
            subject=session.subject,
            date=session.session_date,
        )
        if created:
            # Mark present for all students linked to scores
            for score in scores:
                if score.student:
                    AttendanceReport.objects.get_or_create(
                        attendance=attendance,
                        student=score.student,
                        defaults={'status': True},
                    )
    except Exception:
        pass


@login_required(login_url='/')
def session_pdf(request, pk):
    from engagement.models import EngagementSession, StudentAttentionScore
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import cm
    import io

    session = get_object_or_404(EngagementSession, pk=pk)
    scores  = StudentAttentionScore.objects.filter(
        session=session
    ).order_by('-avg_attention')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_style = ParagraphStyle('title', fontSize=20, fontName='Helvetica-Bold',
                                 textColor=colors.HexColor('#0f3460'), spaceAfter=6)
    sub_style   = ParagraphStyle('sub', fontSize=11, textColor=colors.grey, spaceAfter=20)

    elements.append(Paragraph("StudentEye — Engagement Report", title_style))
    elements.append(Paragraph(f"Session #{session.id} | {session.session_date} | {session.subject.name if session.subject else 'General'}", sub_style))

    # Summary table
    summary_data = [
        ['Metric', 'Value'],
        ['Staff', session.staff.user.get_full_name()],
        ['Subject', session.subject.name if session.subject else '—'],
        ['Date', str(session.session_date)],
        ['Avg Attention', f"{session.avg_attention:.1f}%" if session.avg_attention else '—'],
        ['Students Detected', str(session.total_students)],
        ['Frames Processed', str(session.frames_processed)],
        ['Processing Time', f"{session.processing_time_sec}s"],
        ['Overall Label', session.attention_label],
    ]

    summary_table = Table(summary_data, colWidths=[6*cm, 10*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f3460')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 11),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f0f4ff')),
        ('FONTNAME',   (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 1), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
        ('GRID',  (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.8*cm))

    # Student scores heading
    elements.append(Paragraph("Student Attention Scores", ParagraphStyle(
        'heading2', fontSize=14, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0f3460'), spaceAfter=10
    )))

    # Student scores table
    score_data = [['#', 'Student', 'Roll No', 'Avg Attention', 'Min', 'Max', 'Emotion', 'Label']]
    for i, score in enumerate(scores, 1):
        name = score.student.user.get_full_name() if score.student else score.student_name
        score_data.append([
            str(i), name, score.roll_no or '—',
            f"{score.avg_attention:.1f}%",
            f"{score.min_attention:.1f}%",
            f"{score.max_attention:.1f}%",
            score.dominant_emotion.capitalize() if score.dominant_emotion else '—',
            score.label,
        ])

    score_table = Table(score_data, colWidths=[1*cm, 4*cm, 2*cm, 3*cm, 2*cm, 2*cm, 2.5*cm, 2.5*cm])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#533483')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
        ('GRID',  (0, 0), (-1, -1), 0.4, colors.HexColor('#dddddd')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(score_table)
    elements.append(Spacer(1, 0.8*cm))

    # Footer
    elements.append(Paragraph(
        f"Generated by StudentEye AI Engagement System — {timezone.now().strftime('%d %b %Y %H:%M')}",
        ParagraphStyle('footer', fontSize=8, textColor=colors.grey)
    ))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="session_{session.id}_report.pdf"'
    return response


@login_required(login_url='/')
def staff_take_attendance(request):
    try:
        staff = request.user.staff_profile
    except Exception:
        return redirect('login')
    subjects = Subject.objects.filter(staff=request.user)
    return render(request, 'staff_template/take_attendance.html', {'subjects': subjects})


# ===========================================================================
# Student Views
# ===========================================================================

@login_required(login_url='/')
def student_home(request):
    from engagement.models import StudentAttentionScore
    import json
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'Student profile not found.')
        return redirect('login')

    scores = StudentAttentionScore.objects.filter(
        student=student
    ).select_related('session').order_by('-session__session_date')[:10]

    avg = None
    if scores:
        avg = round(sum(s.avg_attention for s in scores) / len(scores), 1)

    # Trend data for student
    trend_labels = json.dumps([str(s.session.session_date) for s in scores])
    trend_data   = json.dumps([float(s.avg_attention) for s in scores])

    context = {
        'student':     student,
        'scores':      scores,
        'overall_avg': avg,
        'trend_labels': trend_labels,
        'trend_data':   trend_data,
    }
    return render(request, 'student_template/home.html', context)


@login_required(login_url='/')
def student_attention_history(request):
    from engagement.models import StudentAttentionScore
    try:
        student = request.user.student_profile
    except Exception:
        return redirect('login')

    scores = StudentAttentionScore.objects.filter(
        student=student
    ).select_related('session').order_by('-session__session_date')
    return render(request, 'student_template/attention_history.html', {'scores': scores})


@login_required(login_url='/')
def student_attendance(request):
    try:
        student = request.user.student_profile
    except Exception:
        return redirect('login')

    reports = AttendanceReport.objects.filter(
        student=student
    ).select_related('attendance__subject').order_by('-attendance__date')
    return render(request, 'student_template/attendance.html', {'reports': reports})


# ============================================================================
# ADD THESE FUNCTIONS TO THE BOTTOM OF core/views.py
# (Replace the existing session_live_data function with this full block)
# ============================================================================

@login_required(login_url='/')
def session_live_data(request, pk):
    """Returns current processing state as JSON. Polled every 2s by frontend."""
    from engagement.models import EngagementSession, StudentAttentionScore, FrameEmotionLog
    from collections import Counter
    import os
    from pathlib import Path
    from django.conf import settings

    session     = get_object_or_404(EngagementSession, pk=pk)
    frames      = list(FrameEmotionLog.objects.filter(
        session=session, avg_attention__isnull=False
    ).order_by('frame_index').values('timestamp_sec', 'avg_attention', 'face_count'))

    scores = list(StudentAttentionScore.objects.filter(
        session=session
    ).order_by('-avg_attention').values(
        'student_name', 'roll_no', 'avg_attention', 'min_attention', 'max_attention',
        'dominant_emotion', 'frames_counted',
        'avg_yaw', 'avg_pitch', 'avg_ear', 'eyes_closed_pct',
        'pose_score', 'ear_score', 'emotion_score',
    ))

    emotion_counter = Counter()
    for s in scores:
        if s['dominant_emotion']:
            emotion_counter[s['dominant_emotion'].capitalize()] += max(s['frames_counted'], 1)

    # Latest live frame number
    live_dir    = Path(settings.MEDIA_ROOT) / 'live_frames' / f"session_{pk}"
    live_frames = sorted(live_dir.glob("frame_*.jpg")) if live_dir.exists() else []
    latest_frame_num = int(live_frames[-1].stem.split('_')[1]) if live_frames else -1

    return JsonResponse({
        'status':           session.status,
        'frames_done':      len(frames),
        'frames_processed': session.frames_processed,
        'avg_attention':    session.avg_attention,
        'total_students':   session.total_students,
        'processing_time':  session.processing_time_sec,
        'latest_frame':     latest_frame_num,

        'timeline_labels':  [f"{f['timestamp_sec']:.0f}s" for f in frames],
        'timeline_data':    [float(f['avg_attention']) for f in frames],
        'emotion_labels':   list(emotion_counter.keys()),
        'emotion_values':   list(emotion_counter.values()),
        'score_labels':     [s['student_name'] for s in scores],
        'pose_scores':      [round(float(s['pose_score']), 1) for s in scores],
        'ear_scores':       [round(float(s['ear_score']), 1) for s in scores],
        'emotion_scores':   [round(float(s['emotion_score']), 1) for s in scores],
        'yaw_data':         [round(float(s['avg_yaw']), 1) for s in scores],
        'pitch_data':       [round(float(s['avg_pitch']), 1) for s in scores],
        'students':         scores,
    })


@login_required(login_url='/')
def session_live_frame(request, pk, frame_num):
    """Serve the latest annotated live frame JPEG."""
    from django.conf import settings
    from django.http import FileResponse, Http404
    from pathlib import Path

    frame_path = Path(settings.MEDIA_ROOT) / 'live_frames' / f"session_{pk}" / f"frame_{frame_num:04d}.jpg"
    if not frame_path.exists():
        raise Http404
    return FileResponse(open(frame_path, 'rb'), content_type='image/jpeg')


# ============================================================================
# HOD SESSION MANAGEMENT
# ============================================================================

@login_required(login_url='/')
def hod_delete_session(request, session_id):
    from engagement.models import EngagementSession
    session = get_object_or_404(EngagementSession, id=session_id)
    session.delete()
    messages.success(request, f'Session #{session_id} deleted.')
    return redirect('hod_sessions')


@login_required(login_url='/')
def hod_edit_session(request, session_id):
    from engagement.models import EngagementSession
    session = get_object_or_404(EngagementSession, id=session_id)

    if request.method == 'POST':
        subject_id   = request.POST.get('subject') or None
        session_date = request.POST.get('session_date')
        staff_id     = request.POST.get('staff') or None

        session.subject      = Subject.objects.filter(id=subject_id).first() if subject_id else None
        session.session_date = session_date

        if staff_id:
            from core.models import Staff
            staff = Staff.objects.filter(id=staff_id).first()
            if staff:
                session.staff = staff

        session.save()
        messages.success(request, f'Session #{session_id} updated.')
        return redirect('hod_sessions')

    subjects  = Subject.objects.select_related('course').all()
    all_staff = Staff.objects.select_related('user').all()
    return render(request, 'hod_template/edit_session.html', {
        'session':   session,
        'subjects':  subjects,
        'all_staff': all_staff,
    })

