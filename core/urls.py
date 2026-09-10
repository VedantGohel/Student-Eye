from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('',        views.login_view,  name='login'),
    path('logout/', views.logout_view, name='logout'),

    # HOD
    path('hod/',                             views.hod_home,            name='hod_home'),
    path('hod/add-staff/',                   views.hod_add_staff,       name='hod_add_staff'),
    path('hod/manage-staff/',                views.hod_manage_staff,    name='hod_manage_staff'),
    path('hod/edit-staff/<int:staff_id>/',   views.hod_edit_staff,      name='hod_edit_staff'),
    path('hod/delete-staff/<int:staff_id>/', views.hod_delete_staff,    name='hod_delete_staff'),
    path('hod/add-student/',                 views.hod_add_student,     name='hod_add_student'),
    path('hod/manage-students/',             views.hod_manage_students, name='hod_manage_students'),
    path('hod/edit-student/<int:student_id>/',   views.hod_edit_student,   name='hod_edit_student'),
    path('hod/delete-student/<int:student_id>/', views.hod_delete_student, name='hod_delete_student'),
    path('hod/add-course/',                  views.hod_add_course,      name='hod_add_course'),
    path('hod/delete-course/<int:course_id>/',   views.hod_delete_course,  name='hod_delete_course'),
    path('hod/add-subject/',                 views.hod_add_subject,     name='hod_add_subject'),
    path('hod/delete-subject/<int:subject_id>/', views.hod_delete_subject, name='hod_delete_subject'),
    path('hod/sessions/',                    views.hod_sessions,        name='hod_sessions'),
    path('hod/session/<int:session_id>/delete/', views.hod_delete_session, name='hod_delete_session'),
    path('hod/session/<int:session_id>/edit/',   views.hod_edit_session,   name='hod_edit_session'),

    # Staff
    path('staff/',            views.staff_home,            name='staff_home'),
    path('staff/upload/',     views.staff_upload_session,  name='staff_upload_session'),
    path('staff/sessions/',   views.staff_sessions,        name='staff_sessions'),
    path('staff/attendance/', views.staff_take_attendance, name='staff_take_attendance'),

    # Session
    path('session/<int:pk>/',     views.session_detail, name='session_detail'),
    path('session/<int:pk>/pdf/', views.session_pdf,    name='session_pdf'),
    path('session/<int:pk>/live/', views.session_live_data, name='session_live_data'),
    path('session/<int:pk>/frame/<int:frame_num>/', views.session_live_frame, name='session_live_frame'),

    # Student
    path('student/',            views.student_home,              name='student_home'),
    path('student/history/',    views.student_attention_history, name='student_attention_history'),
    path('student/attendance/', views.student_attendance,        name='student_attendance'),
]
