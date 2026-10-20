import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _

from .models import Camera
from services.go2rtc import sync_camera_to_go2rtc, remove_camera_from_go2rtc, discover_camera_streams
from services.recorder import start_camera_recording, stop_camera_recording


# ==========================================
# AUTHENTICATION VIEWS & APIS
# ==========================================

@require_http_methods(["GET", "POST"])
def login_view(request):
    """Render login page or authenticate user."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        # Handles both JSON API and HTML Form submissions
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.POST.get('username')
            password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if request.content_type == 'application/json':
                return JsonResponse({'success': True, 'is_admin': user.is_staff or user.is_superuser})
            return redirect('dashboard')
        else:
            msg = _('Invalid username or password.')
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'error': msg}, status=401)
            return render(request, 'registration/login.html', {'error': msg})

    return render(request, 'registration/login.html')


@login_required
@require_http_methods(["POST", "GET"])
def logout_view(request):
    """Log out the current user."""
    logout(request)
    if request.content_type == 'application/json':
        return JsonResponse({'success': True})
    return redirect('login')


@login_required
@require_http_methods(["GET"])
def current_user_api(request):
    """Return info about the logged-in user and their role."""
    return JsonResponse({
        'username': request.user.username,
        'is_admin': request.user.is_staff or request.user.is_superuser
    })


# ==========================================
# DASHBOARD & CAMERA MANAGEMENT APIS
# ==========================================

@login_required
@require_http_methods(["GET"])
def dashboard_view(request):
    """Render the main NVR dashboard."""
    return render(request, 'cameras/dashboard.html', {
        'is_admin': request.user.is_staff or request.user.is_superuser
    })


@login_required
@require_http_methods(["POST"])
def camera_probe_api(request):
    """API endpoint for ONVIF, RTSP, and HTTP stream auto-discovery (Admin only)."""
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': _('Forbidden: Admin access required.')}, status=403)

    try:
        payload = json.loads(request.body)
        protocol = payload.get('protocol', 'ONVIF')
        ip_address = payload.get('ip_address')
        port = payload.get('port')
        username = payload.get('username', 'admin')
        password = payload.get('password', '')
        custom_main_url = payload.get('custom_main_url')
        custom_sub_url = payload.get('custom_sub_url')

        if protocol != 'HTTP' and (not ip_address or not port):
            return JsonResponse({'success': False, 'error': _('IP address and port are required for probing.')}, status=400)

        result = discover_camera_streams(
            protocol=protocol,
            ip_address=ip_address,
            port=int(port) if port else 80,
            username=username,
            password=password,
            custom_main_url=custom_main_url,
            custom_sub_url=custom_sub_url
        )
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET", "POST"])
def camera_list_create(request):
    """
    GET: List all cameras (Available to all logged-in users).
    POST: Create a camera (Admin only).
    """
    if request.method == "GET":
        cameras = Camera.objects.all()
        data = []
        for cam in cameras:
            data.append({
                'id': cam.id,
                'name': cam.name,
                'ip_address': cam.ip_address,
                'port': cam.port,
                'protocol': cam.protocol,
                'username': cam.username,
                'stream_sub': cam.stream_sub_name,
                'stream_main': cam.stream_main_name,
                'is_active': cam.is_active,
                'record_enabled': cam.record_enabled,
                'retention_days': cam.retention_days,
                'segment_duration_minutes': cam.segment_duration_minutes,
                'record_path': cam.record_path or '',
            })
        return JsonResponse({'cameras': data})

    elif request.method == "POST":
        if not (request.user.is_staff or request.user.is_superuser):
            return JsonResponse({'error': _('Forbidden: Admin access required.')}, status=403)

        try:
            payload = json.loads(request.body)
            cam = Camera.objects.create(
                name=payload.get('name'),
                ip_address=payload.get('ip_address'),
                port=payload.get('port', 554 if payload.get('protocol') == 'RTSP' else 8899),
                username=payload.get('username', 'admin'),
                password=payload.get('password') or '',
                protocol=payload.get('protocol', 'ONVIF'),
                custom_main_url=payload.get('custom_main_url'),
                custom_sub_url=payload.get('custom_sub_url'),
                is_active=payload.get('is_active', True),
                record_enabled=payload.get('record_enabled', False),
                retention_days=payload.get('retention_days', 7),
                segment_duration_minutes=payload.get('segment_duration_minutes', 15),
                record_path=payload.get('record_path')
            )
            
            if cam.is_active:
                sync_camera_to_go2rtc(cam)
                if cam.record_enabled:
                    start_camera_recording(cam)

            return JsonResponse({'status': 'created', 'id': cam.id}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def camera_detail_update_delete(request, pk):
    """
    GET: View camera details (All logged-in users).
    PUT/DELETE: Modify or remove camera (Admin only).
    """
    cam = get_object_or_404(Camera, pk=pk)

    if request.method == "GET":
        return JsonResponse({
            'id': cam.id,
            'name': cam.name,
            'ip_address': cam.ip_address,
            'port': cam.port,
            'protocol': cam.protocol,
            'username': cam.username,
            'password': cam.password if (request.user.is_staff or request.user.is_superuser) else '***',
            'custom_main_url': cam.custom_main_url or '',
            'custom_sub_url': cam.custom_sub_url or '',
            'is_active': cam.is_active,
            'record_enabled': cam.record_enabled,
            'retention_days': cam.retention_days,
            'segment_duration_minutes': cam.segment_duration_minutes,
            'record_path': cam.record_path or '',
        })

    # Mutation endpoints are strictly restricted to Admin/Superuser
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': _('Forbidden: Admin access required.')}, status=403)

    if request.method == "PUT":
        try:
            payload = json.loads(request.body)
            cam.name = payload.get('name', cam.name)
            cam.ip_address = payload.get('ip_address', cam.ip_address)
            cam.port = payload.get('port', cam.port)
            cam.protocol = payload.get('protocol', cam.protocol)
            cam.username = payload.get('username', cam.username)
            if 'password' in payload and payload['password'] != '':
                cam.password = payload['password']
            cam.custom_main_url = payload.get('custom_main_url')
            cam.custom_sub_url = payload.get('custom_sub_url')

            cam.is_active = payload.get('is_active', cam.is_active)
            cam.record_enabled = payload.get('record_enabled', cam.record_enabled)
            cam.retention_days = payload.get('retention_days', cam.retention_days)
            cam.segment_duration_minutes = payload.get('segment_duration_minutes', cam.segment_duration_minutes)
            cam.record_path = payload.get('record_path')
            
            cam.save()

            if cam.is_active:
                sync_camera_to_go2rtc(cam)
                start_camera_recording(cam) if cam.record_enabled else stop_camera_recording(cam.id)
            else:
                stop_camera_recording(cam.id)
                remove_camera_from_go2rtc(cam)

            return JsonResponse({'status': 'updated'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    elif request.method == "DELETE":
        try:
            stop_camera_recording(cam.id)
            remove_camera_from_go2rtc(cam)
            cam.delete()
            return JsonResponse({'status': 'deleted'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)