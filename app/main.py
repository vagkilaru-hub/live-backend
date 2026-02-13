from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime
import pytz
import asyncio
import json

from app.websocket_manager import manager
from app.ai_processor import analyzer

# IST Timezone
IST = pytz.timezone('Asia/Kolkata')

def get_ist_timestamp():
    """Get current timestamp in IST"""
    return datetime.now(IST).isoformat()

# Initialize FastAPI app
app = FastAPI(
    title="Live Feedback System",
    description="Real-Time Student Attention Monitoring",
    version="2.0.0"
)

# Configure CORS - CRITICAL FIX FOR VERCEL
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://feedback-system-pigak94ps-vagdevis-projects-1b93f082.vercel.app",
        "https://feedback-system-tau-ten.vercel.app",
        "https://feedback-system-jyr19zbi9-vagdevis-projects-1b93f082.vercel.app",
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
        "message": "Live Feedback System API",
        "version": "2.0.0",
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

@app.websocket("/ws/student/{room_id}/{student_id}")
async def student_websocket(
    websocket: WebSocket,
    room_id: str,
    student_id: str,
    name: str = Query(..., description="Student name")
):
    """WebSocket endpoint for students"""
    
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
            'id': 'teacher',
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
            
            if msg_type == "attention_update":
                detection_data = data.get("data", {})
                status = detection_data.get('status', 'attentive')
                
                print("=" * 80)
                print(f"📥 RECEIVED FROM {name}: {status.upper()}")
                print(f"   Timestamp: {get_ist_timestamp()}")
                print("=" * 80)
                
                # Analyze attention
                analyzed_status, confidence, analysis = analyzer.analyze_attention(student_id, detection_data)
                
                # Update student status in manager
                await manager.update_student_attention(room_id, student_id, {
                    "status": analyzed_status,
                    "confidence": confidence
                })
                print(f"✅ Updated student status in manager: {analyzed_status}")
                
                # Generate alert - IMMEDIATE
                alert = analyzer.generate_alert(student_id, name, analyzed_status, analysis)
                
                if alert:
                    if alert['alert_type'] == 'clear_alert':
                        print("🟢" * 40)
                        print(f"🟢 CLEARING ALERT FOR: {name}")
                        print("🟢" * 40)
                        
                        try:
                            await manager.broadcast_to_room_teachers(room_id, {
                                "type": "clear_alert",
                                "data": {"student_id": student_id}
                            })
                            print(f"✅ Clear alert SENT to teachers in room {room_id}")
                        except Exception as e:
                            print(f"❌ Error sending clear alert: {e}")
                    
                    else:
                        print("🔴" * 40)
                        print(f"🔴 SENDING ALERT: {alert['message']}")
                        print(f"   Severity: {alert['severity']}")
                        print(f"   Type: {alert['alert_type']}")
                        print("🔴" * 40)
                        
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
                        
                        try:
                            await manager.broadcast_to_room_teachers(room_id, alert_message)
                            print(f"✅ Alert SENT to teachers in room {room_id}")
                            print(f"📤 Alert data: {json.dumps(alert_message, indent=2)}")
                        except Exception as e:
                            print(f"❌ Error sending alert: {e}")
                else:
                    print(f"ℹ️ No alert change needed for {name} (status: {analyzed_status})")
            
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


@app.websocket("/ws/teacher")
async def teacher_websocket(
    websocket: WebSocket,
    room_id: str = Query(None, description="Optional: Join existing room"),
    name: str = Query("Teacher", description="Teacher name")
):
    """WebSocket endpoint for teachers"""
    
    # Accept connection FIRST
    await websocket.accept()
    print(f"✅ Teacher WebSocket accepted")
    
    # Check if teacher already has a room (reconnection)
    existing_room = None
    for rid, teachers in manager.rooms_teachers.items():
        if rid in manager.room_ids:
            existing_room = rid
            break
    
    # Create or reuse room
    created_room_id = None
    async with manager.lock:
        if existing_room and not room_id:
            # Reuse existing room on reconnection
            created_room_id = existing_room
            if websocket not in manager.rooms_teachers[created_room_id]:
                manager.rooms_teachers[created_room_id].append(websocket)
            print(f"🔄 Teacher reconnected to existing room: {created_room_id}")
        elif room_id and room_id in manager.rooms_teachers:
            # Join specific room
            created_room_id = room_id
            if websocket not in manager.rooms_teachers[room_id]:
                manager.rooms_teachers[room_id].append(websocket)
            print(f"👨‍🏫 Teacher joined existing room: {created_room_id}")
        else:
            # Create NEW room only if no existing room
            created_room_id = manager.generate_room_id()
            manager.rooms_teachers[created_room_id] = [websocket]
            manager.rooms_students[created_room_id] = {}
            manager.rooms_students_info[created_room_id] = {}
            # CRITICAL: Store room_id PERMANENTLY
            manager.room_ids[created_room_id] = {
                'created_at': get_ist_timestamp(),
                'teacher_count': 1
            }
            print(f"✅ Created NEW room: {created_room_id}")
            print(f"🔒 Room {created_room_id} stored permanently")
        
        manager.teacher_rooms[websocket] = created_room_id
        manager.teacher_names[websocket] = name
    
    # Get current students
    students_list = []
    if created_room_id in manager.rooms_students_info:
        students_list = list(manager.rooms_students_info[created_room_id].values())
    
    # Send room_created IMMEDIATELY
    try:
        await websocket.send_json({
            "type": "room_created",
            "data": {
                "room_id": created_room_id,
                "students": students_list,
                "timestamp": get_ist_timestamp()
            }
        })
        print(f"📤 Sent room_created: {created_room_id}")
        print(f"   Students in room: {len(students_list)}")
    except Exception as e:
        print(f"❌ Error sending room_created: {e}")
        await manager.disconnect_teacher(websocket)
        return
    
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
            
            if msg_type == "heartbeat":
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
            
            elif msg_type == "webrtc_offer":
                # Broadcast WebRTC offer to all students in room
                offer_data = data.get("offer")
                target_student_id = data.get("target_id")
                await manager.broadcast_to_room_students(created_room_id, {
                    "type": "webrtc_offer",
                    "data": {
                        "offer": offer_data,
                        "target_id": target_student_id
                    }
                })
            
            elif msg_type == "webrtc_answer":
                # Forward answer to specific student
                answer_data = data.get("answer")
                target_student_id = data.get("target_id")
                if target_student_id and created_room_id in manager.rooms_students:
                    student_ws = manager.rooms_students[created_room_id].get(target_student_id)
                    if student_ws:
                        await student_ws.send_json({
                            "type": "webrtc_answer",
                            "data": {"answer": answer_data}
                        })
            
            elif msg_type == "webrtc_ice_candidate":
                # Forward ICE candidate
                candidate_data = data.get("candidate")
                target_id = data.get("target_id")
                
                if target_id:
                    # Send to specific student
                    if created_room_id in manager.rooms_students:
                        student_ws = manager.rooms_students[created_room_id].get(target_id)
                        if student_ws:
                            await student_ws.send_json({
                                "type": "webrtc_ice_candidate",
                                "data": {"candidate": candidate_data}
                            })
                else:
                    # Broadcast to all students
                    await manager.broadcast_to_room_students(created_room_id, {
                        "type": "webrtc_ice_candidate",
                        "data": {"candidate": candidate_data}
                    })
    
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


# For local development
if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)