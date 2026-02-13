"""
Configuration file for Live Feedback System
"""
import os
from typing import List

# Environment
ENV = os.getenv("ENV", "production")

# CORS Configuration - Allow Vercel deployments
ALLOWED_ORIGINS: List[str] = [
    # Vercel deployments
    "https://feedback-system-pigak94ps-vagdevis-projects-1b93f082.vercel.app",
    "https://feedback-system-tau-ten.vercel.app",
    "https://feedback-system-jyr19zbi9-vagdevis-projects-1b93f082.vercel.app",
    # Local development
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

# WebSocket Configuration
WS_HEARTBEAT_INTERVAL = 30  # seconds
WS_TIMEOUT = 60  # seconds

# Room Configuration
ROOM_CODE_LENGTH = 5
ROOM_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excluding confusing chars like 0, O, 1, I

# Attention Tracking
ATTENTION_THRESHOLDS = {
    "distracted_duration": 10,  # seconds - trigger alert after 10s of distraction
    "looking_away_duration": 15,  # seconds - trigger alert after 15s looking away
    "consecutive_checks": 3,  # number of consecutive distracted checks before alert
}

# Alert Configuration
ALERT_COOLDOWN = 30  # seconds - minimum time between alerts for same student
ALERT_SEVERITY_LEVELS = {
    "info": 1,
    "warning": 2,
    "critical": 3,
}

# Server Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# API Configuration
API_TITLE = "Live Feedback System"
API_DESCRIPTION = "Real-Time Student Attention Monitoring for Online Classes"
API_VERSION = "2.0.0"

# Feature Flags
ENABLE_CAMERA_STREAMING = True
ENABLE_AUDIO_STREAMING = False  # Not fully implemented yet
ENABLE_SCREEN_SHARING = False
ENABLE_CHAT = True
ENABLE_ANALYTICS = True

# Performance
MAX_STUDENTS_PER_ROOM = 50
MAX_CONCURRENT_ROOMS = 100
MESSAGE_QUEUE_SIZE = 1000

# Security
ENABLE_RATE_LIMITING = True
MAX_REQUESTS_PER_MINUTE = 100
MAX_WEBSOCKET_MESSAGE_SIZE = 1024 * 1024  # 1MB

# Database (if needed in future)
DATABASE_URL = os.getenv("DATABASE_URL", None)

# Redis (if needed for scaling)
REDIS_URL = os.getenv("REDIS_URL", None)

# Timezone
TIMEZONE = "Asia/Kolkata"

# Development helpers
if DEBUG:
    # More verbose logging in debug mode
    LOG_LEVEL = "DEBUG"
    # Allow localhost without SSL
    ALLOWED_ORIGINS.extend([
        "http://localhost:*",
        "http://127.0.0.1:*",
    ])

print(f"🔧 Config loaded: ENV={ENV}, DEBUG={DEBUG}")
print(f"🌐 Allowed origins: {len(ALLOWED_ORIGINS)} configured")