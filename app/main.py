from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime
import pytz
import asyncio
import json

# FIXED IMPORTS
from app.websocket_manager import manager
from app.ai_processor import analyzer

# IST Timezone
IST = pytz.timezone('Asia/Kolkata')

def get_ist_timestamp():
    """Get current timestamp in IST"""
    return datetime.now(IST).isoformat()

# Initialize FastAPI app
app = FastAPI(
    title="Live Feedback System with WebRTC Audio",
    description="Real-Time Student Attention Monitoring + Two-Way Audio",
    version="3.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://feedback-system-pigak94ps-vagdevis-projects-1b93f082.vercel.app",
        "https://feedback-system-tau-ten.vercel.app",
        "https://feedback-system-jyr19zbi9-vagdevis-projects-1b93f082.vercel.app",
        "https://live-frontend-murex.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Live Feedback System API with WebRTC",
        "version": "3.0.0",
        "status": "running",
        "active_rooms": len(manager.rooms_teachers),
        "timestamp": get_ist_timestamp()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "rooms": len(manager.rooms_teachers),
        "total_students": sum(len(students) for students in manager.rooms_students.values()),
        "features": ["attention_detection", "webrtc_audio", "chat"],
        "timestamp": get_ist_timestamp()
    }

@app.get("/room/{room_id}/exists")
async def check_room(room_id: str):
    """Check if room exists"""
    exists = manager.room_exists(room_id)
    return {
        "exists": exists,
        "room_id": room_id,
        "timestamp": get_ist_timestamp()
    }

@app.websocket("/ws/teacher")
async def teacher_websocket(
    websocket: WebSocket,
    room_id: str = Query(None, description="Optional: Join existing room"),
    name: str = Query("Teacher", description="Teacher name")
):
    """WebSocket endpoint for teachers with WebRTC audio support"""
    
    created_room_id = await manager.connect_teacher(websocket, name)
    print(f"✅ Teacher '{name}' connected with room: {created_room_id}")
    
    # Get current students
    students_list = []
    if created_room_id in manager.rooms_students_info:
        students_list = list(manager.rooms_students_info[created_room_id].values())
    
    # Send room_created message
    await websocket.send_json({
        "type": "room_created",
        "data": {
            "room_id": created_room_id,
            "students": students_list,
            "timestamp": get_ist_timestamp()
        }
    })
    
    # Heartbeat task
    async def send_heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
                if websocket.client_state.name == "CONNECTED":
                    await websocket.send_json({"type": "heartbeat"})
        except:
            pass
    
    heartbeat_task = asyncio.create_task(send_heartbeat())
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            # ==================== WEBRTC AUDIO HANDLING ====================
            if msg_type in ["audio_ready", "audio_offer", "audio_answer", 
                           "audio_ice_candidate", "audio_stopped", "audio_speaking"]:
                await manager.handle_audio_message(websocket, created_room_id, data)
            
            # ==================== EXISTING HANDLERS ====================
            elif msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
            
            elif msg_type == "teacher_camera_frame":
                frame_data = data.get("frame")
                if frame_data:
                    await manager.broadcast_to_room_students(created_room_id, {
                        "type": "teacher_frame",
                        "data": {
                            "frame": frame_data,
                            "timestamp": get_ist_timestamp()
                        }
                    })
            
            elif msg_type == "request_update":
                students_list = []
                if created_room_id in manager.rooms_students_info:
                    students_list = list(manager.rooms_students_info[created_room_id].values())
                
                await websocket.send_json({
                    "type": "state_update",
                    "data": {"students": students_list}
                })
            
            elif msg_type == "chat_message":
                message = data.get("message", "")
                chat_data = {
                    "type": "chat_message",
                    "data": {
                        "user_id": "teacher",
                        "user_name": name,
                        "user_type": "teacher",
                        "message": message,
                        "timestamp": get_ist_timestamp()
                    }
                }
                await manager.broadcast_to_room_teachers(created_room_id, chat_data)
                await manager.broadcast_to_room_students(created_room_id, chat_data)
    
    except WebSocketDisconnect:
        print(f"❌ Teacher disconnected from room {created_room_id}")
        heartbeat_task.cancel()
        await manager.disconnect_teacher(websocket)
    except Exception as e:
        print(f"❌ Error in teacher websocket: {e}")
        import traceback
        traceback.print_exc()
        heartbeat_task.cancel()
        await manager.disconnect_teacher(websocket)


@app.websocket("/ws/student/{room_id}/{student_id}")
async def student_websocket(
    websocket: WebSocket,
    room_id: str,
    student_id: str,
    name: str = Query(..., description="Student name")
):
    """WebSocket endpoint for students with WebRTC audio support"""
    
    # Check if room exists
    if not manager.room_exists(room_id):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": f"Room {room_id} does not exist. Please check the room code."
        })
        await websocket.close(code=4004, reason="Room not found")
        print(f"❌ Student {name} tried to join non-existent room: {room_id}")
        return
    
    # Connect student
    success = await manager.connect_student(websocket, room_id, student_id, name)
    if not success:
        print(f"❌ Failed to connect student {name}")
        return
    
    print(f"✅ Student '{name}' joined room {room_id}")
    
    # Send participant list
    participants = []
    if room_id in manager.rooms_students_info:
        for sid, info in manager.rooms_students_info[room_id].items():
            participants.append({
                'id': sid,
                'name': info['name'],
                'type': 'student'
            })
    
    if room_id in manager.rooms_teachers and len(manager.rooms_teachers[room_id]) > 0:
        participants.append({
            'id': f'teacher_{room_id}',
            'name': 'Teacher',
            'type': 'teacher'
        })
    
    await websocket.send_json({
        "type": "participant_list",
        "data": {"participants": participants}
    })
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            # ==================== WEBRTC AUDIO HANDLING ====================
            if msg_type in ["audio_ready", "audio_offer", "audio_answer", 
                           "audio_ice_candidate", "audio_stopped", "audio_speaking"]:
                await manager.handle_audio_message(websocket, room_id, data)
            
            # ==================== EXISTING HANDLERS ====================
            elif msg_type == "attention_update":
                detection_data = data.get("data", {})
                status = detection_data.get('status', 'attentive')
                
                print("=" * 80)
                print(f"🔥 RECEIVED FROM {name}: {status.upper()}")
                print(f"   Timestamp: {get_ist_timestamp()}")
                print("=" * 80)
                
                # Analyze attention
                analyzed_status, confidence, analysis = analyzer.analyze_attention(student_id, detection_data)
                
                # Update student status
                await manager.update_student_attention(room_id, student_id, {
                    "status": analyzed_status,
                    "confidence": confidence
                })
                
                # Generate alert
                alert = analyzer.generate_alert(student_id, name, analyzed_status, analysis)
                
                if alert:
                    if alert['alert_type'] == 'clear_alert':
                        await manager.broadcast_to_room_teachers(room_id, {
                            "type": "clear_alert",
                            "data": {"student_id": student_id}
                        })
                    else:
                        alert_message = {
                            "type": "alert",
                            "data": {
                                "student_id": student_id,
                                "student_name": name,
                                "alert_type": alert['alert_type'],
                                "message": alert['message'],
                                "severity": alert['severity'],
                                "timestamp": get_ist_timestamp()
                            }
                        }
                        await manager.broadcast_to_room_teachers(room_id, alert_message)
            
            elif msg_type == "camera_frame":
                frame_data = data.get("frame")
                if frame_data:
                    await manager.broadcast_camera_frame(room_id, student_id, frame_data)
            
            elif msg_type == "chat_message":
                message = data.get("message", "")
                chat_data = {
                    "type": "chat_message",
                    "data": {
                        "user_id": student_id,
                        "user_name": name,
                        "user_type": "student",
                        "message": message,
                        "timestamp": get_ist_timestamp()
                    }
                }
                await manager.broadcast_to_room_teachers(room_id, chat_data)
                await manager.broadcast_to_room_students(room_id, chat_data)
            
            elif msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
    
    except WebSocketDisconnect:
        print(f"❌ Student '{name}' disconnected")
        await manager.disconnect_student(room_id, student_id)
        analyzer.reset_student_tracking(student_id)
    except Exception as e:
        print(f"❌ Error in student websocket: {e}")
        import traceback
        traceback.print_exc()
        await manager.disconnect_student(room_id, student_id)
        analyzer.reset_student_tracking(student_id)


# For local development
if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 8000))
    print("=" * 60)
    print("🚀 Starting Live Feedback System with WebRTC Audio")
    print("=" * 60)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)