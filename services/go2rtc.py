import logging
import subprocess
import json
import time
import requests
import uuid

logger = logging.getLogger('zentinel')

GO2RTC_API_URL="http://localhost:1984/api"
GO2RTC_RTSP_LOOPBACK = "rtsp://127.0.0.1:8554"

COMMON_RTSP_PATTERNS = [
    {"label": "Xiongmai (XM) Standard", "main": "/user={user}&password={password}&channel=1&stream=0.sdp", "sub": "/user={user}&password={password}&channel=1&stream=1.sdp"},
    {"label": "Generico H.264 / H.265", "main": "/h264/ch1/main/av_stream", "sub": "/h264/ch1/sub/av_stream"},
    {"label": "Hikvision / EZVIZ", "main": "/Streaming/Channels/101", "sub": "/Streaming/Channels/102"},
    {"label": "Dahua / Imou", "main": "/cam/realmonitor?channel=1&subtype=0", "sub": "/cam/realmonitor?channel=1&subtype=1"},
]

# =====================================================================
# HTTP STREAM HANDLING (PROBING AND ROUTING)
# =====================================================================

def analyze_http_stream(stream_url, timeout_sec=3):
    """Analyze a raw HTTP URL with ffprobe to extract its codec and format."""
    timeout_us = str(timeout_sec * 1000000)
    logger.debug("Analyzing HTTP stream")
    cmd = [
    "ffprobe", 
    "-v", "error",
    "-select_streams", "v:0",
    "-show_entries", "stream=codec_name:format=format_name",
    "-of", "json",
    "-timeout", timeout_us,
    stream_url]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            # print("DEBUG A MANO data:", data)
            streams = data.get("streams", [])
            fmt = data.get("format", {})
            return {
                "codec": streams[0].get("codec_name", "").lower() if streams else "",
                "format": fmt.get("format_name", "").lower()
            }
    except Exception:
        pass
    return {"codec": "", "format": ""}

def get_go2rtc_source(stream_url):
    """Resolve a stream URL for go2rtc, probing HTTP streams when needed."""
    if not stream_url or not stream_url.lower().startswith(("http://", "https://")):
        
        return {"src": stream_url, "requires_transcoding": False, "warning": None}

    # Probe the HTTP URL immediately.
    info = analyze_http_stream(stream_url)

    logger.debug("HTTP stream analysis result: %s", info)
    
    # Use a safe fallback only when probing actually fails.
    if not info or not info.get("codec"):
        return {
            "src": f"ffmpeg:{stream_url}#video=h264#hardware",
            "requires_transcoding": True,
            "warning": "Unable to analyze the stream. Applied a safe transcoding fallback."
        }

    codec = str(info.get("codec", "")).lower()
    fmt = str(info.get("format", "")).lower()

    # 1. Native H.264/H.265 pass-through (zero-copy).
    if codec in ["h264", "hevc", "h265"] and ("flv" in fmt or "mp4" in fmt):
        logger.debug("Recognized FLV stream")
        return {"src": stream_url, "requires_transcoding": False, "warning": None}

    # 2. Zero-copy remuxing through FFmpeg.
    if codec in ["h264", "hevc", "h265"]:
        logger.debug("Recognized transport stream")
        return {
            "src": f"ffmpeg:{stream_url}#video=copy#audio=copy",
            "requires_transcoding": False,
            "warning": None
        }

    # 3. Transcode MJPEG and other non-native codecs.
    return {
        "src": f"ffmpeg:{stream_url}#video=h264#hardware",
        "requires_transcoding": True,
        "warning": "The stream uses a non-native codec (such as MJPEG) and requires H.264 transcoding. This increases CPU/GPU usage."
    }
# =====================================================================
# GO2RTC OPERATIONS AND PROBING
# =====================================================================

def sync_camera_to_go2rtc(camera):
    """Synchronize camera streams with go2rtc."""
    main_raw, sub_raw = camera.get_source_urls()
    
    main_info = get_go2rtc_source(main_raw)
    sub_info = get_go2rtc_source(sub_raw)

    logger.debug("Sending main stream to go2rtc: %s", main_info)
    logger.debug("Sending sub stream to go2rtc: %s", sub_info)

    try:
        requests.put(f"{GO2RTC_API_URL}/streams", params={"src": main_info["src"], "name": camera.stream_main_name}, timeout=3)
        requests.put(f"{GO2RTC_API_URL}/streams", params={"src": sub_info["src"], "name": camera.stream_sub_name}, timeout=3)
        return True
    except Exception as e:
        logger.error("Synchronization failed for camera %s", camera.id, exc_info=True)
        return False


def remove_camera_from_go2rtc(camera):
    """Remove camera streams from go2rtc."""
    try:
        requests.delete(f"{GO2RTC_API_URL}/streams", params={"src": camera.stream_main_name}, timeout=3)
        requests.delete(f"{GO2RTC_API_URL}/streams", params={"src": camera.stream_sub_name}, timeout=3)
        return True
    except Exception as e:
        logger.error("Removal failed for camera %s", camera.id, exc_info=True)
        return False


import subprocess
import json

def probe_stream_ffprobe(stream_url, timeout_sec=4):
    """Use go2rtc as a universal proxy for temporary RTSP metadata probing."""
    source_dict = get_go2rtc_source(stream_url)
    source_url = source_dict["src"]
    # 1. Generate a unique temporary ID to avoid overwriting active streams.
    temp_stream_name = f"probe_{uuid.uuid4().hex[:8]}"
    loopback_url = f"{GO2RTC_RTSP_LOOPBACK}/{temp_stream_name}"
    # 2. Register the temporary stream with go2rtc.
    try:
        put_res = requests.patch(
           f"{GO2RTC_API_URL}/streams",
           params={"name": temp_stream_name, "src": source_url},
            timeout=3
        )
        
        if put_res.status_code not in (200, 201):
            logger.error("go2rtc registration failed")
            return {
                "online": False, 
                "error": f"go2rtc registration failed (HTTP {put_res.status_code})"
            }
    except Exception as e:
        return {"online": False, "error": f"Unable to contact the go2rtc API: {e}"}

    # 3. Probe the local loopback endpoint with ffprobe.
    timeout_us = str(timeout_sec * 1000000)
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,r_frame_rate",
        "-of", "json",
        "-rtsp_transport", "tcp",
        "-analyzeduration", "8000000",  # Analyze up to five seconds of stream data.
        "-probesize", "5000000",
        "-timeout", str(timeout_us),  # Newer versions use -timeout for RTSP.
        loopback_url
    ]

    res_payload = {"online": False, "error": "Stream is unreachable"}

    try:
        start_time = time.time()
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec+1)
        
        elapsed = round(time.time() - start_time, 2)

        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                v = streams[0]
                width = v.get("width")
                height = v.get("height")
                codec = v.get("codec_name", "unk").upper()
                fps_raw = v.get("r_frame_rate", "0/0")

                try:
                    num, den = map(int, fps_raw.split('/'))
                    fps = round(num / den) if den > 0 else 0
                except Exception:
                    fps = 0

                res_payload = {
                    "online": True,
                    "resolution": f"{width}x{height}",
                    "width": width,
                    "height": height,
                    "codec": codec,
                    "fps": fps,
                    "latency_sec": elapsed
                }

    except subprocess.TimeoutExpired:
        res_payload = {"online": False, "error": f"Timeout ({timeout_sec}s)"}
    except Exception as e:
        res_payload = {"online": False, "error": str(e)}

    finally:
        # Remove the temporary stream.
        try:
            requests.delete(
                f"{GO2RTC_API_URL}/streams",
                params={"src": temp_stream_name},
                timeout=3
            )
            # the result of the api call could return a error code even if the operation was executed correctly, better to check with another probe
            check_cmd = [
                'ffprobe', '-v', 'error',
                '-rtsp_transport', 'tcp',
                '-timeout', '1000000',  # 1 second timeout
                loopback_url
            ]
            check_res = subprocess.run(check_cmd, capture_output=True, text=True)
            if check_res.returncode == 0:
                logger.error(f"Warning: Stream '{temp_stream_name}' still active after delete!")
            else:
                logger.warning(f"Stream '{temp_stream_name}' deleted correctly")
        except Exception as del_err:
            logger.error("Network error while cleaning up temporary stream '%s'", temp_stream_name, exc_info=True)

    return res_payload


def discover_camera_streams(protocol, ip_address, port, username="admin", password="", custom_main_url=None, custom_sub_url=None):
    """Scan and identify ONVIF, RTSP, or HTTP streams."""
    auth = f"{username}:{password}@" if username else ""
    discovered_options = []

    if protocol == 'HTTP':
        target_url = custom_main_url or custom_sub_url
        
        if not target_url:
            logger.error("Target stream URL is empty or None")
            return {'success': False, 'error': 'URL is empty'}

        info1 = probe_stream_ffprobe(custom_main_url)
        discovered_options.append({"name":"Main Path", "url": custom_main_url, "info": info1})
        info2 = probe_stream_ffprobe(custom_sub_url)
        discovered_options.append({"name": "Sub Path", "url": custom_sub_url, "info": info2})

        return {'success': True, 'type': 'HTTP', 'options': discovered_options}
    

    elif protocol == 'ONVIF':
        onvif_src = f"onvif://{auth}{ip_address}:{port}"
        try:
            res = requests.get(f"{GO2RTC_API_URL}/onvif", params={'src': onvif_src}, timeout=5)
            if res.status_code == 200:
                sources = res.json().get("sources", [])
                for src in sources:
                    onvif_url = src.get("url")
                    if "snapshot" in onvif_url:
                        continue
                    
                    ff_info = probe_stream_ffprobe(onvif_url)
                    discovered_options.append({
                        "name": src.get("name"),
                        "url": onvif_url,
                        "info": ff_info
                    })
                return {"success": True, "type": "ONVIF", "options": discovered_options}
            return {"success": False, "error": f"ONVIF is unreachable (HTTP {res.status_code})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    else:  # RTSP
        for p in COMMON_RTSP_PATTERNS:
            main_path = p["main"].format(user=username, password=password)
            sub_path = p["sub"].format(user=username, password=password)
            url_main = f"rtsp://{auth}{ip_address}:{port}{main_path}"
            url_sub = f"rtsp://{auth}{ip_address}:{port}{sub_path}"

            ff_main = probe_stream_ffprobe(url_main)
            if ff_main.get("online"):
                ff_sub = probe_stream_ffprobe(url_sub)
                discovered_options.append({
                    "label": p["label"],
                    "main_path": url_main,
                    "sub_path": url_sub,
                    "main_info": ff_main,
                    "sub_info": ff_sub
                })

        if discovered_options:
            return {"success": True, "type": "RTSP", "options": discovered_options}
        return {"success": False, "error": "No standard RTSP pattern responded."}
